#!/bin/bash
# ============================================================
# setup-vps.sh - Script de configuração do Meli Triagem na VPS
# Uso: bash setup-vps.sh
# ============================================================

set -e

APP_DIR="/var/www/Meli_Triagem"

echo "============================================"
echo "  🚀 Setup Meli Triagem na VPS"
echo "============================================"

# 1. Instalar dependências do sistema
echo ""
echo "📦 Instalando dependências do sistema..."
apt-get update -qq
apt-get install -y python3 python3-venv python3-pip git nginx certbot python3-certbot-nginx -qq

# 2. Criar diretório se necessário
mkdir -p "$APP_DIR"
cd "$APP_DIR"

# 3. Criar ambiente virtual e instalar dependências
echo ""
echo "🐍 Criando ambiente virtual e instalando pacotes..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

# 4. Criar arquivo .env se não existir (ou copiar do Meli_Validador)
if [ ! -f "$APP_DIR/.env" ]; then
    echo ""
    echo "📝 Configurando arquivo .env..."
    if [ -f "/var/www/Meli_Validador/.env" ]; then
        echo "  Copiando credenciais do Meli_Validador..."
        cp "/var/www/Meli_Validador/.env" "$APP_DIR/.env"
        # Garante a porta 3005
        sed -i 's/PORT=.*/PORT=3005/g' "$APP_DIR/.env"
    else
        cat > "$APP_DIR/.env" << 'EOF'
PORT=3005
FLASK_DEBUG=0
SECRET_KEY=meli_triagem_secret_key_vps
EOF
    fi
fi

# 5. Instalar o serviço systemd
echo ""
echo "⚙️ Configurando serviço systemd..."
cp "$APP_DIR/deploy/meli-triagem.service" /etc/systemd/system/meli-triagem.service
systemctl daemon-reload
systemctl enable meli-triagem
systemctl restart meli-triagem

# 6. Configurar Nginx
echo ""
echo "🌐 Configurando Nginx..."
cp "$APP_DIR/deploy/nginx-meli-triagem.conf" /etc/nginx/sites-available/meli-triagem.conf
ln -sf /etc/nginx/sites-available/meli-triagem.conf /etc/nginx/sites-enabled/meli-triagem.conf
nginx -t && systemctl reload nginx

echo ""
echo "============================================"
echo "  ✅ Meli Triagem configurado com sucesso!"
echo "============================================"
echo ""
echo "  📍 Local: http://127.0.0.1:3005"
echo "  📍 Subdomínio: http://triagem.marcaseleta.shop"
echo ""
echo "  🔒 Para ativar SSL (HTTPS) com certificado gratuito:"
echo "     certbot --nginx -d triagem.marcaseleta.shop"
echo ""
echo "  🔧 Comandos úteis:"
echo "     systemctl status meli-triagem   # Ver status"
echo "     systemctl restart meli-triagem  # Reiniciar"
echo "     journalctl -u meli-triagem -f   # Ver logs em tempo real"
echo ""
