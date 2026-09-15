"""Cliente HTTP para webhooks n8n (support-app / tokens ML na rede DB1)."""

from __future__ import annotations

import requests

from config import ANYMARKET_CLIENT_WEBHOOK_URL, HTTP_TIMEOUT


def client_webhook_configured() -> bool:
    return bool((ANYMARKET_CLIENT_WEBHOOK_URL or "").strip())


def post_n8n_webhook(url: str, payload: dict, *, timeout: int | None = None) -> dict | None:
    hook = (url or "").strip()
    if not hook:
        return None
    try:
        resp = requests.post(hook, json=payload, timeout=timeout or HTTP_TIMEOUT)
    except requests.RequestException as exc:
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
        return {"ok": False, "error": str(data.get("error") or "Falha na busca via n8n.")}
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
        return {"ok": False, "error": str(data.get("error") or "Falha ao carregar conta via n8n.")}
    return {"ok": True, "data": data}
