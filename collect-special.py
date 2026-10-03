#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════
  Special Collector — Federal + Loteca (somente resultados)
  ───────────────────────────────────────────────────────────────
  Coletor SEPARADO do principal (collect.py). Estas duas modalidades
  NÃO são jogos de dezenas: Federal = bilhetes premiados; Loteca = 14
  jogos de futebol (coluna 1/X/2). Por isso têm schema próprio e um
  arquivo de saída próprio: data/special.json.

  CAMPOS (conferidos em 03/10/2026 nos registros reais Federal 6105 e Loteca 1272):
  Federal: bilhetes em listaDezenas (ordem dos prêmios), valores em
  listaRateioPremio[faixa].valorPremio. Loteca: jogos em
  listaResultadoEquipeEsportiva (nuSequencial); o 1/X/2 sai dos gols, porque
  "resultado" vem vazio. Registro sem esse conteúdo NÃO é gravado (mesmo
  critério do app). O histórico é completado do mais novo para o mais antigo,
  ESPECIAL_LOTE concursos por série a cada execução.
═══════════════════════════════════════════════════════════════════
"""

import json
import os
import re
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

import requests

USER_AGENT = 'Mozilla/5.0 (compatible; SeriesCollector/1.0)'

# Pausa entre chamadas (s). 0.4 no GitHub; o PC usa COLETOR_PAUSA=2 (mais gentil).
PAUSA = float(os.environ.get('COLETOR_PAUSA', '0.4'))
# Concursos buscados por série a cada execução, do mais novo ao mais antigo (o reparo do
# histórico é gradual para não pesar na fonte). O PC usa um lote menor.
LOTE = int(os.environ.get('ESPECIAL_LOTE', '30'))

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
    """FEDERAL → {id, date, prizes:[{faixa, bilhete, valor}]}.
    Bilhetes premiados: listaDezenas (na ordem dos prêmios, ex. "041092");
    valores: listaRateioPremio[faixa].valorPremio. ("descricaoFaixa" é só o texto
    "1 acertos" — era o que ia para o bilhete antes, e o app descartava.)"""
    if not raw:
        return None
    rid = raw.get('numero')
    if not rid:
        return None
    bilhetes = _first(raw, ['listaDezenas', 'dezenasSorteadasOrdemSorteio'], []) or []
    valor = {}
    for p in raw.get('listaRateioPremio') or []:
        if isinstance(p, dict) and p.get('faixa') is not None:
            valor[int(p['faixa'])] = p.get('valorPremio') or 0
    prizes = [{'faixa': i, 'bilhete': str(bl).strip(), 'valor': valor.get(i, 0)} for i, bl in enumerate(bilhetes, 1)]
    return {'id': rid, 'date': parse_date(raw.get('dataApuracao', '')), 'prizes': prizes}


def _resultado(gh, ga):
    if gh is None or ga is None:
        return ''
    return '1' if gh > ga else '2' if ga > gh else 'X'


def normalize_matches(raw):
    """LOTECA → {id, date, matches:[{home, away, goalsHome, goalsAway, result, countryHome, countryAway, championship}]}.
    Jogos: listaResultadoEquipeEsportiva, na ordem de nuSequencial. O campo "resultado"
    vem vazio da fonte; o 1/X/2 sai dos gols (o mesmo formato do seed do app)."""
    if not raw:
        return None
    rid = raw.get('numero')
    if not rid:
        return None
    events = _first(raw, ['listaResultadoEquipeEsportiva'], []) or []
    if not isinstance(events, list):
        events = []
    events = sorted([e for e in events if isinstance(e, dict)], key=lambda e: e.get('nuSequencial') or 0)
    matches = []
    for e in events:
        gh, ga = e.get('nuGolEquipeUm'), e.get('nuGolEquipeDois')
        res = str(e.get('resultado') or '').strip().upper()
        matches.append({
            'home': str(e.get('nomeEquipeUm') or '').strip(),
            'away': str(e.get('nomeEquipeDois') or '').strip(),
            'goalsHome': gh, 'goalsAway': ga,
            'result': res if res in ('1', 'X', '2') else _resultado(gh, ga),
            'countryHome': str(e.get('siglaPaisUm') or '').strip(),
            'countryAway': str(e.get('siglaPaisDois') or '').strip(),
            'championship': str(e.get('nomeCampeonato') or '').strip(),
        })
    return {'id': rid, 'date': parse_date(raw.get('dataApuracao', '')), 'matches': matches}


def valido(kind, rec):
    """Registro com conteúdo útil — o mesmo critério do app (dataSync.specialSeriesUsable)."""
    if not rec:
        return False
    if kind == 'tickets':
        return any(re.fullmatch(r'\d{4,}', p.get('bilhete', '')) for p in rec.get('prizes') or [])
    return any(m.get('home') and m.get('away') for m in rec.get('matches') or [])


def normalize(raw, kind, key):
    try:
        rec = normalize_tickets(raw) if kind == 'tickets' else normalize_matches(raw)
    except Exception as e:
        print(f"    ✗ parse error: {e}", flush=True)
        return None
    return rec if valido(kind, rec) else None                 # vazio não entra


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
    time.sleep(PAUSA)
    if latest_remote is None:
        print("  ✗ source unavailable, keeping existing", flush=True)
        return {'added': 0, 'source_failed': True}

    antes = data.get(key, [])
    existing_list = [d for d in antes if valido(kind, d)]
    if len(existing_list) != len(antes):
        print(f"  removidos {len(antes) - len(existing_list)} registro(s) vazio(s) (formato antigo)", flush=True)
        data[key] = existing_list
    have = {d.get('id') for d in existing_list}
    faltam = [n for n in range(latest_remote, 0, -1) if n not in have]   # mais novo primeiro
    print(f"  local={len(existing_list)} upstream={latest_remote} faltam={len(faltam)} lote={LOTE}", flush=True)
    if not faltam:
        print("  ✓ up to date", flush=True)
        return {'added': 0, 'source_failed': False}

    missing = faltam[:LOTE]
    print(f"  fetching {len(missing)} record(s) ({missing[0]}..{missing[-1]})...", flush=True)

    new_records, failed = [], []
    try:
        for i, n in enumerate(missing, 1):
            rec = normalize(fetch_record(path, n), kind, key)
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
                rec = normalize(fetch_record(path, n), kind, key)
                if rec:
                    new_records.append(rec)
                    failed.remove(n)
                time.sleep(max(1.0, PAUSA))
            if failed:
                print(f"  ⚠ {len(failed)} still failed: {failed[:5]}{'...' if len(failed) > 5 else ''}", flush=True)
    finally:
        # mesmo se vier um Bloqueio no meio, o que já chegou é guardado
        if new_records:
            data[key] = sorted(existing_list + new_records, key=lambda x: x.get('id', 0))
    return {'added': len(new_records), 'source_failed': False, 'still_missing': len(faltam) - len(new_records)}


def main():
    print(f"═══ Special collector started at {datetime.now(timezone.utc).isoformat()} ═══", flush=True)
    data = load_existing()

    antes = {k: list(data.get(k, [])) for k in SPECIALS}
    source_failures, bloqueio = 0, None
    for key in SPECIALS:
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
    ids_antes = {k: {id(d) for d in antes[k]} for k in SPECIALS}
    ids_depois = {k: {id(d) for d in data.get(k, [])} for k in SPECIALS}
    total_new = sum(len(ids_depois[k] - ids_antes[k]) for k in SPECIALS)
    removidos = sum(len(ids_antes[k] - ids_depois[k]) for k in SPECIALS)

    if total_new > 0 or removidos > 0:
        save_data(data)
        total = sum(len(v) for v in data.values() if isinstance(v, list))
        print(f"\n✓ {total_new} new · {removidos} vazio(s) removido(s) | total: {total}", flush=True)
    else:
        print("\n✓ Nothing new.", flush=True)

    if bloqueio:
        print(f"\n⛔ A fonte recusou ({bloqueio}). Nenhuma outra chamada foi feita.", flush=True)
        sys.exit(1)

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
