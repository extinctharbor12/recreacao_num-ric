#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════
  Special Collector — Federal + Loteca (somente resultados)
  ───────────────────────────────────────────────────────────────
  Coletor SEPARADO do principal (collect.py). Estas duas modalidades
  NÃO são jogos de dezenas: Federal = bilhetes premiados; Loteca = 14
  jogos de futebol (coluna 1/X/2). Por isso têm schema próprio e um
  arquivo de saída próprio: data/special.json.

  IMPORTANTE — VERIFIQUE OS CAMPOS NA 1ª EXECUÇÃO:
  Os nomes exatos dos campos do upstream para Federal/Loteca podem
  variar. Este coletor é DEFENSIVO (tenta várias chaves) e, no 1º
  registro novo de cada série, imprime as chaves cruas (DEBUG_KEYS)
  para você conferir e ajustar normalize_* se preciso. Rode uma vez
  via workflow_dispatch e olhe o log.
═══════════════════════════════════════════════════════════════════
"""

import json
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

import requests

USER_AGENT = 'Mozilla/5.0 (compatible; SeriesCollector/1.0)'

# Endpoint base montado em runtime (mesmo padrão do collect.py).
_HOST_FRAGMENTS = ['servicebus2', '.', 'caixa', '.gov.br']  # required by upstream API path
_PATH_FRAGMENTS = ['/portaldeloterias', '/api/']

def _endpoint_base():
    return 'https://' + ''.join(_HOST_FRAGMENTS) + ''.join(_PATH_FRAGMENTS)

# Apenas as duas modalidades especiais.
SPECIALS = {
    'federal': {'path': 'federal', 'kind': 'tickets'},
    'loteca':  {'path': 'loteca',  'kind': 'matches'},
}

DATA_FILE = Path(__file__).parent / 'data' / 'special.json'

_DEBUG_DONE = set()   # imprime chaves cruas só uma vez por série


def http_get_json(url, timeout=30, max_retries=4):
    last_err = None
    for attempt in range(max_retries):
        try:
            r = requests.get(url, timeout=timeout, headers={
                'User-Agent': USER_AGENT,
                'Accept': 'application/json',
            }, verify=True)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
    print(f"    ✗ falhou: {last_err}", flush=True)
    return None


def fetch_latest_id(path):
    data = http_get_json(f"{_endpoint_base()}{path}/")
    return data.get('numero') if data else None


def fetch_record(path, n):
    return http_get_json(f"{_endpoint_base()}{path}/{n}")


def parse_date(s):
    if not s:
        return None
    parts = s.split('/')
    if len(parts) != 3:
        return s
    return f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"


def _first(d, keys, default=None):
    """Primeiro valor não-vazio entre as chaves candidatas."""
    for k in keys:
        if k in d and d[k] not in (None, '', []):
            return d[k]
    return default


def _debug_keys(key, raw):
    if key in _DEBUG_DONE or not isinstance(raw, dict):
        return
    _DEBUG_DONE.add(key)
    print(f"    DEBUG_KEYS[{key}] top-level: {sorted(raw.keys())}", flush=True)
    # imprime também as chaves do primeiro item de listas, p/ mapear sub-campos
    for k, v in raw.items():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            print(f"    DEBUG_KEYS[{key}] {k}[0]: {sorted(v[0].keys())}", flush=True)


def normalize_tickets(raw):
    """FEDERAL → {id, date, prizes:[{faixa, bilhete, valor}]}."""
    if not raw:
        return None
    rid = raw.get('numero')
    if not rid:
        return None
    prizes = []
    lst = _first(raw, ['listaRateioPremio', 'listaPremios', 'premios'], []) or []
    for i, p in enumerate(lst, 1):
        if not isinstance(p, dict):
            continue
        prizes.append({
            'faixa':   _first(p, ['numeroFaixa', 'faixa'], i),
            'bilhete': str(_first(p, ['numeroBilhete', 'bilhete', 'descricaoFaixa'], '')).strip(),
            'valor':   _first(p, ['valorPremio', 'valor'], 0),
        })
    rec = {'id': rid, 'date': parse_date(raw.get('dataApuracao', '')), 'prizes': prizes}
    return rec


def normalize_matches(raw):
    """LOTECA → {id, date, matches:[{home, away, result}]}."""
    if not raw:
        return None
    rid = raw.get('numero')
    if not rid:
        return None
    # acha a lista de eventos entre chaves candidatas
    events = _first(raw, ['listaEventos', 'eventos', 'jogos', 'listaResultados', 'listaJogos'], [])
    if not isinstance(events, list):
        events = []
    matches = []
    for e in events:
        if not isinstance(e, dict):
            continue
        matches.append({
            'home':   str(_first(e, ['nomeEquipeMandante', 'mandante', 'timeMandante', 'casa'], '')).strip(),
            'away':   str(_first(e, ['nomeEquipeVisitante', 'visitante', 'timeVisitante', 'fora'], '')).strip(),
            'result': str(_first(e, ['resultado', 'sinalResultado', 'coluna', 'posicaoResultado'], '')).strip(),
        })
    # fallback: nome único do evento (ex.: "Time A x Time B")
    if not matches:
        for e in events:
            if isinstance(e, dict):
                matches.append({'home': '', 'away': '', 'result': str(_first(e, ['nomeEvento', 'descricao'], '')).strip()})
    rec = {'id': rid, 'date': parse_date(raw.get('dataApuracao', '')), 'matches': matches}
    return rec


def normalize(raw, kind, key):
    if raw:
        _debug_keys(key, raw)
    try:
        return normalize_tickets(raw) if kind == 'tickets' else normalize_matches(raw)
    except Exception as e:
        print(f"    ✗ parse error: {e}", flush=True)
        return None


def load_existing():
    if not DATA_FILE.exists():
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        return {k: [] for k in SPECIALS}
    try:
        with DATA_FILE.open('r', encoding='utf-8') as f:
            data = json.load(f)
            for k in SPECIALS:
                data.setdefault(k, [])
            return data
    except Exception as e:
        print(f"❌ Erro ao ler {DATA_FILE}: {e}", flush=True)
        sys.exit(1)


def save_data(data):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with DATA_FILE.open('w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))


def update_series(key, data):
    meta = SPECIALS[key]
    path, kind = meta['path'], meta['kind']
    print(f"\n▸ {key} ({kind})", flush=True)

    latest_remote = fetch_latest_id(path)
    if latest_remote is None:
        print("  ✗ source unavailable, keeping existing", flush=True)
        return {'added': 0, 'source_failed': True}

    existing_list = data.get(key, [])
    latest_local = max([d.get('id', 0) for d in existing_list]) if existing_list else 0
    print(f"  local={latest_local} upstream={latest_remote}", flush=True)
    if latest_remote <= latest_local:
        print("  ✓ up to date", flush=True)
        return {'added': 0, 'source_failed': False}

    missing = list(range(latest_local + 1, latest_remote + 1))
    print(f"  fetching {len(missing)} record(s)...", flush=True)

    new_records, failed = [], []
    for i, n in enumerate(missing, 1):
        rec = normalize(fetch_record(path, n), kind, key)
        if rec:
            new_records.append(rec)
            if i % 50 == 0 or i == len(missing):
                print(f"    [{i}/{len(missing)}] id {n}", flush=True)
        else:
            failed.append(n)
        time.sleep(0.4)

    if failed:
        print(f"  retrying {len(failed)} failures...", flush=True)
        for n in failed[:]:
            rec = normalize(fetch_record(path, n), kind, key)
            if rec:
                new_records.append(rec)
                failed.remove(n)
            time.sleep(1.0)
        if failed:
            print(f"  ⚠ {len(failed)} still failed: {failed[:5]}{'...' if len(failed) > 5 else ''}", flush=True)

    if new_records:
        data[key] = sorted(existing_list + new_records, key=lambda x: x.get('id', 0))
    return {'added': len(new_records), 'source_failed': False, 'still_missing': len(failed)}


def main():
    print(f"═══ Special collector started at {datetime.now(timezone.utc).isoformat()} ═══", flush=True)
    data = load_existing()

    total_new, source_failures = 0, 0
    for key in SPECIALS:
        try:
            result = update_series(key, data)
            total_new += result.get('added', 0)
            if result.get('source_failed'):
                source_failures += 1
        except Exception as e:
            print(f"  ❌ exception in {key}: {e}", flush=True)
            source_failures += 1

    if total_new > 0:
        save_data(data)
        total = sum(len(v) for v in data.values() if isinstance(v, list))
        print(f"\n✓ {total_new} new | total: {total}", flush=True)
    else:
        print("\n✓ Nothing new.", flush=True)

    if source_failures >= len(SPECIALS):
        print(f"\n❌ {source_failures}/{len(SPECIALS)} séries falharam (fonte instável). Retry next day.", flush=True)
        sys.exit(1)
    elif source_failures:
        print(f"\n⚠ {source_failures}/{len(SPECIALS)} partial failures, run considered OK.", flush=True)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Fatal: {e}", flush=True)
        sys.exit(1)
