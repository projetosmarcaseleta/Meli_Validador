import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "ml_exporter"
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv(ROOT.parent / ".env")
load_dotenv(ROOT.parent.parent / ".env")

from config import ANYMARKET_DB_HOST, ANYMARKET_DB_USER, ANYMARKET_DB_PASSWORD
from app import app
import os

token = os.environ.get("MELI_ACCESS_TOKEN", "").strip()
client = app.test_client()
resp = client.post("/api/audit", json={"token": token, "skus": ["238601800"], "mode": "catalog"})
data = resp.get_json()
print("HTTP", resp.status_code)
print("DB_HOST", bool(ANYMARKET_DB_HOST), "DB_USER", ANYMARKET_DB_USER[:20] if ANYMARKET_DB_USER else None)
print(json.dumps({"success": data.get("success"), "warnings": data.get("warnings"), "summary": data.get("summary"), "item0": (data.get("items") or [{}])[0]}, ensure_ascii=False, indent=2))
