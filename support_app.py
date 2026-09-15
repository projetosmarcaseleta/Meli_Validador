"""Cliente HTTP da support-app AnyMarket (busca de conta + marketplaces)."""

from __future__ import annotations

from urllib.parse import quote
import re

import requests
from urllib3.exceptions import InsecureRequestWarning

from anymarket_auth import resolve_backoffice_credentials
from config import (
    ANYMARKET_SKU_WEBHOOK_URL,
    ANYMARKET_SUPPORT_BASE_URL,
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


def _headers() -> dict[str, str]:
    token = get_support_token()
    return {
        "Accept": "application/json, text/plain, */*",
        "Authorization": f"Bearer {token}",
        "Referer": f"{ANYMARKET_SUPPORT_BASE_URL}/",
    }


def is_support_configured() -> bool:
    return bool(ANYMARKET_SUPPORT_BASE_URL and get_support_token())


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
    return str(row.get("active") or "").strip().upper() in {"ATIVADO", "ACTIVE", "ATIVO", "1", "TRUE"}


def _first_integration(rows: list[dict], name: str) -> dict:
    wanted = name.strip().upper()
    active = [
        row for row in rows
        if str(row.get("integration") or "").strip().upper() == wanted and _is_active_marketplace(row)
    ]
    if active:
        return active[0]
    for row in rows:
        if str(row.get("integration") or "").strip().upper() == wanted:
            return row
    return {}


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
    ml_row = _first_integration(rows, "MERCADO LIVRE")
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
        "meli_access_token": str(ml_row.get("api_key") or "").strip(),
        "marketplaces": integrations,
        "backoffice_api_ok": api_ok,
    }
    return {"ok": True, "data": payload}
