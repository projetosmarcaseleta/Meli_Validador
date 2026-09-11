"""
anymarket_api.py – Cliente da API Backoffice v2 do AnyMarket.

Auth: headers gumgaToken + platform em todas as chamadas.
"""

from __future__ import annotations

import re
import threading
import unicodedata
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


def _sku_lookup_candidates(sku: str) -> list[str]:
    raw = str(sku or "").strip()
    if not raw:
        return []
    out: list[str] = []
    for value in (raw, raw.lstrip("0") or "0", raw.zfill(9)):
        if value not in out:
            out.append(value)
    return out


def _partner_ids_from_item(item: dict) -> set[str]:
    ids: set[str] = set()
    if not isinstance(item, dict):
        return ids
    for key in ("partnerId", "externalIdProduct", "sku"):
        val = str(item.get(key) or "").strip()
        if val:
            ids.add(val)
    for sku in item.get("skus") or []:
        if not isinstance(sku, dict):
            continue
        for key in ("partnerId", "sku"):
            val = str(sku.get(key) or "").strip()
            if val:
                ids.add(val)
    return ids


def _item_matches_sku(item: dict, candidate_set: set[str]) -> bool:
    found = _partner_ids_from_item(item)
    if candidate_set & found:
        return True
    expanded: set[str] = set()
    for pid in found:
        expanded.update(_sku_lookup_candidates(pid))
    return bool(candidate_set & expanded)


def find_product_by_partner_id(
    partner_id: str,
    gumga_token: str,
    platform: str | None = None,
) -> dict:
    """
    Localiza o produto AnyMarket pelo partnerId/SKU do cliente.
    Usa GET /products?sku= (filtro oficial) e GET /skus/marketplaces?partnerID=,
    depois GET /products/{id}.
    """
    candidates = _sku_lookup_candidates(partner_id)
    if not candidates:
        return {}

    base = ANYMARKET_API_BASE_URL.rstrip("/")
    headers = _headers(gumga_token, platform)
    candidate_set = set(candidates)

    def _auth_error(resp) -> None:
        if resp.status_code != 401:
            return
        body = _content(resp)
        msg = body.get("message") if isinstance(body, dict) else ""
        raise PermissionError(msg or "Token AnyMarket inválido (401).")

    def _full_product(product_id, fallback: dict | None = None) -> dict:
        if product_id is None:
            return fallback or {}
        full = get_product(product_id, gumga_token, platform)
        return full or fallback or {}

    for sku in candidates:
        try:
            resp = _session().get(
                f"{base}/products",
                headers=headers,
                params={"sku": sku, "limit": 10},
                proxies=_PROXIES,
                timeout=HTTP_TIMEOUT,
            )
            _auth_error(resp)
            if resp.status_code >= 400:
                continue
            hits = [item for item in _extract_content_list(resp.json()) if isinstance(item, dict)]
            unique_full: dict | None = None
            for item in hits:
                full = _full_product(item.get("id"), item)
                if _item_matches_sku(full, candidate_set) or _item_matches_sku(item, candidate_set):
                    return full
                if unique_full is None:
                    unique_full = full
                else:
                    unique_full = None
                    break
            # O filtro sku= da API já restringe aos produtos daquele SKU.
            if unique_full and unique_full.get("id"):
                return unique_full
        except PermissionError:
            raise
        except Exception as exc:
            print(f"[ANYMARKET ERRO] busca products sku={sku} -> {type(exc).__name__}: {exc}")

        try:
            resp = _session().get(
                f"{base}/skus/marketplaces",
                headers=headers,
                params={"partnerID": sku},
                proxies=_PROXIES,
                timeout=HTTP_TIMEOUT,
            )
            _auth_error(resp)
            if resp.status_code >= 400:
                continue
            listings = resp.json()
            if isinstance(listings, dict):
                listings = _extract_content_list(listings)
            if not isinstance(listings, list) or not listings:
                continue
            # SKU existe no hub; tenta o produto completo de novo pelo filtro oficial.
            resp = _session().get(
                f"{base}/products",
                headers=headers,
                params={"sku": sku, "limit": 10},
                proxies=_PROXIES,
                timeout=HTTP_TIMEOUT,
            )
            _auth_error(resp)
            if resp.status_code >= 400:
                continue
            hits = [item for item in _extract_content_list(resp.json()) if isinstance(item, dict)]
            if len(hits) == 1:
                return _full_product(hits[0].get("id"), hits[0])
            for item in hits:
                full = _full_product(item.get("id"), item)
                if _item_matches_sku(full, candidate_set) or _item_matches_sku(item, candidate_set):
                    return full
        except PermissionError:
            raise
        except Exception as exc:
            print(f"[ANYMARKET ERRO] busca skus/marketplaces partnerID={sku} -> {type(exc).__name__}: {exc}")

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


def _sku_visual_matchers(sku: dict | None) -> tuple[set[str], set[str]]:
    """Ids e rótulos da variação visual do SKU (cor), para filtrar fotos."""
    ids: set[str] = set()
    labels: set[str] = set()
    if not sku or not isinstance(sku, dict):
        return ids, labels
    variations = sku.get("variations")
    if not isinstance(variations, list):
        return ids, labels
    for var in variations:
        if not isinstance(var, dict):
            continue
        type_obj = var.get("type") or {}
        type_name = ""
        visual = False
        if isinstance(type_obj, dict):
            type_name = str(type_obj.get("name") or "").strip().lower()
            visual = bool(type_obj.get("visualVariation"))
        elif isinstance(type_obj, str):
            type_name = type_obj.strip().lower()
        is_visual = visual or type_name in {"color", "cor", "colour"}
        if not is_visual:
            continue
        vid = var.get("id")
        if vid is not None and str(vid).strip():
            ids.add(str(vid).strip())
        desc = str(var.get("description") or var.get("value") or "").strip()
        if desc:
            labels.add(desc.lower())
    return ids, labels


