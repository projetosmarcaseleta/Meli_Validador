#!/bin/bash
# ============================================================
# update-vps.sh - Atualiza o Meli Triagem na VPS
# Uso: bash update-vps.sh
# ============================================================

set -e

APP_DIR="/var/www/Meli_Triagem"

echo "🔄 Atualizando Meli Triagem..."
cd "$APP_DIR"

git fetch origin main
git reset --hard origin/main

source venv/bin/activate
pip install -r requirements.txt --quiet

systemctl restart meli-triagem

echo "✅ Atualização concluída com sucesso!"
systemctl status meli-triagem --no-pager
