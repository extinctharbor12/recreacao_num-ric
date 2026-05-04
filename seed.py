#!/usr/bin/env python3
"""
SEED — converte um draws.js local para data/series.json com codinomes.

USO:
  1. Copie seu www/data/draws.js ao lado deste arquivo
  2. python seed.py
  3. git add data/series.json && git commit -m "seed" && git push
"""
import json, re, sys
from pathlib import Path

# Mapping: chave antiga (em draws.js) → codinome (em series.json)
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

# Mapping: nomes de campos antigos → novos
FIELD_RENAME = {
    'concurso': 'id',
    'data':     'date',
    'numeros':  'values',
    'mes':      'label',
    'trevos':   'extra',
}

src = Path(__file__).parent / 'draws.js'
dst = Path(__file__).parent / 'data' / 'series.json'

if not src.exists():
    print(f"❌ Não encontrei {src}")
    print(f"   Cole seu draws.js ao lado deste arquivo.")
    sys.exit(1)

content = src.read_text(encoding='utf-8')
m = re.search(r'window\.DRAWS\s*=\s*(\{.*\})\s*;', content, re.DOTALL)
if not m:
    print(f"❌ Formato inesperado em {src}")
    sys.exit(1)

old_data = json.loads(m.group(1))
old_data.pop('meta', None)

new_data = {}
for old_key, records in old_data.items():
    if old_key not in RENAME:
        continue
    new_key = RENAME[old_key]
    if not isinstance(records, list):
        continue
    new_records = []
    for r in records:
        new_r = {}
        for old_field, val in r.items():
            new_field = FIELD_RENAME.get(old_field, old_field)
            new_r[new_field] = val
        new_records.append(new_r)
    new_data[new_key] = new_records

dst.parent.mkdir(parents=True, exist_ok=True)
with dst.open('w', encoding='utf-8') as f:
    json.dump(new_data, f, ensure_ascii=False, separators=(',', ':'))

total = sum(len(v) for v in new_data.values())
print(f"✓ {dst} criado")
print(f"  Total: {total} em {len(new_data)} series")
for k, v in new_data.items():
    print(f"    {k:12s} {len(v)}")
