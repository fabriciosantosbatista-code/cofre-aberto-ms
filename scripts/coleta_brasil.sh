#!/usr/bin/env bash
# Cofre Aberto MS — roda as coletas bloqueadas fora do Brasil e publica no GitHub.
# Agende no cron de uma máquina no Brasil (ver docs/coleta-brasil.md), em horário
# diferente da coleta do GitHub (04:23), por exemplo às 06:10:
#   10 6 * * *  cd ~/cofre-aberto-ms && bash scripts/coleta_brasil.sh >> ~/coleta_brasil.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."
echo "===== $(date '+%d/%m/%Y %H:%M') ====="

git fetch -q origin main
git reset -q --hard origin/main          # esta pasta só serve para a coleta: começa sempre do main

python3 scripts/coleta_brasil.py "$@"

ARQUIVOS="dados/tjms_magistrados.json dados/camaras/"
git add $ARQUIVOS
if git diff --staged --quiet; then
  echo "Sem mudanças nas fontes coletadas pelo Brasil."
  exit 0
fi
git -c user.name="Cofre Aberto Bot (Brasil)" -c user.email="bot@cofreabertoms.com.br" \
    commit -q -m "🇧🇷 Coleta pelo Brasil (TJMS, câmaras do interior) — $(date '+%d/%m/%Y %H:%M')"

for tentativa in 1 2 3 4 5; do
  if git push -q origin HEAD:main; then echo "✅ Publicado."; exit 0; fi
  echo "Push recusado (o GitHub publicou algo antes); reaplicando sobre o main… ($tentativa/5)"
  sleep $((tentativa * 10))
  git pull -q --rebase origin main
done
echo "❌ Não foi possível publicar depois de 5 tentativas."; exit 1
