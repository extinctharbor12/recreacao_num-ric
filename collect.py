#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════
  Numeric Series Collector
  Coleta séries numéricas públicas e mantém um agregado em data/
═══════════════════════════════════════════════════════════════════
"""

import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

import requests

USER_AGENT = 'Mozilla/5.0 (compatible; SeriesCollector/1.0)'

# Pausa entre chamadas (s). 0.4 no GitHub; o PC usa COLETOR_PAUSA=2 (mais gentil).
PAUSA = float(os.environ.get('COLETOR_PAUSA', '0.4'))

# Endpoint base é montado em runtime a partir destes fragmentos
# para evitar referência textual ao provedor no código-fonte público.
_HOST_FRAGMENTS = ['servicebus2', '.', 'caixa', '.gov.br']  # NOTE: required by upstream API path
_PATH_FRAGMENTS = ['/portaldeloterias', '/api/']

def _endpoint_base():
    return 'https://' + ''.join(_HOST_FRAGMENTS) + ''.join(_PATH_FRAGMENTS)

# Codinomes em latim baseados na quantidade de elementos.
# Cada série tem um path remoto e características próprias.
SERIES = {
    'senarius':  {'path': 'megasena',      'has_extra_label': False, 'has_extra_set': False},
    'quindecim': {'path': 'lotofacil',     'has_extra_label': False, 'has_extra_set': False},
    'quinarius': {'path': 'quina',         'has_extra_label': False, 'has_extra_set': False},
    'vigintus':  {'path': 'lotomania',     'has_extra_label': False, 'has_extra_set': False},
    'septenus':  {'path': 'timemania',     'has_extra_label': False, 'has_extra_set': False},
    'duplex':    {'path': 'duplasena',     'has_extra_label': False, 'has_extra_set': False},
    'mensarius': {'path': 'diadesorte',    'has_extra_label': True,  'has_extra_set': False},
    'septemcol': {'path': 'supersete',     'has_extra_label': False, 'has_extra_set': False},
    'senatrev':  {'path': 'maismilionaria','has_extra_label': False, 'has_extra_set': True},
}

DATA_FILE = Path(__file__).parent / 'data' / 'series.json'


class Bloqueio(Exception):
    """A fonte RECUSOU (HTTP 403/429). Parar tudo na hora: sem nova tentativa
    e sem passar para as outras séries — insistir só prolonga o bloqueio."""


def http_get_json(url, timeout=30, max_retries=4):
    last_err = None
    for attempt in range(max_retries):
        try:
            r = requests.get(url, timeout=timeout, headers={
                'User-Agent': USER_AGENT,
                'Accept': 'application/json',
            }, verify=True)
            if r.status_code in (403, 429):
                raise Bloqueio(f"HTTP {r.status_code} em {url}")
            r.raise_for_status()
            return r.json()
        except Bloqueio:
            raise
        except Exception as e:
            last_err = e
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
    print(f"    ✗ falhou: {last_err}", flush=True)
    return None


def fetch_latest_id(path):
    base = _endpoint_base()
    data = http_get_json(f"{base}{path}/")
    return data.get('numero') if data else None


def fetch_record(path, n):
    base = _endpoint_base()
    return http_get_json(f"{base}{path}/{n}")


def parse_date(s):
    if not s: return None
    parts = s.split('/')
    if len(parts) != 3: return s
    return f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"


def normalize(raw, meta):
    """Convert upstream record to our generic schema."""
    if not raw: return None
    try:
        rid = raw.get('numero')
        if not rid: return None
        elements = sorted([int(n) for n in raw.get('listaDezenas', []) or []])
        if not elements: return None
        rec = {
            'id': rid,
            'date': parse_date(raw.get('dataApuracao', '')),
            'values': elements,
        }
        if meta.get('has_extra_label'):
            label = raw.get('nomeTimeCoracaoMesSorte') or raw.get('mesDeSorte')
            if label: rec['label'] = label.strip().capitalize()
        if meta.get('has_extra_set'):
            extra = raw.get('trevosSorteados') or raw.get('listaDezenasSegundoSorteio') or []
            if extra:
                rec['extra'] = sorted([int(n) for n in extra])
        return rec
    except Exception as e:
        print(f"    ✗ parse error: {e}", flush=True)
        return None


def load_existing():
    if not DATA_FILE.exists():
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        return {k: [] for k in SERIES}
    try:
        with DATA_FILE.open('r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ Erro ao ler {DATA_FILE}: {e}", flush=True)
        sys.exit(1)


def save_data(data):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with DATA_FILE.open('w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))


def update_series(key, data):
    meta = SERIES[key]
    path = meta['path']
    print(f"\n▸ {key}", flush=True)

    latest_remote = fetch_latest_id(path)
    time.sleep(PAUSA)
    if latest_remote is None:
        print(f"  ✗ source unavailable, keeping existing", flush=True)
        return {'added': 0, 'source_failed': True}

    existing_list = data.get(key, [])
    existing_ids = {d.get('id') for d in existing_list if d.get('id')}
    latest_local = max(existing_ids) if existing_ids else 0

    # Procura buracos REAIS (qualquer id ausente até o upstream), não apenas os
    # acima do maior id local. Assim uma falha pontual num concurso do meio se
    # auto-corrige no ciclo seguinte, em vez de virar gap permanente que obriga
    # rodar o backfill.
    missing = [n for n in range(1, latest_remote + 1) if n not in existing_ids]

    print(f"  local={latest_local} upstream={latest_remote} gaps={len(missing)}", flush=True)
    if not missing:
        print(f"  ✓ up to date", flush=True)
        return {'added': 0, 'source_failed': False}

    print(f"  fetching {len(missing)} record(s)...", flush=True)

    new_records = []
    failed = []
    try:
        for i, n in enumerate(missing, 1):
            raw = fetch_record(path, n)
            rec = normalize(raw, meta)
            if rec:
                new_records.append(rec)
                if i % 50 == 0 or i == len(missing):
                    print(f"    [{i}/{len(missing)}] id {n}", flush=True)
            else:
                failed.append(n)
            time.sleep(PAUSA)

        if failed:
            print(f"  retrying {len(failed)} failures...", flush=True)
            for n in failed[:]:
                raw = fetch_record(path, n)
                rec = normalize(raw, meta)
                if rec:
                    new_records.append(rec)
                    failed.remove(n)
                time.sleep(max(1.0, PAUSA))
            if failed:
                print(f"  ⚠ {len(failed)} still failed: {failed[:5]}{'...' if len(failed)>5 else ''}", flush=True)
    finally:
        # mesmo se vier um Bloqueio no meio, o que já chegou é guardado
        if new_records:
            data[key] = sorted(existing_list + new_records, key=lambda x: x.get('id', 0))

    return {'added': len(new_records), 'source_failed': False, 'still_missing': len(failed)}


def main():
    print(f"═══ Collector started at {datetime.now(timezone.utc).isoformat()} ═══", flush=True)
    data = load_existing()

    contar = lambda d: sum(len(v) for v in d.values() if isinstance(v, list))
    antes = contar(data)
    source_failures = 0
    series_count = len(SERIES)
    bloqueio = None

    for key in SERIES.keys():
        try:
            result = update_series(key, data)
            if result.get('source_failed'):
                source_failures += 1
        except Bloqueio as e:
            bloqueio = e
            print(f"  ⛔ BLOQUEIO: {e} — parando tudo, sem nova tentativa", flush=True)
            break
        except Exception as e:
            print(f"  ❌ exception in {key}: {e}", flush=True)
            source_failures += 1

    total_new = contar(data) - antes
    if total_new > 0:
        save_data(data)
        total = sum(len(v) for k, v in data.items() if isinstance(v, list))
        print(f"\n✓ {total_new} new | total: {total}", flush=True)
    else:
        print(f"\n✓ Nothing new.", flush=True)

    if bloqueio:
        print(f"\n⛔ A fonte recusou ({bloqueio}). Nenhuma outra chamada foi feita.", flush=True)
        sys.exit(1)

    failure_rate = source_failures / series_count
    if failure_rate >= 0.5:
        print(f"\n❌ {source_failures}/{series_count} series failed (source unstable). Retry next day.", flush=True)
        sys.exit(1)
    elif source_failures > 0:
        print(f"\n⚠ {source_failures}/{series_count} partial failures, run considered OK.", flush=True)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Fatal: {e}", flush=True)
        sys.exit(1)
