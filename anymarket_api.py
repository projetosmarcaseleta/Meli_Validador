"""
anymarket_api.py – Cliente da API Backoffice v2 do AnyMarket.

Auth: headers gumgaToken + platform em todas as chamadas.
"""

from __future__ import annotations

import re
import threading
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import (
    ANYMARKET_API_BASE_URL,
    ANYMARKET_PLATFORM,
    HTTP_TIMEOUT,
    PROXY,
)

_PROXIES = {"http": PROXY, "https": PROXY} if PROXY else {}
_local = threading.local()

_RETRY = Retry(
    total=3,
    backoff_factor=0.5,
    status_forcelist=[429, 500, 502, 503],
    allowed_methods=["GET"],
    raise_on_status=False,
)

GENDER_LABELS = {
    "MALE": "Masculino",
    "FEMALE": "Feminino",
    "BOY": "Menino",
    "GIRL": "Menina",
    "UNISSEX": "Unissex",
    "BABIES": "Bebês",
    "CHILDISH_UNISSEX": "Infantil unissex",
}


def _session() -> requests.Session:
    if not hasattr(_local, "session"):
        s = requests.Session()
        adapter = HTTPAdapter(pool_connections=2, pool_maxsize=4, max_retries=_RETRY)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        _local.session = s
    return _local.session


