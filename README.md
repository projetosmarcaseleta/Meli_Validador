# 🔍 Meli Validador & Agrupador

Sistema para **auditoria, validação e agrupamento de anúncios** (PARENT_PK, family_name, gênero e atributos) no **Mercado Livre**, com interface web FastAPI/Uvicorn e suporte a CLI.

---

## 🚀 Funcionalidades

- **Auditoria e Validação em Tempo Real:** Analisa lotes de anúncios no Mercado Livre verificando consistência de marcas, modelos, gêneros e integridade de variações.
- **Normalização de PARENT_PK e family_name:** Planeja e executa a unificação e agrupamento de anúncios irmãos e variações de produtos.
- **Relatórios Detalhados & PDF:** Geração automática de relatórios em formato JSON, TXT e PDF (`pdf_validador.py`).
- **Interface Web FastAPI:** Painel moderno com streaming de logs em tempo real via NDJSON (`agrupar.web`).
- **Modo Seguro (DRY_RUN):** Simula todas as operações e visualiza o plano de agrupamento antes de aplicar alterações reais.

---

## 📁 Estrutura do Repositório

```text
Meli_Validador/
├── agrupar/
│   ├── web.py                 # Servidor FastAPI e rotas de streaming
│   ├── validador.py           # Regras de auditoria e validação de anúncios
│   ├── pipeline.py            # Orquestrador de validação e agrupamento
│   ├── plano.py               # Planejador de PUTs e atualizações
│   ├── meli.py                # Cliente da API Mercado Livre
│   ├── anymarket.py           # Consultas à réplica PostgreSQL do AnyMarket
│   ├── pdf_validador.py       # Gerador de relatórios em PDF
│   ├── config.py              # Configurações do Pydantic Settings
│   ├── __main__.py            # Ponto de entrada CLI (python -m agrupar)
│   └── static/                # Interface Web frontend (HTML/CSS/JS)
├── deploy/
│   ├── setup-vps.sh           # Script de configuração inicial na VPS
│   ├── update-vps.sh          # Script de atualização rápida na VPS
│   ├── meli-validador.service # Serviço Systemd
│   └── nginx-meli-validador.conf # Configuração de proxy Nginx
├── .github/workflows/
│   └── deploy.yml             # Pipeline de CI/CD para deploy automático
├── Dockerfile                 # Imagem Docker de produção
├── docker-compose.yml         # Compose para deploy containerizado
├── pyproject.toml             # Metadados e dependências do pacote
├── requirements.txt           # Dependências Python
├── .env.example               # Modelo de variáveis de ambiente
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
| `MELI_ACCESS_TOKEN` | Token da API do Mercado Livre | - |
| `DRY_RUN` | `true` para simulação; `false` para aplicar alterações | `true` |
| `GROUPING_UNIT` | `gender_brand_model` (padrão) ou `gender` | `gender_brand_model` |
| `REVALIDACAO_SEGUNDOS` | Tempo de espera para conferência do ML | `45` |
| `ANYMARKET_DB_HOST` | Host PostgreSQL AnyMarket (necessário para SKU) | - |
| `PORT` | Porta da aplicação web | `8765` |

---

## 💻 Como Rodar Localmente

### 🪟 Windows (PowerShell):
```powershell
# 1. Criar ambiente virtual
py -3.13 -m venv venv
.\venv\Scripts\Activate.ps1

# 2. Instalar dependências
pip install -r requirements.txt
pip install -e .

# 3. Rodar a interface web
python -m agrupar.web
```
Ou dê dois cliques no [iniciar_meli_validador.bat](iniciar_meli_validador.bat).
Acesse: **[http://localhost:8765](http://localhost:8765)**

### 💻 Executar via Linha de Comando (CLI):
```powershell
# Exemplo passando MLBs diretamente:
python -m agrupar MLB123456789 MLB987654321
```

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
