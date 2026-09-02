#!/bin/bash
# ============================================================
# setup-vps.sh - Setup do Meli Validador na VPS
# Executar na VPS como root ou com sudo:
# bash setup-vps.sh
# ============================================================

set -e

APP_DIR="/var/www/Meli_Validador"
REPO_URL="https://github.com/projetosmarcaseleta/Meli_Validador.git"

echo "============================================"
echo "  🚀 Setup Meli Validador na VPS"
echo "============================================"

# 1. Dependências do sistema
echo ""
echo "📦 1. Instalando pacotes do sistema..."
apt-get update -qq
apt-get install -y python3 python3-venv python3-pip git libpq-dev curl nginx -qq

# 2. Clonar ou atualizar
echo ""
echo "📥 2. Baixando repositório..."
if [ -d "$APP_DIR" ]; then
    echo "  Diretório já existe, atualizando..."
    cd "$APP_DIR"
    git fetch origin main
    git reset --hard origin/main
else
    mkdir -p /var/www
    git clone "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi

# 3. Ambiente Virtual Python e Dependências
echo ""
echo "🐍 3. Configurando ambiente virtual Python..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install --upgrade pip --quiet
pip install -r ml_exporter/requirements.txt --quiet

# 4. Criar .env se não existir
if [ ! -f "$APP_DIR/.env" ]; then
    echo ""
    echo "📝 4. Criando arquivo .env a partir do .env.example..."
    if [ -f "$APP_DIR/.env.example" ]; then
        cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    else
        cat > "$APP_DIR/.env" << 'EOF'
PORT=3002
FLASK_DEBUG=0
SECRET_KEY=sua_chave_secreta_aqui
PUBLIC_EXPORT_URL=https://validador.marcaseleta.shop/export
GUMGA_TOKEN=
ANYMARKET_PLATFORM=SELETA
EOF
    fi
    echo "  ⚠️  IMPORTANTE: Edite /var/www/Meli_Validador/.env com seus tokens reais!"
fi

# 5. Configurar Serviço Systemd
echo ""
echo "⚙️  5. Configurando serviço Systemd (meli-validador)..."
cp "$APP_DIR/deploy/meli-validador.service" /etc/systemd/system/meli-validador.service
systemctl daemon-reload
systemctl enable meli-validador
systemctl restart meli-validador

# 6. Configurar Nginx
if [ -f "$APP_DIR/deploy/nginx-meli-validador.conf" ]; then
    echo ""
    echo "🌐 6. Configurando Nginx..."
    cp "$APP_DIR/deploy/nginx-meli-validador.conf" /etc/nginx/sites-available/meli-validador.conf
    ln -sf /etc/nginx/sites-available/meli-validador.conf /etc/nginx/sites-enabled/meli-validador.conf
    nginx -t && systemctl reload nginx || echo "⚠️ Verifique as configurações de domínio no Nginx."
fi

echo ""
echo "============================================"
echo "  ✅ Setup do Meli Validador concluído!"
echo "============================================"
echo ""
echo "  📍 Status: systemctl status meli-validador"
echo "  📍 Logs:   journalctl -u meli-validador -f"
echo "  📍 Reiniciar: systemctl restart meli-validador"
echo "  📍 Atualizar: bash /var/www/Meli_Validador/deploy/update-vps.sh"
echo ""
