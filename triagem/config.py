"""
config.py – Configurações do Meli Triagem (Filtro e Exclusão Rápida)
"""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    _here = Path(__file__).resolve().parent
    load_dotenv(_here / ".env")
    load_dotenv(_here.parent / ".env")
    load_dotenv(_here.parent.parent / ".env")
    load_dotenv()
except ImportError:
    pass

PORT = int(os.environ.get("PORT", os.environ.get("MELI_TRIAGEM_PORT", "3008")))
API_BASE_URL = os.environ.get("ML_API_BASE_URL", "https://api.mercadolibre.com")
PROXY = os.environ.get("HTTP_PROXY", None)
HTTP_TIMEOUT = int(os.environ.get("HTTP_TIMEOUT", "30"))
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "12"))

# AnyMarket Configs
ANYMARKET_API_BASE_URL = os.environ.get("ANYMARKET_API_BASE_URL", "https://api.anymarket.com.br/v2")
ANYMARKET_PLATFORM = os.environ.get("ANYMARKET_PLATFORM", "SELETA")
GUMGA_TOKEN = os.environ.get("GUMGA_TOKEN", os.environ.get("ANYMARKET_GUMGA_TOKEN", ""))

# Webhook n8n para consulta de SKUs
ANYMARKET_SKU_WEBHOOK_URL = os.environ.get(
    "ANYMARKET_SKU_WEBHOOK_URL",
    os.environ.get("N8N_SKU_WEBHOOK_URL", "")
).strip().strip("'\"")

# Database Read-Replica AnyMarket
ANYMARKET_DB_HOST = os.environ.get("ANYMARKET_DB_HOST", "").strip().strip("'\"")
ANYMARKET_DB_PORT = int(os.environ.get("ANYMARKET_DB_PORT", "5432"))
ANYMARKET_DB_NAME = os.environ.get("ANYMARKET_DB_NAME", "anymarket").strip().strip("'\"")
ANYMARKET_DB_USER = os.environ.get("ANYMARKET_DB_USER", "").strip().strip("'\"")
ANYMARKET_DB_PASSWORD = os.environ.get("ANYMARKET_DB_PASSWORD", "").strip().strip("'\"")
ANYMARKET_DB_SSLMODE = os.environ.get("ANYMARKET_DB_SSLMODE", "require").strip().strip("'\"")

# Webhook Google Sheets
GOOGLE_SHEET_WEBHOOK_URL = os.environ.get("GOOGLE_SHEET_WEBHOOK_URL", "").strip().strip("'\"")
