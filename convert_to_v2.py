"""Converte data/draws.json (v1) para data/series.json (v2 com codinomes)."""
import json
from pathlib import Path

RENAME = {
    'mega':       'senarius',
    'lotofacil':  'quindecim',
    'quina':      'quinarius',
    'lotomania':  'vigintus',
    'timemania':  'septenus',
    'duplasena':  'duplex',
    'diasorte':   'mensarius',
    'supersete':  'septemcol',
    'milionaria': 'senatrev',
}
FIELD_RENAME = {
    'concurso': 'id',
    'data':     'date',
    'numeros':  'values',
    'mes':      'label',
    'trevos':   'extra',
}

src = Path('data/draws.json')
dst = Path('data/series.json')

with src.open('r', encoding='utf-8') as f:
    old_data = json.load(f)
old_data.pop('meta', None)

new_data = {}
for old_key, records in old_data.items():
    if old_key not in RENAME or not isinstance(records, list):
        continue
    new_key = RENAME[old_key]
    new_records = []
    for r in records:
        new_r = {FIELD_RENAME.get(k, k): v for k, v in r.items()}
        new_records.append(new_r)
    new_data[new_key] = new_records

with dst.open('w', encoding='utf-8') as f:
    json.dump(new_data, f, ensure_ascii=False, separators=(',', ':'))

total = sum(len(v) for v in new_data.values())
print(f"OK: {total} registros em {len(new_data)} séries")
for k, v in new_data.items():
    print(f"  {k:12s} {len(v)}")
