"""
api.py – Chamadas à API do Mercado Livre
Session thread-local com keep-alive e retry automático.
"""

import threading
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import API_BASE_URL, PROXY, HTTP_TIMEOUT

_PROXIES = {"http": PROXY, "https": PROXY} if PROXY else {}

_local = threading.local()

_RETRY = Retry(
    total=3,
    backoff_factor=0.5,
    status_forcelist=[429, 500, 502, 503],
    allowed_methods=["GET"],
    raise_on_status=False,
)

BATCH_SIZE = 20

LISTING_LABELS = {
    "gold_special": "Clássico",
    "gold_pro":     "Premium",
    "gold":         "Ouro",
    "silver":       "Prata",
    "bronze":       "Bronze",
    "free":         "Grátis",
}

LOGISTIC_LABELS = {
    "fulfillment":   "Fulfillment",
    "cross_docking": "Cross Docking",
    "drop_off":      "Drop Off",
    "xd_drop_off":   "Agência ML",
    "self_service":  "Flex",
    "custom":        "Custom",
    "me2":           "ME2",
    "me1":           "ME1",
    "not_specified": "Não especificado",
}



def _session() -> requests.Session:
    if not hasattr(_local, "session"):
        s = requests.Session()
        adapter = HTTPAdapter(pool_connections=1, pool_maxsize=1, max_retries=_RETRY)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        _local.session = s
    return _local.session


def _get(url: str, token: str) -> dict:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    try:
        resp = _session().get(url, headers=headers, proxies=_PROXIES, timeout=HTTP_TIMEOUT)
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        print(f"[API ERRO] GET {url} -> {type(exc).__name__}: {exc}")
        return {}


def validate_token(token: str) -> dict:
    return _get(f"{API_BASE_URL}/users/me", token)


def get_products_batch(mlbs: list[str], token: str) -> dict:
    """
    GET /items?ids=MLB1,MLB2,...  (até 20 por chamada).
    Retorna dict {mlb_id: produto_dict}.
    """
    if not mlbs:
        return {}

    ids_param = ",".join(m.strip().upper() for m in mlbs)
    url = f"{API_BASE_URL}/items?ids={ids_param}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    results = {}
    try:
        resp = _session().get(url, headers=headers, proxies=_PROXIES, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        for item in resp.json():
            code = item.get("code", 0)
            body = item.get("body") or {}
            item_id = body.get("id", "")
            if code == 200 and item_id:
                results[item_id] = body
            else:
                print(f"[API BATCH] code={code} id={body.get('id') or body.get('message','?')}")
    except Exception as exc:
        print(f"[API ERRO] batch {mlbs[:3]}... -> {type(exc).__name__}: {exc}")

    return results


def search_items_by_seller_sku(user_id: str | int, sku: str, token: str) -> list[str]:
    """
    Busca os MLBs vinculados a um SKU (seller_sku) na conta do vendedor no Mercado Livre.
    GET /users/{user_id}/items/search?seller_sku={sku}
    """
    if not user_id or not sku:
        return []

    import urllib.parse
    sku_clean = str(sku).strip()
    encoded = urllib.parse.quote(sku_clean)
    
    # 1. Busca por seller_sku
    url = f"{API_BASE_URL}/users/{user_id}/items/search?seller_sku={encoded}"
    data = _get(url, token)
    results = data.get("results") or []
    
    # 2. Se não encontrou, tenta por sku direto
    if not results and data.get("paging", {}).get("total", 0) == 0:
        url_sku = f"{API_BASE_URL}/users/{user_id}/items/search?sku={encoded}"
        data_sku = _get(url_sku, token)
        results = data_sku.get("results") or []

    return [str(m).strip().upper() for m in results if str(m).startswith("MLB")]
