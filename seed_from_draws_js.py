#!/usr/bin/env python3
"""
SEED INICIAL — converte seu www/data/draws.js para data/draws.json

Rode 1x apenas, depois de criar o repositório, pra colocar todos os
sorteios que você já tem dentro do GitHub. Depois disso o workflow
automático cuida de manter atualizado.

USO:
  1. Cole seu www/data/draws.js ao lado deste script (raiz do repo)
  2. python seed_from_draws_js.py
  3. Vai criar data/draws.json
  4. git add data/draws.json && git commit -m "seed inicial" && git push
"""
import json, re, sys
from pathlib import Path

src = Path(__file__).parent / 'draws.js'
dst = Path(__file__).parent / 'data' / 'draws.json'

if not src.exists():
    print(f"❌ Não encontrei {src}")
    print(f"   Cole seu www/data/draws.js ao lado deste script.")
    sys.exit(1)

content = src.read_text(encoding='utf-8')
m = re.search(r'window\.DRAWS\s*=\s*(\{.*\})\s*;', content, re.DOTALL)
if not m:
    print(f"❌ Formato inesperado em {src}")
    sys.exit(1)

data = json.loads(m.group(1))
# Remove meta if present
data.pop('meta', None)

dst.parent.mkdir(parents=True, exist_ok=True)
with dst.open('w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, separators=(',', ':'))

total = sum(len(v) for k, v in data.items() if isinstance(v, list))
print(f"✓ {dst} criado")
print(f"  Total: {total} sorteios em {len([k for k,v in data.items() if isinstance(v, list)])} modalidades")
for k, v in data.items():
    if isinstance(v, list):
        print(f"    {k:12s} {len(v)} concursos")
