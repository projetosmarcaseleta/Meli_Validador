#!/bin/bash
# ============================================================
# setup-vps.sh - Script de configuração completa na VPS
# Configura o Meli Validador E o Meli Triagem juntos
# ============================================================

set -e

APP_DIR="/var/www/Meli_Validador"
REPO_URL="https://github.com/projetosmarcaseleta/Meli_Validador.git"

echo "============================================"
echo "  🚀 Setup Meli Validador + Triagem na VPS"
echo "============================================"

# 1. Instalar dependências do sistema
echo ""
echo "📦 Instalando dependências do sistema..."
apt-get update -qq
apt-get install -y python3 python3-venv python3-pip git nginx certbot python3-certbot-nginx -qq

# 2. Clonar ou atualizar repositório
echo ""
echo "📥 Clonando repositório..."
if [ -d "$APP_DIR" ]; then
    echo "  Diretório já existe, atualizando..."
    cd "$APP_DIR"
    git fetch origin main
    git reset --hard origin/main
else
    git clone "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi

# 3. Criar ambiente virtual e instalar dependências
echo ""
echo "🐍 Criando ambiente virtual..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
if [ -f "$APP_DIR/triagem/requirements.txt" ]; then
    pip install -r "$APP_DIR/triagem/requirements.txt" --quiet
fi

# 4. Criar arquivo .env se não existir
if [ ! -f "$APP_DIR/.env" ]; then
    echo ""
    echo "📝 Criando arquivo .env padrão..."
    cat > "$APP_DIR/.env" << 'EOF'
PORT=3002
FLASK_DEBUG=0
SECRET_KEY=meli_secret_key_vps
PUBLIC_EXPORT_URL=https://app.marcaseleta.shop/export
EOF
    echo "  ⚠️ Configure /var/www/Meli_Validador/.env com suas variáveis se necessário."
fi

# 5. Instalar os serviços systemd (Validador e Triagem)
echo ""
echo "⚙️ Configurando serviços systemd..."
cp "$APP_DIR/deploy/meli-validador.service" /etc/systemd/system/meli-validador.service
cp "$APP_DIR/deploy/meli-triagem.service" /etc/systemd/system/meli-triagem.service

systemctl daemon-reload
systemctl enable meli-validador meli-triagem
systemctl restart meli-validador meli-triagem

# 6. Configurar Nginx
echo ""
echo "🌐 Configurando Nginx..."
cp "$APP_DIR/deploy/nginx-meli-validador.conf" /etc/nginx/sites-available/meli-validador.conf
ln -sf /etc/nginx/sites-available/meli-validador.conf /etc/nginx/sites-enabled/meli-validador.conf
nginx -t && systemctl reload nginx

echo ""
echo "============================================"
echo "  ✅ Setup concluído com sucesso!"
echo "============================================"
echo ""
echo "  📍 Validador: https://app.marcaseleta.shop/export"
echo "  📍 Triagem:   https://triagem.marcaseleta.shop"
echo "                ou https://app.marcaseleta.shop/triagem"
echo ""
echo "  🔒 Para ativar SSL (HTTPS):"
echo "     certbot --nginx -d validador.marcaseleta.shop -d app.marcaseleta.shop -d triagem.marcaseleta.shop"
echo ""
