"""Cliente HTTP da support-app AnyMarket (busca de conta + marketplaces)."""

from __future__ import annotations

from urllib.parse import quote
import os
import re

import requests
from urllib3.exceptions import InsecureRequestWarning

from anymarket_auth import resolve_backoffice_credentials
from config import (
    ANYMARKET_SKU_WEBHOOK_URL,
    ANYMARKET_SUPPORT_BASE_URL,
    ANYMARKET_SUPPORT_DIRECT,
    MELI_TOKEN_WEBHOOK_URL,
    SELETA_SKU_WEBHOOK_URL,
    get_support_token,
)

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

SUPPORT_PREFIX = "support:"
_QUERY_RE = re.compile(r"^[\w .,&+/\-']{2,80}$", re.UNICODE)
_OI_RE = re.compile(r"^(\d+)\.?$")


def support_client_id(oi: str | int) -> str:
    digits = "".join(ch for ch in str(oi or "") if ch.isdigit())
    return f"{SUPPORT_PREFIX}{digits}" if digits else ""


def parse_support_oi(client_id: str | None) -> str:
    raw = str(client_id or "").strip()
    if raw.lower().startswith(SUPPORT_PREFIX):
        raw = raw[len(SUPPORT_PREFIX):]
    match = _OI_RE.match(raw)
    return f"{match.group(1)}." if match else ""


def normalize_oi_value(raw: str | None) -> str:
    """Normaliza OI para formato AnyMarket (ex.: 259063586.)."""
    digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
    return f"{digits}." if digits else ""


def _headers() -> dict[str, str]:
    token = get_support_token()
    return {
        "Accept": "application/json, text/plain, */*",
        "Authorization": f"Bearer {token}",
        "Referer": f"{ANYMARKET_SUPPORT_BASE_URL}/",
    }


def is_support_configured() -> bool:
    return bool(ANYMARKET_SUPPORT_BASE_URL and get_support_token())


def support_direct_access_enabled() -> bool:
    """
    VPS/produção: URL *.internal só funciona com VPN.
    Use ANYMARKET_SUPPORT_DIRECT=1 no .env local quando a VPN alcança a support-app.
    """
    if not is_support_configured():
        return False
    base = (ANYMARKET_SUPPORT_BASE_URL or "").lower()
    if any(token in base for token in (".internal", "localhost", "127.0.0.1")):
        if ANYMARKET_SUPPORT_DIRECT:
            return True
        current = (os.environ.get("ANYMARKET_SUPPORT_DIRECT") or "").strip().lower()
        return current in ("1", "true", "yes")
    return True


def _get(path: str) -> dict:
    if not is_support_configured():
        return {"ok": False, "error": "Support App AnyMarket sem URL ou token."}
    url = f"{ANYMARKET_SUPPORT_BASE_URL}{path}"
    try:
        resp = requests.get(url, headers=_headers(), timeout=20, verify=False)
    except requests.RequestException as exc:
        return {"ok": False, "error": f"Falha ao consultar support-app: {exc}"}
    if resp.status_code == 401:
        return {"ok": False, "error": "Token da support-app expirado ou inválido."}
    if resp.status_code >= 400:
        return {"ok": False, "error": f"Support-app HTTP {resp.status_code}."}
    try:
        return {"ok": True, "data": resp.json()}
    except ValueError:
        return {"ok": False, "error": "Support-app devolveu resposta inválida."}


def search_organizations(query: str) -> dict:
    term = str(query or "").strip()
    if not _QUERY_RE.match(term):
        return {"ok": False, "error": "Busca inválida. Use nome ou OI do cliente (mín. 2 caracteres)."}
    result = _get(f"/advancedSearch/{quote(term, safe='')}")
    if not result.get("ok"):
        return result
    rows = result.get("data") or []
    if not isinstance(rows, list):
        return {"ok": False, "error": "Support-app devolveu formato inesperado na busca."}

    seen: set[str] = set()
    clients: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        oi = str(row.get("hierarchyCode") or row.get("id") or "").strip()
        client_id = support_client_id(oi)
        if not client_id or client_id in seen:
            continue
        seen.add(client_id)
        clients.append({
            "id": client_id,
            "name": str(row.get("name") or client_id).strip(),
            "oi": oi if oi.endswith(".") else f"{oi}.",
            "active": bool(row.get("active")),
            "source": "support",
        })
    clients.sort(key=lambda item: (not item["active"], item["name"].lower()))
    return {"ok": True, "data": clients}


