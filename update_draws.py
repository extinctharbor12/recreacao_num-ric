#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════
  ATUALIZADOR — Versão GitHub Actions (gera draws.json puro)
═══════════════════════════════════════════════════════════════════

Roda no GitHub Actions 2x por dia. Atualiza data/draws.json com os
sorteios novos das 9 modalidades numéricas da Caixa.

Diferença vs update_draws.py local:
  - Lê/escreve data/draws.json (JSON puro)
  - Sem mensagens interativas (saída concisa pra log do CI)
  - Saída sempre em UTC pra logs consistentes
"""

import json
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

import requests

USER_AGENT = 'Mozilla/5.0 (compatible; SorteAnaliseDataUpdater/1.0)'

MODALIDADES = {
    'mega':       {'api_path': 'megasena',      'has_month': False, 'has_trevos': False},
    'lotofacil':  {'api_path': 'lotofacil',     'has_month': False, 'has_trevos': False},
    'quina':      {'api_path': 'quina',         'has_month': False, 'has_trevos': False},
    'lotomania':  {'api_path': 'lotomania',     'has_month': False, 'has_trevos': False},
    'timemania':  {'api_path': 'timemania',     'has_month': False, 'has_trevos': False},
    'duplasena':  {'api_path': 'duplasena',     'has_month': False, 'has_trevos': False},
    'diasorte':   {'api_path': 'diadesorte',    'has_month': True,  'has_trevos': False},
    'supersete':  {'api_path': 'supersete',     'has_month': False, 'has_trevos': False},
    'milionaria': {'api_path': 'maismilionaria','has_month': False, 'has_trevos': True},
}

API_BASE = 'https://servicebus2.caixa.gov.br/portaldeloterias/api'
DATA_FILE = Path(__file__).parent / 'data' / 'draws.json'


def http_get_json(url, timeout=30, max_retries=4):
    """Fetch JSON with retry+backoff."""
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
                wait = 2 ** attempt
                time.sleep(wait)
    print(f"    ✗ falhou: {last_err}", flush=True)
    return None


def fetch_latest_concurso(api_path):
    url = f"{API_BASE}/{api_path}/"
    data = http_get_json(url)
    return data.get('numero') if data else None


def fetch_concurso(api_path, numero):
    url = f"{API_BASE}/{api_path}/{numero}"
    return http_get_json(url)


def parse_data(s):
    if not s: return None
    parts = s.split('/')
    if len(parts) != 3: return s
    return f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"


def caixa_to_record(api_data, meta):
    if not api_data: return None
    try:
        concurso = api_data.get('numero')
        if not concurso: return None
        dezenas = sorted([int(n) for n in api_data.get('listaDezenas', []) or []])
        if not dezenas: return None
        rec = {
            'concurso': concurso,
            'data': parse_data(api_data.get('dataApuracao', '')),
            'numeros': dezenas,
        }
        if meta.get('has_month'):
            mes = api_data.get('nomeTimeCoracaoMesSorte') or api_data.get('mesDeSorte')
            if mes: rec['mes'] = mes.strip().capitalize()
        if meta.get('has_trevos'):
            trevos = api_data.get('trevosSorteados') or api_data.get('listaDezenasSegundoSorteio') or []
            if trevos:
                rec['trevos'] = sorted([int(n) for n in trevos])
        return rec
    except Exception as e:
        print(f"    ✗ parse error: {e}", flush=True)
        return None


def load_existing():
    """Loads data/draws.json if it exists, otherwise returns empty structure."""
    if not DATA_FILE.exists():
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        return {k: [] for k in MODALIDADES}
    try:
        with DATA_FILE.open('r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ Erro ao ler {DATA_FILE}: {e}", flush=True)
        sys.exit(1)


def save_data(data):
    """Saves to data/draws.json with no extra whitespace."""
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with DATA_FILE.open('w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))


def update_modality(key, data):
    meta = MODALIDADES[key]
    api_path = meta['api_path']
    print(f"\n▸ {key.upper()}", flush=True)

    latest_remote = fetch_latest_concurso(api_path)
    if latest_remote is None:
        print(f"  ✗ API indisponível, mantendo dados existentes", flush=True)
        return 0

    existing_list = data.get(key, [])
    latest_local = max([d.get('concurso', 0) for d in existing_list]) if existing_list else 0

    print(f"  local={latest_local} oficial={latest_remote}", flush=True)
    if latest_remote <= latest_local:
        print(f"  ✓ atualizado", flush=True)
        return 0

    missing = list(range(latest_local + 1, latest_remote + 1))
    print(f"  baixando {len(missing)} concurso(s)...", flush=True)

    new_records = []
    failed = []
    for i, n in enumerate(missing, 1):
        api_data = fetch_concurso(api_path, n)
        rec = caixa_to_record(api_data, meta)
        if rec:
            new_records.append(rec)
            if i % 50 == 0 or i == len(missing):
                print(f"    [{i}/{len(missing)}] concurso {n}", flush=True)
        else:
            failed.append(n)
        time.sleep(0.4)

    # Retry failed once
    if failed:
        print(f"  retry de {len(failed)} falhas...", flush=True)
        for n in failed[:]:
            api_data = fetch_concurso(api_path, n)
            rec = caixa_to_record(api_data, meta)
            if rec:
                new_records.append(rec)
                failed.remove(n)
            time.sleep(1.0)
        if failed:
            print(f"  ⚠ {len(failed)} concurso(s) ainda com falha: {failed[:5]}{'...' if len(failed)>5 else ''}", flush=True)

    if new_records:
        data[key] = sorted(existing_list + new_records, key=lambda x: x.get('concurso', 0))

    return len(new_records)


def main():
    print(f"═══ Atualizador iniciado em {datetime.now(timezone.utc).isoformat()} ═══", flush=True)
    data = load_existing()

    total_new = 0
    for key in MODALIDADES.keys():
        added = update_modality(key, data)
        total_new += added

    if total_new > 0:
        save_data(data)
        total = sum(len(v) for k, v in data.items() if isinstance(v, list))
        print(f"\n✓ {total_new} novo(s) | total: {total}", flush=True)
    else:
        print(f"\n✓ Nada novo. Tudo em dia.", flush=True)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Erro fatal: {e}", flush=True)
        sys.exit(1)