def _image_url(image: dict) -> str:
    url = (
        image.get("originalImage")
        or image.get("standardUrl")
        or image.get("url")
        or image.get("thumbnailUrl")
        or ""
    )
    url = str(url).strip()
    if url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    return url


def _image_urls(product: dict, sku: dict | None = None) -> list[str]:
    images = [img for img in (product.get("images") or []) if isinstance(img, dict)]
    var_ids, labels = _sku_visual_matchers(sku)
    if var_ids or labels:
        matched = []
        for image in images:
            img_var_id = image.get("idVariation")
            img_label = str(image.get("variation") or "").strip().lower()
            id_ok = img_var_id is not None and str(img_var_id) in var_ids
            label_ok = bool(img_label and img_label in labels)
            if id_ok or label_ok:
                matched.append(image)
        if matched:
            images = matched

    images.sort(key=lambda img: (not bool((img or {}).get("main")), (img or {}).get("index") or 0))
    urls: list[str] = []
    seen: set[str] = set()
    for image in images:
        url = _image_url(image)
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


_HTML_RE = re.compile(r"<[^>]+>")
_NOISE_CHAR_NAMES = {
    "destaques",
    "apresentação do produto",
    "apresentacao do produto",
    "aviso importante para lavadora de roupas",
    "conteúdo da embalagem",
    "conteudo da embalagem",
}

# characteristics AnyMarket → chave comparável com o ML
ANY_CHAR_FIELD_MAP: list[tuple[str, tuple[str, ...]]] = [
    ("model", ("modelo", "referência", "referencia")),
    ("capacity", ("capacidade de lavagem", "capacidade")),
    ("power", ("potência", "potencia")),
    ("material", ("material do cesto", "material")),
    ("warranty", ("prazo de garantia", "garantia")),
    ("gender", ("gênero", "genero", "gender")),
]


def normalize_attr_key(name: str) -> str:
    text = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", " ", text).strip().lower()
    return re.sub(r"\s+", " ", text)


def _plain_text(value: str) -> str:
    text = _HTML_RE.sub(" ", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def _truncate(text: str, limit: int = 2000) -> str:
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _is_noise_characteristic(name: str, value: str) -> bool:
    name_l = (name or "").strip().lower()
    if name_l in _NOISE_CHAR_NAMES:
        return True
    if "<" in (value or "") or "iframe" in (value or "").lower():
        return True
    if len(value or "") > 400:
        return True
    return False


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


def extract_anymarket_fields(product: dict, sku_hint: str = "", sku_id_hint: str = "") -> dict[str, str]:
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
        "capacity": "",
        "power": "",
        "material": "",
        "warranty": "",
        "extra_attrs": {},
    }
    if not product:
        return empty

    chars = _chars_by_name(product)
    skus = [s for s in (product.get("skus") or []) if isinstance(s, dict)]

    selected_sku = None
    sku_id_hint = str(sku_id_hint or "").strip()
    if sku_id_hint:
        for sku in skus:
            if str(sku.get("id") or "").strip() == sku_id_hint:
                selected_sku = sku
                break
    sku_hints = set(_sku_lookup_candidates(sku_hint)) if sku_hint else set()
    if not selected_sku and sku_hints:
        for sku in skus:
            if str(sku.get("partnerId") or "").strip() in sku_hints:
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

    mapped_char_names: set[str] = {
        "cor", "color", "cores", "cor principal",
        "tamanho", "size", "tamanho do produto",
        "voltagem", "voltage", "voltagem do produto",
        "marca", "brand",
        "gênero", "genero", "gender",
        "kit", "é kit", "e kit", "kit de fábrica",
    }
    extra_fields: dict[str, str] = {}
    for field_key, names in ANY_CHAR_FIELD_MAP:
        value = _char_value(chars, *names)
        extra_fields[field_key] = value
        mapped_char_names.update(n.lower() for n in names)

    extra_attrs: dict[str, dict] = {}
    for char in product.get("characteristics") or []:
        if not isinstance(char, dict):
            continue
        name = str(char.get("name") or "").strip()
        raw_value = str(char.get("value") or "")
        value = _plain_text(raw_value)
        if not name or not value or _is_noise_characteristic(name, raw_value):
            continue
        name_l = name.lower()
        if name_l in mapped_char_names or any(len(n) >= 4 and n in name_l for n in mapped_char_names):
            continue
        key = normalize_attr_key(name)
        if not key or key in extra_attrs:
            continue
        extra_attrs[key] = {"label": name, "value": value}

    images = _image_urls(product, selected_sku)

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

    description = _truncate(_plain_text(str(product.get("description") or "")), 2000)
    model = str(product.get("model") or "").strip() or extra_fields.get("model") or ""
    if extra_fields.get("gender") and not gender:
        gender = extra_fields["gender"]

    return {
        "any_id": str(product.get("id") or ""),
        "any_sku_id": any_sku_id,
        "any_sku": " | ".join(partner_ids),
        "sku": " | ".join(partner_ids),
        "title": sku_title or str(product.get("title") or "").strip(),
        "description": description,
        "brand": str(brand).strip(),
        "model": model,
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
        "capacity": extra_fields.get("capacity") or "",
        "power": extra_fields.get("power") or "",
        "material": extra_fields.get("material") or "",
        "warranty": extra_fields.get("warranty") or "",
        "image_main": images[0] if images else "",
        "image_count": str(len(images)),
        "images": " | ".join(images),
        "images_list": images,
        "extra_attrs": extra_attrs,
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
