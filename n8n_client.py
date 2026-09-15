"""Cliente HTTP para webhooks n8n (support-app / tokens ML na rede DB1)."""

from __future__ import annotations

import requests

import json

from config import ANYMARKET_CLIENT_WEBHOOK_URL, HTTP_TIMEOUT


def format_error_value(value: object, *, fallback: str = "") -> str:
    if value is None:
        return fallback
    if isinstance(value, str):
        text = value.strip()
        if not text or text == "[object Object]":
            return fallback
        lower = text.lower()
        if "whitelabel error page" in lower or "status=401" in lower or "not authorized" in lower:
            return "401 Unauthorized — token/credencial da support-app inválida ou expirada."
        if len(text) > 280:
            return text[:280] + "…"
        return text
    if isinstance(value, dict):
        for key in ("message", "errorMessage", "description", "detail", "error"):
            part = format_error_value(value.get(key), fallback="")
            if part:
                return part
        try:
            return json.dumps(value, ensure_ascii=False)[:240]
        except TypeError:
            return fallback or str(value)
    text = str(value).strip()
    return text if text and text != "[object Object]" else (fallback or text)


def client_webhook_configured() -> bool:
    return bool((ANYMARKET_CLIENT_WEBHOOK_URL or "").strip())


def post_n8n_webhook(url: str, payload: dict, *, timeout: int | None = None) -> dict | None:
    hook = (url or "").strip()
    if not hook:
        return None
    try:
        resp = requests.post(hook, json=payload, timeout=timeout or HTTP_TIMEOUT)
    except Exception as exc:
        return {"success": False, "error": f"Falha ao chamar n8n: {exc}"}
    if resp.status_code != 200:
        return {
            "success": False,
            "error": f"n8n HTTP {resp.status_code}: {(resp.text or '')[:220]}",
        }
    if not (resp.text or "").strip():
        return {
            "success": False,
            "error": "n8n retornou corpo vazio (configure Respond to Webhook).",
        }
    try:
        data = resp.json()
    except ValueError:
        return {"success": False, "error": "Resposta n8n inválida (não-JSON)."}
    return data if isinstance(data, dict) else {"success": False, "error": "Payload n8n inválido."}


def search_clients_via_n8n(query: str) -> dict:
    if not client_webhook_configured():
        return {"ok": False, "error": "Webhook de conta (ANYMARKET_CLIENT_WEBHOOK_URL) não configurado."}
    data = post_n8n_webhook(
        ANYMARKET_CLIENT_WEBHOOK_URL,
        {"action": "search", "q": query, "query": query},
    )
    if not data:
        return {"ok": False, "error": "Sem resposta do webhook de conta."}
    if not data.get("success"):
        return {
            "ok": False,
            "error": format_error_value(data.get("error"), fallback="Falha na busca via n8n."),
        }
    clients = data.get("clients") or []
    if not isinstance(clients, list):
        return {"ok": False, "error": "Formato inesperado do n8n (clients)."}
    return {"ok": True, "data": clients}


def select_client_via_n8n(
    *,
    oi: str = "",
    client_id: str = "",
    client_name: str = "",
) -> dict:
    if not client_webhook_configured():
        return {"ok": False, "error": "Webhook de conta (ANYMARKET_CLIENT_WEBHOOK_URL) não configurado."}
    data = post_n8n_webhook(
        ANYMARKET_CLIENT_WEBHOOK_URL,
        {
            "action": "select",
            "oi": oi,
            "client_id": client_id,
            "client_name": client_name,
        },
    )
    if not data:
        return {"ok": False, "error": "Sem resposta do webhook de conta."}
    if not data.get("success"):
        return {
            "ok": False,
            "error": format_error_value(data.get("error"), fallback="Falha ao carregar conta via n8n."),
        }
    return {"ok": True, "data": data}
