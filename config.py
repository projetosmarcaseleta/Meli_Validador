"""
config.py – Configurações do Relatorios Meli
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

API_BASE_URL = os.environ.get("ML_API_BASE_URL", "https://api.mercadolibre.com")
PROXY        = os.environ.get("HTTP_PROXY", None)
HTTP_TIMEOUT = int(os.environ.get("HTTP_TIMEOUT", "30"))
MAX_WORKERS  = int(os.environ.get("MAX_WORKERS", "10"))

ANYMARKET_API_BASE_URL = os.environ.get(
    "ANYMARKET_API_BASE_URL",
    "https://api.anymarket.com.br/v2",
)
ANYMARKET_PLATFORM = os.environ.get("ANYMARKET_PLATFORM", "SELETA")
GUMGA_TOKEN = os.environ.get("GUMGA_TOKEN", os.environ.get("ANYMARKET_GUMGA_TOKEN", ""))

# Webhook n8n para consulta de SKUs (Prioritário para VPS sem acesso direto ao banco)
ANYMARKET_SKU_WEBHOOK_URL = os.environ.get(
    "ANYMARKET_SKU_WEBHOOK_URL",
    os.environ.get("N8N_SKU_WEBHOOK_URL", "")
).strip().strip("'\"")

# Database Read-Replica (Fallback para ambiente local/VPN direta)
ANYMARKET_DB_HOST = os.environ.get("ANYMARKET_DB_HOST", "").strip().strip("'\"")
ANYMARKET_DB_PORT = int(os.environ.get("ANYMARKET_DB_PORT", "5432"))
ANYMARKET_DB_NAME = os.environ.get("ANYMARKET_DB_NAME", "anymarket").strip().strip("'\"")
ANYMARKET_DB_USER = os.environ.get("ANYMARKET_DB_USER", "").strip().strip("'\"")
ANYMARKET_DB_PASSWORD = os.environ.get("ANYMARKET_DB_PASSWORD", "").strip().strip("'\"")
ANYMARKET_DB_SSLMODE = os.environ.get("ANYMARKET_DB_SSLMODE", "require").strip().strip("'\"")
ANYMARKET_OI = os.environ.get("ANYMARKET_OI", "").strip().strip("'\"")

# Webhook Google Sheets / Apps Script
GOOGLE_SHEET_WEBHOOK_URL = os.environ.get("GOOGLE_SHEET_WEBHOOK_URL", "").strip().strip("'\"")

# OpenAI Vision (pré-validação Catálogo × Tradicional)
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_API_BASE = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1").rstrip("/")
OPENAI_VISION_MODEL = os.environ.get("OPENAI_VISION_MODEL", "gpt-4o").strip() or "gpt-4o"
OPENAI_TIMEOUT_SECONDS = int(os.environ.get("OPENAI_TIMEOUT_SECONDS", "60"))
OPENAI_MAX_IMAGES_PER_SIDE = int(os.environ.get("OPENAI_MAX_IMAGES_PER_SIDE", "3"))

# Pré-validação IA (desligada por padrão — ligar com AI_PREVALIDATION_ENABLED=1)
AI_PREVALIDATION_ENABLED = os.environ.get("AI_PREVALIDATION_ENABLED", "0").strip().lower() in ("1", "true", "yes")
