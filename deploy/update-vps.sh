#!/bin/bash
# ============================================================
# update-vps.sh - Atualiza Meli Validador na VPS
# Uso: bash /var/www/Meli_Validador/deploy/update-vps.sh
# ============================================================

set -e

APP_DIR="/var/www/Meli_Validador"

echo "🔄 Atualizando Meli Validador na VPS..."
cd "$APP_DIR"

git fetch origin main
git reset --hard origin/main

source venv/bin/activate
pip install -r requirements.txt --quiet
pip install -e . --quiet

sudo systemctl restart meli-validador

echo "✅ Meli Validador atualizado e reiniciado com sucesso!"
echo "Status:"
sudo systemctl status meli-validador --no-pager
