# sorte-analise-data

Dados públicos das loterias brasileiras, atualizados automaticamente 2x ao dia.

## URLs públicas (consumidas pelo app)

- **Sorteios:** https://raw.githubusercontent.com/SEU_USUARIO/sorte-analise-data/main/data/draws.json
- **Metadata:** https://raw.githubusercontent.com/SEU_USUARIO/sorte-analise-data/main/data/metadata.json

## Modalidades

mega · lotofacil · quina · lotomania · timemania · duplasena · diasorte · supersete · milionaria

## Atualização automática

GitHub Actions roda `update_draws.py` 2x ao dia (08h e 20h horário de Brasília).
Veja a aba **Actions** acima.

## Origem dos dados

API pública não-oficial da Caixa: `servicebus2.caixa.gov.br/portaldeloterias/api`
