# 🔍 Meli Validador & Auditor

Aplicação web para auditoria e validação comparativa de anúncios do **Mercado Livre (Catálogo vs Tradicional)** com cruzamento de dados em tempo real da **AnyMarket** (via API REST e réplica de banco PostgreSQL).

---

## 🚀 Funcionalidades

- **Auditoria de Catálogo x Tradicional (por SKU ou MLB):** Identifica anúncios de catálogo e tradicionais no Mercado Livre vinculados aos SKUs ou MLBs informados.
- **Detecção de Divergências:** Valida diferenças de preço, títulos, fotos, variações e status de ativação.
- **Relatório Excel Completo:** Geração automática de planilhas `.xlsx` com formatação condicional e deltas.
- **Auditoria Visual & Webhook:** Interface moderna para aprovação/reprovação de divergências e envio automático para planilha Google (via Google Apps Script).
- **Pronto para Produção:** Suporte a Gunicorn, Systemd, Nginx reverso, Docker e GitHub Actions CI/CD.

---

## 📁 Estrutura do Repositório

```text
Meli_Validador/
├── ml_exporter/
│   ├── app.py                 # Servidor Flask e rotas
│   ├── exporter.py            # Lógica de auditoria e extração
│   ├── compare.py             # Regras de comparação e divergências
│   ├── anymarket_api.py       # Integração API REST AnyMarket
│   ├── api.py                 # Integração API Mercado Livre
│   ├── import_parser.py       # Leitor de planilhas de importação
│   ├── config.py              # Leitura de variáveis de ambiente
│   ├── requirements.txt       # Dependências Python
│   └── templates/
│       └── index.html         # Interface Web do Validador/Auditor
├── deploy/
│   ├── setup-vps.sh           # Script de instalação completa na VPS
│   ├── update-vps.sh          # Script de atualização rápida na VPS
│   ├── meli-validador.service # Configuração do serviço Systemd
│   └── nginx-meli-validador.conf # Proxy reverso Nginx
├── .github/workflows/
│   └── deploy.yml             # Pipeline de CI/CD para deploy automático
├── Dockerfile                 # Imagem Docker de produção
├── docker-compose.yml         # Compose para deploy containerizado
├── .env.example               # Modelo de variáveis de ambiente
├── iniciar_meli_validador.bat # Script de inicialização no Windows
└── README.md                  # Documentação do projeto
```

---

## ⚙️ Configuração (.env)

Copie o arquivo [.env.example](.env.example) para `.env` e preencha com suas configurações:

```bash
cp .env.example .env
```

| Variável | Descrição | Padrão |
| :--- | :--- | :--- |
| `PORT` | Porta onde o servidor Flask/Gunicorn escuta | `3002` |
| `FLASK_DEBUG` | Modo debug do Flask (`1` dev, `0` prod) | `0` |
| `SECRET_KEY` | Chave secreta de sessão | `sua_chave` |
| `PUBLIC_EXPORT_URL` | URL pública da aplicação | `https://validador.marcaseleta.shop/export` |
| `GUMGA_TOKEN` | Token da AnyMarket | - |
| `ANYMARKET_PLATFORM` | Plataforma AnyMarket | `SELETA` |
| `ANYMARKET_DB_HOST` | Host PostgreSQL AnyMarket (necessário para busca por SKU) | - |
| `ANYMARKET_DB_USER` | Usuário do banco PostgreSQL | - |
| `ANYMARKET_DB_PASSWORD` | Senha do banco PostgreSQL | - |

---

## 💻 Como Rodar Localmente

### 🪟 No Windows (PowerShell):
```powershell
# 1. Ativar o ambiente virtual (ou criar com py -3.13 -m venv venv)
.\venv\Scripts\Activate.ps1

# 2. Instalar dependências
pip install -r ml_exporter/requirements.txt

# 3. Iniciar o validador
python ml_exporter/app.py
```
Ou dê dois cliques no [iniciar_meli_validador.bat](iniciar_meli_validador.bat).  
Acesse: **[http://localhost:3002](http://localhost:3002)**

---

## 🐳 Como Rodar com Docker

```bash
docker compose up -d --build
```

---

## 🌐 Deploy na VPS (Ubuntu / Debian)

Na VPS, execute como `root` ou `sudo`:

```bash
curl -sSL https://raw.githubusercontent.com/projetosmarcaseleta/Meli_Validador/main/deploy/setup-vps.sh | bash
```

Em seguida:
1. Edite `/var/www/Meli_Validador/.env` com seus tokens reais.
2. Reinicie o serviço: `sudo systemctl restart meli-validador`.
3. Acompanhe os logs: `sudo journalctl -u meli-validador -f`.
