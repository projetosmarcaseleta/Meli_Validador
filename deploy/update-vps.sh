#!/bin/bash
# ============================================================
# update-vps.sh - Atualiza o Meli Validador E o Meli Triagem na VPS
# Uso: bash update-vps.sh
# ============================================================

set -e

APP_DIR="/var/www/Meli_Validador"

echo "🔄 Atualizando Meli Validador e Triagem na VPS..."
cd "$APP_DIR"

git fetch origin main
git reset --hard origin/main

source venv/bin/activate
pip install -r requirements.txt --quiet
if [ -f "$APP_DIR/triagem/requirements.txt" ]; then
    pip install -r "$APP_DIR/triagem/requirements.txt" --quiet
fi

# Copia eventuais atualizações de serviços e nginx
cp "$APP_DIR/deploy/meli-validador.service" /etc/systemd/system/meli-validador.service
cp "$APP_DIR/deploy/meli-triagem.service" /etc/systemd/system/meli-triagem.service
cp "$APP_DIR/deploy/nginx-meli-validador.conf" /etc/nginx/sites-available/meli-validador.conf

systemctl daemon-reload
systemctl restart meli-validador meli-triagem
nginx -t && systemctl reload nginx

echo ""
echo "✅ Atualização concluída com sucesso para ambos os serviços!"
echo ""
systemctl status meli-validador --no-pager
systemctl status meli-triagem --no-pager