def fetch_marketplaces(hierarchy_code: str) -> dict:
    oi = parse_support_oi(hierarchy_code) or str(hierarchy_code or "").strip()
    if not _OI_RE.match(oi.rstrip(".")):
        return {"ok": False, "error": "OI do cliente inválido."}
    if not oi.endswith("."):
        oi = f"{oi}."
    result = _get(f"/advancedSearch/marketplaces/{quote(oi, safe='.')}")
    if not result.get("ok"):
        return result
    rows = result.get("data") or []
    if not isinstance(rows, list):
        return {"ok": False, "error": "Support-app devolveu formato inesperado nos marketplaces."}
    return {"ok": True, "data": [row for row in rows if isinstance(row, dict)]}


def _is_active_marketplace(row: dict) -> bool:
    raw = row.get("active")
    if raw is True:
        return True
    if raw is False:
        return False
    return str(raw or "").strip().upper() in {"ATIVADO", "ACTIVE", "ATIVO", "1", "TRUE", "SIM", "YES"}


def _normalize_integration(name: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (name or "").upper())


def _is_meli_integration(row: dict) -> bool:
    label = str(row.get("integration") or row.get("name") or "").strip().upper()
    if not label:
        return False
    norm = _normalize_integration(label)
    if norm in {"MERCADOLIVRE", "ML", "MELI"}:
        return True
    return "MERCADO" in label and "LIVRE" in label


def _token_from_marketplace_row(row: dict) -> str:
    if not isinstance(row, dict):
        return ""
    for key in ("api_key", "apiKey", "access_token", "accessToken", "token", "value"):
        val = str(row.get(key) or "").strip()
        if val:
            return val
    return ""


def _first_integration(rows: list[dict], name: str, *, active_only: bool = False) -> dict:
    wanted = name.strip().upper()
    active = [
        row for row in rows
        if str(row.get("integration") or "").strip().upper() == wanted and _is_active_marketplace(row)
    ]
    if active:
        return active[0]
    if active_only:
        return {}
    for row in rows:
        if str(row.get("integration") or "").strip().upper() == wanted:
            return row
    return {}


def _active_meli_integration(rows: list[dict]) -> dict:
    """Integração Mercado Livre ativa (api_key = access token ML)."""
    meli_rows = [row for row in rows if isinstance(row, dict) and _is_meli_integration(row)]
    active_rows = [row for row in meli_rows if _is_active_marketplace(row)]
    return active_rows[0] if active_rows else {}


def meli_access_token_from_marketplaces(rows: list[dict]) -> str:
    row = _active_meli_integration(rows)
    return _token_from_marketplace_row(row)


def _platform_from_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", (name or "").upper())
    return cleaned or "ANYMARKET"


def resolve_support_client(client_id: str, name: str = "") -> dict:
    oi = parse_support_oi(client_id)
    if not oi:
        return {"ok": False, "error": "Cliente da support-app inválido."}

    markets = fetch_marketplaces(oi)
    if not markets.get("ok"):
        return markets

    rows = markets.get("data") or []
    gumga_row = _first_integration(rows, "GUMGA")
    ml_row = _active_meli_integration(rows)
    if not ml_row:
        ml_row = _first_integration(rows, "MERCADO LIVRE", active_only=True)
    display_name = (name or "").strip() or f"Cliente {oi.rstrip('.')}"
    integrations = []
    for row in rows:
        label = str(row.get("integration") or "").strip()
        if label and label not in integrations:
            integrations.append(label)

    gumga_raw = str(gumga_row.get("api_key") or "").strip()
    platform_guess = _platform_from_name(display_name)
    gumga_token, platform, api_ok = resolve_backoffice_credentials(
        gumga_raw,
        platform_guess,
        oi=oi,
        display_name=display_name,
    )
    payload = {
        "id": support_client_id(oi),
        "name": display_name,
        "platform": platform,
        "gumga_token": gumga_token,
        "sku_webhook_url": ANYMARKET_SKU_WEBHOOK_URL or SELETA_SKU_WEBHOOK_URL,
        "meli_token_webhook_url": MELI_TOKEN_WEBHOOK_URL,
        "oi": oi,
        "meli_access_token": meli_access_token_from_marketplaces(rows),
        "marketplaces": integrations,
        "backoffice_api_ok": api_ok,
    }
    return {"ok": True, "data": payload}
