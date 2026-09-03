import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "ml_exporter"
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv(ROOT.parent / ".env")
load_dotenv(ROOT.parent.parent / ".env")

from exporter import process_skus_for_catalog_audit

token = os.environ.get("MELI_ACCESS_TOKEN", "").strip()
audit = process_skus_for_catalog_audit(["238601800"], token)
out = Path(__file__).resolve().parent / "audit_238601800.json"
out.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"OK summary={audit['summary']} errors={len(audit.get('errors') or [])} file={out}")
if audit.get("items"):
    it = audit["items"][0]
    print(f"status={it.get('status_geral')} mlb_cat={it.get('mlb_cat')} mlb_trad={it.get('mlb_trad')} title={str(it.get('title',''))[:50]}")