def _headers(gumga_token: str, platform: str | None = None) -> dict[str, str]:
    return {
        "gumgaToken": gumga_token.strip(),
        "platform": (platform or ANYMARKET_PLATFORM or "SELETA").strip(),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _content(resp: requests.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return {"message": (resp.text or "")[:300]}


def validate_gumga_token(gumga_token: str, platform: str | None = None) -> dict:
    """
    Valida o gumgaToken com uma consulta leve.
    Retorna {valid, error?, status?}.
    """
    token = (gumga_token or "").strip()
    if not token:
        return {"valid": False, "error": "Token AnyMarket vazio."}

    url = f"{ANYMARKET_API_BASE_URL.rstrip('/')}/products"
    try:
        resp = _session().get(
            url,
            headers=_headers(token, platform),
            params={"limit": 5, "offset": 0},
            proxies=_PROXIES,
            timeout=HTTP_TIMEOUT,
        )
    except Exception as exc:
        return {"valid": False, "error": f"Falha de conexão: {exc}"}

    if resp.status_code == 200:
        return {"valid": True}

    body = _content(resp)
    message = ""
    if isinstance(body, dict):
        message = str(body.get("message") or body.get("error") or "")
    if resp.status_code == 401:
        return {
            "valid": False,
            "status": 401,
            "error": message or "Token AnyMarket inválido ou usuário não registrado.",
        }
    return {
        "valid": False,
        "status": resp.status_code,
        "error": message or f"Erro HTTP {resp.status_code} na validação AnyMarket.",
    }


def get_product(product_id: int | str, gumga_token: str, platform: str | None = None) -> dict:
    """GET /products/{id} – detalhes do produto."""
    url = f"{ANYMARKET_API_BASE_URL.rstrip('/')}/products/{product_id}"
    try:
        resp = _session().get(
            url,
            headers=_headers(gumga_token, platform),
            proxies=_PROXIES,
            timeout=HTTP_TIMEOUT,
        )
        if resp.status_code == 404:
            return {}
        if resp.status_code == 401:
            body = _content(resp)
            msg = body.get("message") if isinstance(body, dict) else ""
            raise PermissionError(msg or "Token AnyMarket inválido (401).")
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else {}
    except PermissionError:
        raise
    except Exception as exc:
        print(f"[ANYMARKET ERRO] GET {url} -> {type(exc).__name__}: {exc}")
        return {}


def _extract_content_list(payload: Any) -> list:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("content", "data", "items", "skus", "products"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def _find_product_id_in_sku(item: dict) -> str | int | None:
    if item.get("productId") is not None:
        return item.get("productId")
    product = item.get("product")
    if isinstance(product, dict) and product.get("id") is not None:
        return product.get("id")
    if item.get("idProduct") is not None:
        return item.get("idProduct")
    return None


def find_product_by_partner_id(
    partner_id: str,
    gumga_token: str,
    platform: str | None = None,
) -> dict:
    """
    Localiza o produto AnyMarket pelo partnerId/SKU do cliente.
    Tenta filtros em /products e /skus e, se achar o id, chama GET /products/{id}.
    """
    sku = (partner_id or "").strip()
    if not sku:
        return {}

    base = ANYMARKET_API_BASE_URL.rstrip("/")
    headers = _headers(gumga_token, platform)

    # 1) GET /products com filtros comuns
    for params in (
        {"sku": sku, "limit": 5},
        {"partnerId": sku, "limit": 5},
        {"qi": sku, "limit": 5},
    ):
        try:
            resp = _session().get(
                f"{base}/products",
                headers=headers,
                params=params,
                proxies=_PROXIES,
                timeout=HTTP_TIMEOUT,
            )
            if resp.status_code == 401:
                body = _content(resp)
                msg = body.get("message") if isinstance(body, dict) else ""
                raise PermissionError(msg or "Token AnyMarket inválido (401).")
            if resp.status_code >= 400:
                continue
            for item in _extract_content_list(resp.json()):
                if not isinstance(item, dict):
                    continue
                # match direto no produto ou em algum SKU interno
                skus = item.get("skus") or []
                partner_ids = {
                    str((s or {}).get("partnerId") or "").strip()
                    for s in skus
                    if isinstance(s, dict)
                }
                if sku in partner_ids or str(item.get("externalIdProduct") or "").strip() == sku:
                    product_id = item.get("id")
                    if product_id is not None and not skus:
                        return get_product(product_id, gumga_token, platform) or item
                    if item.get("title") and skus:
                        return item
                    if product_id is not None:
                        return get_product(product_id, gumga_token, platform) or item
        except PermissionError:
            raise
        except Exception as exc:
            print(f"[ANYMARKET ERRO] busca products {params} -> {type(exc).__name__}: {exc}")

    # 2) GET /skus?partnerId=...
    try:
        resp = _session().get(
            f"{base}/skus",
            headers=headers,
            params={"partnerId": sku, "limit": 5},
            proxies=_PROXIES,
            timeout=HTTP_TIMEOUT,
        )
        if resp.status_code == 401:
            body = _content(resp)
            msg = body.get("message") if isinstance(body, dict) else ""
            raise PermissionError(msg or "Token AnyMarket inválido (401).")
        if resp.status_code < 400:
            for item in _extract_content_list(resp.json()):
                if not isinstance(item, dict):
                    continue
                if str(item.get("partnerId") or "").strip() != sku:
                    continue
                product_id = _find_product_id_in_sku(item)
                if product_id is not None:
                    return get_product(product_id, gumga_token, platform)
    except PermissionError:
        raise
    except Exception as exc:
        print(f"[ANYMARKET ERRO] busca skus partnerId={sku} -> {type(exc).__name__}: {exc}")

    return {}


def _chars_by_name(product: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for char in product.get("characteristics") or []:
        if not isinstance(char, dict):
            continue
        name = str(char.get("name") or "").strip().lower()
        value = str(char.get("value") or "").strip()
        if name and value:
            out[name] = value
    return out


def _char_value(chars: dict[str, str], *names: str) -> str:
    for name in names:
        key = name.strip().lower()
        if chars.get(key):
            return chars[key]
    # match parcial (ex.: "Cor do produto")
    for name in names:
        needle = name.strip().lower()
        for key, value in chars.items():
            if needle in key:
                return value
    return ""


def _sku_variation_values(sku: dict | None, *type_names: str) -> list[str]:
    """Lê description das variations do SKU filtrando por type.name (color, voltage, size)."""
    if not sku or not isinstance(sku, dict):
        return []
    needles = [n.strip().lower() for n in type_names]
    values: list[str] = []
    seen: set[str] = set()

    def _add(value: str, type_name: str = "") -> None:
        type_l = (type_name or "").strip().lower()
        if needles and type_l and not any(n in type_l for n in needles):
            return
        val = (value or "").strip()
        if not val or val in seen:
            return
        seen.add(val)
        values.append(val)

    variations = sku.get("variations")
    if isinstance(variations, list):
        for var in variations:
            if not isinstance(var, dict):
                continue
            type_obj = var.get("type") or {}
            type_name = ""
            if isinstance(type_obj, dict):
                type_name = str(type_obj.get("name") or "")
            elif isinstance(type_obj, str):
                type_name = type_obj
            _add(str(var.get("description") or var.get("value") or ""), type_name)
    elif isinstance(variations, dict):
        for type_name, value in variations.items():
            _add(str(value or ""), str(type_name or ""))
    return values


def _variation_values(product: dict, *type_names: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for sku in product.get("skus") or []:
        if not isinstance(sku, dict):
            continue
        for val in _sku_variation_values(sku, *type_names):
            if val not in seen:
                seen.add(val)
                values.append(val)
    return values


def _image_urls(product: dict) -> list[str]:
    images = list(product.get("images") or [])
    images.sort(key=lambda img: (not bool((img or {}).get("main")), (img or {}).get("index") or 0))
    urls: list[str] = []
    seen: set[str] = set()
    for image in images:
        if not isinstance(image, dict):
            continue
        url = (
            image.get("originalImage")
            or image.get("standardUrl")
            or image.get("url")
            or image.get("thumbnailUrl")
            or ""
        )
        url = str(url).strip()
        if not url:
            continue
        if url.startswith("http://"):
            url = "https://" + url[len("http://") :]
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def _resolve_kit(product: dict, chars: dict[str, str]) -> str:
    kit_components = product.get("kitComponents")
    if kit_components:
        if isinstance(kit_components, dict):
            components = kit_components.get("components") or kit_components.get("items") or []
            if components:
                return f"Sim ({len(components)} itens)"
        if isinstance(kit_components, list) and kit_components:
            return f"Sim ({len(kit_components)} itens)"
        return "Sim"

    kit_char = _char_value(chars, "kit", "é kit", "e kit", "kit de fábrica")
    if kit_char:
        return kit_char
    return ""


def extract_anymarket_fields(product: dict, sku_hint: str = "") -> dict[str, str]:
    """Extrai campos completos do produto AnyMarket para comparação."""
    empty = {
        "any_id": "",
        "any_sku_id": "",
        "any_sku": "",
        "sku": "",
        "title": "",
        "description": "",
        "brand": "",
        "model": "",
        "color": "",
        "size": "",
        "gender": "",
        "voltage": "",
        "kit": "",
        "ean": "",
        "price": "",
        "stock": "",
        "category": "",
        "is_active": "",
        "has_variations": "",
        "external_id": "",
        "height": "",
        "width": "",
        "length": "",
        "weight": "",
        "image_main": "",
        "image_count": "",
        "images": "",
        "images_list": [],
    }
    if not product:
        return empty

    chars = _chars_by_name(product)
    skus = [s for s in (product.get("skus") or []) if isinstance(s, dict)]

    selected_sku = None
    if sku_hint:
        for sku in skus:
            if str(sku.get("partnerId") or "").strip() == sku_hint.strip():
                selected_sku = sku
                break
    if not selected_sku and skus:
        selected_sku = skus[0]

    partner_ids = [str(s.get("partnerId") or "").strip() for s in skus if s.get("partnerId")]
    partner_ids = [p for p in partner_ids if p]

    color = " | ".join(_sku_variation_values(selected_sku, "cor", "color"))
    size = " | ".join(_sku_variation_values(selected_sku, "tamanho", "size"))
    voltage = " | ".join(_sku_variation_values(selected_sku, "voltagem", "voltage"))

    gender_raw = str(product.get("gender") or "").strip()
    gender = GENDER_LABELS.get(gender_raw.upper(), gender_raw)
    if not gender:
        gender = _char_value(chars, "gênero", "genero", "gender")
    images = _image_urls(product)

    brand_obj = product.get("brand") or {}
    brand = brand_obj.get("name", "") if isinstance(brand_obj, dict) else str(brand_obj or "")

    category_obj = product.get("category") or {}
    category = ""
    if isinstance(category_obj, dict):
        category = str(category_obj.get("path") or category_obj.get("name") or "")

    price = ""
    stock = ""
    ean = ""
    any_sku_id = ""
    sku_title = ""
    if selected_sku:
        any_sku_id = str(selected_sku.get("id") or "")
        sell = selected_sku.get("sellPrice")
        if sell is not None:
            price = str(sell)
        amount = selected_sku.get("amount")
        if amount is not None:
            stock = str(amount)
        ean = str(selected_sku.get("ean") or "")
        sku_title = str(
            selected_sku.get("title")
            or selected_sku.get("name")
            or selected_sku.get("skuTitle")
            or ""
        ).strip()

    description = str(product.get("description") or "").strip()
    if len(description) > 500:
        description = description[:497] + "..."

    return {
        "any_id": str(product.get("id") or ""),
        "any_sku_id": any_sku_id,
        "any_sku": " | ".join(partner_ids),
        "sku": " | ".join(partner_ids),
        "title": sku_title or str(product.get("title") or "").strip(),
        "description": description,
        "brand": str(brand).strip(),
        "model": str(product.get("model") or "").strip(),
        "color": color,
        "size": size,
        "gender": gender,
        "voltage": voltage,
        "kit": _resolve_kit(product, chars),
        "ean": ean,
        "price": price,
        "stock": stock,
        "category": category,
        "is_active": "SIM" if product.get("isProductActive") else "NAO",
        "has_variations": "SIM" if product.get("hasVariations") else "NAO",
        "external_id": str(product.get("externalIdProduct") or "").strip(),
        "height": str(product.get("height") or ""),
        "width": str(product.get("width") or ""),
        "length": str(product.get("length") or ""),
        "weight": str(product.get("weight") or ""),
        "image_main": images[0] if images else "",
        "image_count": str(len(images)),
        "images": " | ".join(images),
        "images_list": images,
    }


def normalize_for_match(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = text.replace("｜", "|")
    return text


def match_values(ml_value: str, any_value: str) -> str:
    ml_norm = normalize_for_match(ml_value)
    any_norm = normalize_for_match(any_value)
    if not ml_norm and not any_norm:
        return "AMBOS_VAZIOS"
    if not ml_norm:
        return "AUSENTE_ML"
    if not any_norm:
        return "AUSENTE_ANY"
    if ml_norm == any_norm:
        return "OK"
    # tamanhos agregados: considera OK se conjuntos forem iguais
    ml_parts = {p.strip() for p in ml_norm.split("|") if p.strip()}
    any_parts = {p.strip() for p in any_norm.split("|") if p.strip()}
    if ml_parts and ml_parts == any_parts:
        return "OK"
    return "DIVERGENTE"
