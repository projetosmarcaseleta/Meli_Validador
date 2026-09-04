"""
n8n_token.py – Renova o access token do Mercado Livre via webhook n8n.
Não persiste o token em disco. Fail-closed se o payload vier vazio ou ilegível.
"""

from __future__ import annotations

import requests

_TOKEN_KEYS = (
    "api_key",
    "access_token",
    "token",
    "meli_token",
    "ml_token",
    "MELI_ACCESS_TOKEN",
)

_WRAP_KEYS = ("json", "body", "data", "items", "result")

DEFAULT_MELI_TOKEN_WEBHOOK_URL = (
    "https://api.marcaseleta.shop/webhook/646be4d7-0db5-42c3-96b4-654058ef7a79"
)

_BROWSER_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ),
}


def extract_meli_token_from_payload(payload: object) -> str:
    if payload is None:
        return ""

    if isinstance(payload, str):
        token = payload.strip().strip('"').strip("'")
        return token

    if isinstance(payload, list):
        for item in payload:
            token = extract_meli_token_from_payload(item)
            if token:
                return token
        return ""

    if not isinstance(payload, dict):
        return ""

    for key in _TOKEN_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    for key in _WRAP_KEYS:
        if key in payload:
            token = extract_meli_token_from_payload(payload.get(key))
            if token:
                return token

    for value in payload.values():
        if isinstance(value, (dict, list)):
            token = extract_meli_token_from_payload(value)
            if token:
                return token

    return ""


def fetch_meli_token_from_n8n(webhook_url: str = "", timeout: int = 30) -> dict:
    url = (webhook_url or DEFAULT_MELI_TOKEN_WEBHOOK_URL).strip()
    if not url:
        return {"ok": False, "error": "Webhook de token do n8n não configurado."}

    try:
        response = requests.post(
            url,
            json={},
            headers=_BROWSER_HEADERS,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return {"ok": False, "error": f"Falha ao consultar o n8n: {exc}"}

    if response.status_code == 404:
        return {
            "ok": False,
            "error": "Webhook inativo. Ative o workflow no n8n (URL de produção /webhook/, não /webhook-test/).",
        }
    if response.status_code >= 400:
        return {
            "ok": False,
            "error": f"n8n retornou HTTP {response.status_code}.",
        }

    payload: object
    try:
        payload = response.json()
    except ValueError:
        payload = (response.text or "").strip()

    token = extract_meli_token_from_payload(payload)
    if not token:
        return {"ok": False, "error": "O n8n não devolveu um token do Mercado Livre."}

    return {"ok": True, "token": token}
