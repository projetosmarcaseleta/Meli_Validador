"""
exporter.py – Extrai campos do Mercado Livre e AnyMarket lado a lado com divergências.
"""

from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from anymarket_api import (
    extract_anymarket_fields,
    find_product_by_ean,
    find_product_by_partner_id,
    load_product_for_sku_audit,
    get_product,
    get_product_sku,
    merge_sku_into_product,
    normalize_attr_key,
    resolve_product_by_marketplace_id,
)
from api import BATCH_SIZE, LISTING_LABELS, LOGISTIC_LABELS, get_item_description, get_products_batch, search_items_by_seller_sku, validate_token
from compare import (
    build_compare_headers,
    build_compare_row,
    build_ml_only_row,
    build_audit_item,
    build_catalog_audit_item,
    match_values,
)
from config import (
    MAX_WORKERS,
    ANYMARKET_SKU_WEBHOOK_URL,
    ANYMARKET_DB_HOST,
    ANYMARKET_DB_PORT,
    ANYMARKET_DB_NAME,
    ANYMARKET_DB_USER,
    ANYMARKET_DB_PASSWORD,
    ANYMARKET_DB_SSLMODE,
    GUMGA_TOKEN,
    ANYMARKET_PLATFORM,
    get_gumga_token,
)
from import_parser import ImportRow

HEADERS = [
    "SKU", "MLB", "TITULO", "COR", "TAMANHO", "GÊNERO", "VOLTAGEM", "KIT",
    "TIPO ANÚNCIO", "TIPO ENVIO", "CATÁLOGO", "QTD VENDIDA",
    "IMAGEM PRINCIPAL", "IMAGENS",
]

_MLB_PATTERN = re.compile(r"^MLB\d+$", re.IGNORECASE)
_last_db_error: str | None = None
_last_webhook_meta: dict = {
    "called": False,
    "ok": False,
    "url": "",
    "status": None,
    "error": "",
}


def _is_mlb(value: str) -> bool:
    return bool(_MLB_PATTERN.match(str(value or "").strip()))


def _get_last_db_error() -> str | None:
    return _last_db_error


def _get_last_webhook_meta() -> dict:
    return dict(_last_webhook_meta)


def _reset_webhook_meta() -> None:
    global _last_webhook_meta
    _last_webhook_meta = {
        "called": False,
        "ok": False,
        "url": "",
        "status": None,
        "error": "",
    }


def _effective_sku_webhook_url(webhook_url: str | None = None) -> str:
    if webhook_url is not None:
        return str(webhook_url).strip().strip("'\"")
    return (ANYMARKET_SKU_WEBHOOK_URL or "").strip().strip("'\"")


def _merge_sku_maps(target: dict[str, dict], source: dict[str, dict]) -> None:
    for sku, data in source.items():
        if sku not in target:
            target[sku] = {"cat": [], "trad": []}
        for side in ("cat", "trad"):
            seen = {m for m, _ in target[sku][side]}
            for mlb, status in data.get(side, []):
                if mlb not in seen:
                    target[sku][side].append((mlb, status))
                    seen.add(mlb)
        pid = str(data.get("any_product_id") or "").strip()
        if pid and not str(target[sku].get("any_product_id") or "").strip():
            target[sku]["any_product_id"] = pid
        sid = str(data.get("any_sku_id") or "").strip()
        if sid and not str(target[sku].get("any_sku_id") or "").strip():
            target[sku]["any_sku_id"] = sid


def _append_mlb_slot(
    sku_map: dict[str, dict],
    sku: str,
    mlb: str,
    is_catalog: bool,
    status: str = "",
    marketplace_listing_id: str = "",
) -> None:
    if sku not in sku_map:
        sku_map[sku] = {"cat": [], "trad": [], "marketplace_listing_by_mlb": {}}
    if "marketplace_listing_by_mlb" not in sku_map[sku]:
        sku_map[sku]["marketplace_listing_by_mlb"] = {}
    side = "cat" if is_catalog else "trad"
    existing = {m for m, _ in sku_map[sku][side]}
    if mlb not in existing:
        sku_map[sku][side].append((mlb, status or "active"))
    lid = str(marketplace_listing_id or "").strip()
    if mlb and lid:
        sku_map[sku]["marketplace_listing_by_mlb"][mlb] = lid


def _any_product_id_from_payload(val: dict) -> str:
    if not isinstance(val, dict):
        return ""
    for key in ("any_product_id", "product_id", "id_product", "idProduct", "productId"):
        pid = str(val.get(key) or "").strip()
        if pid:
            return pid
    return ""


def _any_sku_id_from_payload(val: dict) -> str:
    if not isinstance(val, dict):
        return ""
    for key in ("any_sku_id", "sku_id", "id_sku", "idSku"):
        sid = str(val.get(key) or "").strip()
        if sid:
            return sid
    return ""


def _mlb_slots_from_webhook(entries) -> list[tuple[str, str]]:
    slots: list[tuple[str, str]] = []
    if not isinstance(entries, list):
        return slots
    for item in entries:
        mlb = ""
        status = "active"
        if isinstance(item, dict):
            mlb = str(
                item.get("mlb")
                or item.get("id_in_marketplace")
                or item.get("idInMarketplace")
                or ""
            ).strip()
            status = str(item.get("status") or item.get("status_in_marketplace") or "active").strip() or "active"
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            mlb = str(item[0] or "").strip()
            status = str(item[1] or "active").strip() or "active"
        mlb = mlb.upper()
        if mlb.startswith("MLB"):
            slots.append((mlb, status))
    return slots


def _marketplace_pairs_for_sku(slots: dict, sku_id_hint: str) -> list[tuple[str, str]]:
    """Pares (sku_id, id anúncio AnyMarket) para GET /skus/{skuId}/marketplaces/{id}."""
    sid = str(sku_id_hint or slots.get("any_sku_id") or "").strip()
    by_mlb = slots.get("marketplace_listing_by_mlb") or {}
    if not isinstance(by_mlb, dict):
        return []
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for mlb, _ in (slots.get("cat") or []) + (slots.get("trad") or []):
        lid = str(by_mlb.get(mlb) or by_mlb.get(str(mlb).upper()) or "").strip()
        if not sid or not lid:
            continue
        key = (sid, lid)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _ids_from_webhook_entries(entries) -> tuple[str, str]:
    if not isinstance(entries, list):
        return "", ""
    product_id = ""
    sku_id = ""
    for item in entries:
        if not isinstance(item, dict):
            continue
        if not product_id:
            product_id = _any_product_id_from_payload(item)
        if not sku_id:
            sku_id = _any_sku_id_from_payload(item)
        if product_id and sku_id:
            break
    return product_id, sku_id


def _apply_webhook_listing_ids(sku_map: dict[str, dict], sku: str, val: dict) -> None:
    if sku not in sku_map:
        sku_map[sku] = {"cat": [], "trad": [], "marketplace_listing_by_mlb": {}}
    by_mlb = sku_map[sku].setdefault("marketplace_listing_by_mlb", {})

    def _ingest(entries) -> None:
        if not isinstance(entries, list):
            return
        for item in entries:
            if not isinstance(item, dict):
                continue
            mlb = str(
                item.get("mlb")
                or item.get("id_in_marketplace")
                or item.get("idInMarketplace")
                or ""
            ).strip().upper()
            lid = str(
                item.get("marketplace_id")
                or item.get("marketplace_listing_id")
                or item.get("listing_id")
                or ""
            ).strip()
            if mlb.startswith("MLB") and lid and lid.isdigit():
                by_mlb[mlb] = lid

    _ingest(val.get("cat"))
    _ingest(val.get("trad"))


def _apply_webhook_product_ids(sku_map: dict[str, dict], sku: str, val: dict) -> None:
    _apply_webhook_listing_ids(sku_map, sku, val)
    product_id = _any_product_id_from_payload(val)
    sku_id = _any_sku_id_from_payload(val)
    if not product_id or not sku_id:
        nested_pid, nested_sid = _ids_from_webhook_entries(val.get("cat"))
        if not product_id:
            product_id = nested_pid
        if not sku_id:
            sku_id = nested_sid
    if not product_id or not sku_id:
        nested_pid, nested_sid = _ids_from_webhook_entries(val.get("trad"))
        if not product_id:
            product_id = nested_pid
        if not sku_id:
            sku_id = nested_sid
    _set_any_product_id(sku_map, sku, product_id)
    if not sku_id:
        return
    if sku not in sku_map:
        sku_map[sku] = {"cat": [], "trad": []}
    if not str(sku_map[sku].get("any_sku_id") or "").strip():
        sku_map[sku]["any_sku_id"] = sku_id


def _set_any_product_id(sku_map: dict[str, dict], sku: str, product_id: str) -> None:
    pid = str(product_id or "").strip()
    if not pid:
        return
    if sku not in sku_map:
        sku_map[sku] = {"cat": [], "trad": []}
    if not str(sku_map[sku].get("any_product_id") or "").strip():
        sku_map[sku]["any_product_id"] = pid


def _db_table_columns(cur, table_name: str) -> set[str]:
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'anymarket_prd' AND table_name = %s
        """,
        (table_name,),
    )
    return {str(row[0]).lower() for row in cur.fetchall()}


def _attach_anymarket_product_ids_from_db(cur, sku_map: dict[str, dict], skus: list[str]) -> None:
    """Preenche any_product_id via réplica (sku_in_marketplace / partner_id → product_id)."""
    pending = [s for s in skus if s and not str((sku_map.get(s) or {}).get("any_product_id") or "").strip()]
    if not pending:
        return

    from psycopg2 import sql as psql

    sm_cols = _db_table_columns(cur, "sku_marketplace")
    sku_cols = _db_table_columns(cur, "sku")
    queries: list[tuple[str, list[str]]] = []

    if "sku_in_marketplace" in sm_cols and "product_id" in sm_cols:
        queries.append(
            (
                """
                SELECT sm.sku_in_marketplace, sm.product_id
                FROM anymarket_prd.sku_marketplace AS sm
                WHERE sm.sku_in_marketplace IN ({skus})
                  AND sm.product_id IS NOT NULL
                """,
                pending,
            )
        )
    if "sku_in_marketplace" in sm_cols and "sku_id" in sm_cols and "id" in sku_cols and "product_id" in sku_cols:
        queries.append(
            (
                """
                SELECT sm.sku_in_marketplace, s.product_id, s.id
                FROM anymarket_prd.sku_marketplace AS sm
                JOIN anymarket_prd.sku AS s ON s.id = sm.sku_id
                WHERE sm.sku_in_marketplace IN ({skus})
                  AND s.product_id IS NOT NULL
                """,
                pending,
            )
        )
    partner_col = "partner_id" if "partner_id" in sku_cols else ("partnerid" if "partnerid" in sku_cols else "")
    if partner_col and "product_id" in sku_cols:
        queries.append(
            (
                f"""
                SELECT s.{partner_col}, s.product_id, s.id
                FROM anymarket_prd.sku AS s
                WHERE s.{partner_col} IN ({{skus}})
                  AND s.product_id IS NOT NULL
                """,
                pending,
            )
        )

    for sql_text, batch_skus in queries:
        still = [s for s in batch_skus if not str((sku_map.get(s) or {}).get("any_product_id") or "").strip()]
        if not still:
            break
        try:
            placeholders = psql.SQL(", ").join(psql.Placeholder() for _ in still)
            query = psql.SQL(sql_text).format(skus=placeholders)
            cur.execute(query, still)
            for row in cur.fetchall():
                sku_key = str(row[0] or "").strip()
                product_id = str(row[1] or "").strip()
                sku_id = str(row[2] or "").strip() if len(row) > 2 else ""
                if sku_key and product_id:
                    _set_any_product_id(sku_map, sku_key, product_id)
                if sku_key and sku_id:
                    if sku_key not in sku_map:
                        sku_map[sku_key] = {"cat": [], "trad": []}
                    if not str(sku_map[sku_key].get("any_sku_id") or "").strip():
                        sku_map[sku_key]["any_sku_id"] = sku_id
        except Exception as exc:
            print(f"[DB ANYMARKET] lookup product_id ignorado ({type(exc).__name__})", flush=True)
            try:
                cur.connection.rollback()
            except Exception:
                pass




def _enrich_sku_from_ml_search(sku: str, user_id, token: str, sku_map: dict[str, dict]) -> None:
    mlbs = search_items_by_seller_sku(user_id, sku, token)
    if not mlbs:
        return
    products = get_products_batch(mlbs, token)
    for mlb, prod in products.items():
        if not prod:
            continue
        is_catalog = bool(prod.get("catalog_listing"))
        status = str(prod.get("status") or "active")
        _append_mlb_slot(sku_map, sku, mlb, is_catalog, status)


def _attrs_map(produto: dict) -> dict:
    return {a["id"]: a for a in (produto.get("attributes") or []) if a.get("id")}


def _attr_value(attrs: dict, *attr_ids: str) -> str:
    for attr_id in attr_ids:
        value = (attrs.get(attr_id) or {}).get("value_name") or ""
        if value:
            return str(value).strip()
    return ""


def _resolve_sku(produto: dict, attrs: dict | None = None) -> str:
    sku = produto.get("seller_custom_field") or ""
    if not sku:
        attrs = attrs if attrs is not None else _attrs_map(produto)
        sku = _attr_value(attrs, "SELLER_SKU")
    return sku


def _resolve_color(attrs: dict) -> str:
    return _attr_value(attrs, "COLOR", "MAIN_COLOR", "COLOUR")


def _resolve_size(produto: dict, attrs: dict) -> str:
    size = _attr_value(attrs, "SIZE", "FILTRABLE_SIZE")
    if size:
        return size
    sizes = []
    seen = set()
    for variation in produto.get("variations") or []:
        for combo in variation.get("attribute_combinations") or []:
            if combo.get("id") != "SIZE":
                continue
            value = (combo.get("value_name") or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            sizes.append(value)
    return " | ".join(sizes)


def _resolve_gender(attrs: dict) -> str:
    return _attr_value(attrs, "GENDER")


def _resolve_voltage(attrs: dict) -> str:
    return _attr_value(attrs, "VOLTAGE")


def _resolve_kit(attrs: dict) -> str:
    is_kit = _attr_value(attrs, "IS_FACTORY_KIT", "KIT")
    pieces = _attr_value(attrs, "PIECES_NUMBER", "UNITS_PER_PACKAGE", "UNIT_PACK")
    is_kit_yes = is_kit.lower() in {"sim", "yes", "true", "1"}
    if is_kit_yes and pieces:
        return f"Sim ({pieces} peças)" if pieces.isdigit() else f"Sim ({pieces})"
    if is_kit_yes:
        return "Sim"
    if pieces:
        return f"{pieces} peças" if pieces.isdigit() else pieces
    if is_kit:
        return is_kit
    return ""


def _resolve_tipo_envio(produto: dict) -> str:
    shipping = produto.get("shipping") or {}
    logistic_type = shipping.get("logistic_type") or ""
    if logistic_type and logistic_type != "not_specified":
        return LOGISTIC_LABELS.get(logistic_type, logistic_type.replace("_", " ").title())
    mode = shipping.get("mode") or ""
    if mode and mode != "not_specified":
        return LOGISTIC_LABELS.get(mode, mode.upper())
    return "Não especificado"


def _resolve_image_urls(produto: dict) -> list[str]:
    urls = []
    seen = set()
    for picture in produto.get("pictures") or []:
        url = (picture.get("secure_url") or picture.get("url") or "").strip()
        if not url:
            continue
        if url.startswith("http://"):
            url = "https://" + url[len("http://") :]
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


_ML_ATTR_FIELD_IDS: dict[str, str] = {
    "BRAND": "brand",
    "MARCA": "brand",
    "MODEL": "model",
    "MODELO": "model",
    "COLOR": "color",
    "MAIN_COLOR": "color",
    "COLOUR": "color",
    "SIZE": "size",
    "FILTRABLE_SIZE": "size",
    "VOLTAGE": "voltage",
    "GTIN": "ean",
    "EAN": "ean",
    "GENDER": "gender",
    "MATERIAL": "material",
    "POWER": "power",
    "WASHING_CAPACITY_KG": "capacity",
    "CAPACITY": "capacity",
    "WASHING_MACHINE_CAPACITY": "capacity",
    "LINE": "line",
    "WARRANTY": "warranty",
    "WARRANTY_TIME": "warranty",
    "PACKAGE_HEIGHT": "height",
    "HEIGHT": "height",
    "PACKAGE_WIDTH": "width",
    "WIDTH": "width",
    "PACKAGE_LENGTH": "length",
    "LENGTH": "length",
    "PACKAGE_WEIGHT": "weight",
    "WEIGHT": "weight",
}

_ML_ATTR_SKIP_IDS = {
    "SELLER_SKU",
    "ITEM_CONDITION",
    "EMPTY_GTIN_REASON",
    "GTIN",
    "EAN",
    "BRAND",
    "MARCA",
    "MODEL",
    "MODELO",
    "COLOR",
    "MAIN_COLOR",
    "COLOUR",
    "SIZE",
    "FILTRABLE_SIZE",
    "VOLTAGE",
    "GENDER",
    "IS_FACTORY_KIT",
    "KIT",
    "PIECES_NUMBER",
    "UNITS_PER_PACKAGE",
    "UNIT_PACK",
}


def _truncate_text(text: str, limit: int = 2000) -> str:
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _ml_mapped_attr(attrs: dict, field: str) -> str:
    for attr_id, mapped in _ML_ATTR_FIELD_IDS.items():
        if mapped != field:
            continue
        value = _attr_value(attrs, attr_id)
        if value:
            return value
    return ""


def _ml_extra_attrs(produto: dict) -> dict[str, dict]:
    extra: dict[str, dict] = {}
    for attr in produto.get("attributes") or []:
        if not isinstance(attr, dict):
            continue
        attr_id = str(attr.get("id") or "").strip().upper()
        if attr_id in _ML_ATTR_SKIP_IDS or attr_id in _ML_ATTR_FIELD_IDS:
            continue
        name = str(attr.get("name") or attr_id).strip()
        value = str(attr.get("value_name") or "").strip()
        if not name or not value:
            continue
        key = normalize_attr_key(name)
        if not key or key in extra:
            continue
        extra[key] = {"label": name, "value": value}
    return extra


def _extract_ml_description(produto: dict) -> str:
    description = str(produto.get("descriptions") or produto.get("description") or "")
    if isinstance(produto.get("descriptions"), list):
        parts = []
        for block in produto.get("descriptions") or []:
            if isinstance(block, dict):
                parts.append(str(block.get("plain_text") or block.get("text") or ""))
        description = " ".join(parts)
    return _truncate_text(str(description).strip(), 2000)


def _attach_ml_descriptions(ml_fields_by_mlb: dict[str, dict], token: str, progress_callback=None) -> None:
    mlbs = [mlb for mlb in ml_fields_by_mlb.keys() if mlb]
    if not mlbs or not token:
        return
    total = len(mlbs)
    completed = 0
    lock = threading.Lock()

    def _one(mlb: str) -> tuple[str, str]:
        try:
            return mlb, get_item_description(mlb, token)
        except Exception:
            return mlb, ""

    with ThreadPoolExecutor(max_workers=min(len(mlbs), MAX_WORKERS)) as pool:
        futures = [pool.submit(_one, mlb) for mlb in mlbs]
        for fut in as_completed(futures):
            mlb, text = fut.result()
            with lock:
                completed += 1
                if text:
                    ml_fields_by_mlb[mlb]["description"] = _truncate_text(text, 2000)
                if progress_callback:
                    pct = int(78 + (completed / total) * 8)
                    progress_callback(min(pct, 86), 100, f"Descrições ML: {completed}/{total}...")


def _build_ml_fields(produto: dict) -> dict[str, str | int | list]:
    listing_id = produto.get("listing_type_id", "")
    attrs = _attrs_map(produto)
    image_urls = _resolve_image_urls(produto)
    description = _extract_ml_description(produto)

    price = produto.get("price")
    if price is None and produto.get("variations"):
        prices = [v.get("price") for v in produto.get("variations") or [] if v.get("price")]
        if prices:
            price = prices[0]

    return {
        "sku": _resolve_sku(produto, attrs),
        "mlb": produto.get("id", ""),
        "title": produto.get("title") or "",
        "description": description,
        "brand": _attr_value(attrs, "BRAND", "MARCA"),
        "model": _attr_value(attrs, "MODEL", "MODELO") or str(produto.get("model") or ""),
        "color": _resolve_color(attrs),
        "size": _resolve_size(produto, attrs),
        "gender": _resolve_gender(attrs),
        "voltage": _resolve_voltage(attrs),
        "kit": _resolve_kit(attrs),
        "ean": _attr_value(attrs, "GTIN", "EAN"),
        "price": str(price) if price is not None else "",
        "stock": str(produto.get("available_quantity", "")),
        "listing_type": LISTING_LABELS.get(listing_id, listing_id),
        "shipping_type": _resolve_tipo_envio(produto),
        "catalog": "SIM" if produto.get("catalog_listing") else "NÃO",
        "sold_quantity": produto.get("sold_quantity", 0),
        "condition": str(produto.get("condition") or ""),
        "status": str(produto.get("status") or ""),
        "category_id": str(produto.get("category_id") or ""),
        "category": str(produto.get("category_id") or ""),
        "catalog_product_id": str(produto.get("catalog_product_id") or ""),
        "permalink": str(produto.get("permalink") or ""),
        "capacity": _ml_mapped_attr(attrs, "capacity"),
        "power": _ml_mapped_attr(attrs, "power"),
        "material": _ml_mapped_attr(attrs, "material"),
        "warranty": _ml_mapped_attr(attrs, "warranty"),
        "height": _ml_mapped_attr(attrs, "height"),
        "width": _ml_mapped_attr(attrs, "width"),
        "length": _ml_mapped_attr(attrs, "length"),
        "weight": _ml_mapped_attr(attrs, "weight"),
        "image_main": image_urls[0] if image_urls else "",
        "image_count": str(len(image_urls)),
        "images": " | ".join(image_urls),
        "images_list": image_urls,
        "extra_attrs": _ml_extra_attrs(produto),
    }


def process_mlbs(
    mlb_list: list[str],
    token: str,
    progress_callback=None,
    gumga_token: str | None = None,
    any_platform: str | None = None,
    any_product_ids: list[str] | None = None,
    import_rows: list[ImportRow | dict] | None = None,
    reviews: dict[str, str] | None = None,
) -> tuple[list, list]:
    mlbs = [m.strip().upper() for m in mlb_list if m.strip()]
    total = len(mlbs)
    with_any = bool((gumga_token or "").strip())
    with_import = bool(import_rows)
    with_decision = bool(reviews)

    import_map: dict[str, dict] = {}
    for item in import_rows or []:
        data = item.as_dict() if isinstance(item, ImportRow) else dict(item)
        mlb_key = str(data.get("mlb") or "").strip().upper()
        if mlb_key:
            import_map[mlb_key] = data

    all_rows = [build_compare_headers(with_import, with_any, with_decision=with_decision)]
    errors: list[str] = []

    if not mlbs:
        return all_rows, errors

    produtos: dict = {}
    batches = [mlbs[i : i + BATCH_SIZE] for i in range(0, total, BATCH_SIZE)]
    lock = threading.Lock()
    completed = 0

    def _fetch(batch):
        nonlocal completed
        result = get_products_batch(batch, token)
        with lock:
            produtos.update(result)
            completed += len(batch)
            if progress_callback:
                progress_callback(completed, total, f"Buscando ML... {completed}/{total}")

    with ThreadPoolExecutor(max_workers=min(len(batches), MAX_WORKERS)) as pool:
        futures = [pool.submit(_fetch, b) for b in batches]
        for f in as_completed(futures):
            f.result()

    for mlb in mlbs:
        if mlb not in produtos:
            errors.append(f"[{mlb}] Não encontrado ou erro na API do Mercado Livre.")

    ml_fields_by_mlb: dict[str, dict] = {}
    for mlb in mlbs:
        produto = produtos.get(mlb)
        if produto:
            ml_fields_by_mlb[mlb] = _build_ml_fields(produto)
    _attach_ml_descriptions(ml_fields_by_mlb, token, progress_callback)

    any_by_mlb: dict[str, dict] = {}
    if with_any:
        gumga = gumga_token.strip()
        product_cache: dict[str, dict] = {}
        cache_lock = threading.Lock()

        def _fetch_product(product_id: str) -> dict:
            with cache_lock:
                cached = product_cache.get(f"id:{product_id}")
            if cached is not None:
                return cached
            product = get_product(product_id, gumga, any_platform)
            with cache_lock:
                product_cache[f"id:{product_id}"] = product
            return product

        def _lookup_for_mlb(mlb: str, fields: dict) -> tuple[str, dict, list[str]]:
            local_errors: list[str] = []
            import_row = import_map.get(mlb, {})
            sku_hint = str(fields.get("sku") or import_row.get("id_sku") or "").strip()
            product_id = str(import_row.get("id_product") or "").strip()
            product: dict = {}

            if product_id:
                try:
                    product = _fetch_product(product_id)
                except PermissionError as exc:
                    raise PermissionError(str(exc)) from exc
                if not product:
                    local_errors.append(
                        f"[{mlb}] ID_PRODUCT {product_id} não encontrado no AnyMarket."
                    )

            if not product:
                if sku_hint:
                    with cache_lock:
                        cached = product_cache.get(f"sku:{sku_hint}")
                    if cached is None:
                        product = find_product_by_partner_id(sku_hint, gumga, any_platform)
                        with cache_lock:
                            product_cache[f"sku:{sku_hint}"] = product
                    else:
                        product = cached
                if not product and not product_id:
                    local_errors.append(f"[{mlb}] Produto não encontrado no AnyMarket.")

            any_fields = extract_anymarket_fields(product, sku_hint=sku_hint)
            return mlb, any_fields, local_errors

        try:
            with ThreadPoolExecutor(max_workers=min(max(len(ml_fields_by_mlb), 1), MAX_WORKERS)) as pool:
                futures = [
                    pool.submit(_lookup_for_mlb, mlb, fields)
                    for mlb, fields in ml_fields_by_mlb.items()
                ]
                for f in as_completed(futures):
                    mlb, any_fields, local_errors = f.result()
                    any_by_mlb[mlb] = any_fields
                    errors.extend(local_errors)
        except PermissionError as exc:
            return all_rows, [f"[ANYMARKET] {exc}"]

    for mlb in mlbs:
        fields = ml_fields_by_mlb.get(mlb)
        if not fields:
            continue
        decision = (reviews.get(mlb) or "PENDENTE") if reviews else None
        if with_any:
            all_rows.append(
                build_compare_row(
                    fields,
                    any_by_mlb.get(mlb, extract_anymarket_fields({})),
                    import_map.get(mlb),
                    with_import=with_import,
                    decision=decision,
                )
            )
        else:
            all_rows.append(
                build_ml_only_row(
                    fields,
                    import_map.get(mlb),
                    with_import=with_import,
                    decision=decision,
                )
            )

    return all_rows, errors


def process_mlbs_for_audit(
    mlb_list: list[str],
    token: str,
    progress_callback=None,
    gumga_token: str | None = None,
    any_platform: str | None = None,
    any_product_ids: list[str] | None = None,
    import_rows: list[ImportRow | dict] | None = None,
) -> dict:
    mlbs = [m.strip().upper() for m in mlb_list if m.strip()]
    total = len(mlbs)
    with_any = bool((gumga_token or "").strip())
    with_import = bool(import_rows)

    import_map: dict[str, dict] = {}
    for item in import_rows or []:
        data = item.as_dict() if isinstance(item, ImportRow) else dict(item)
        mlb_key = str(data.get("mlb") or "").strip().upper()
        if mlb_key:
            import_map[mlb_key] = data

    items: list[dict] = []
    errors: list[str] = []

    if not mlbs:
        return {
            "items": [],
            "summary": {"total": 0, "divergent": 0, "ok": 0, "attention": 0, "errors": 0},
            "errors": errors,
        }

    produtos: dict = {}
    batches = [mlbs[i : i + BATCH_SIZE] for i in range(0, total, BATCH_SIZE)]
    lock = threading.Lock()
    completed = 0

    def _fetch(batch):
        nonlocal completed
        result = get_products_batch(batch, token)
        with lock:
            produtos.update(result)
            completed += len(batch)
            if progress_callback:
                progress_callback(completed, total, f"Buscando ML... {completed}/{total}")

    with ThreadPoolExecutor(max_workers=min(len(batches), MAX_WORKERS)) as pool:
        futures = [pool.submit(_fetch, b) for b in batches]
        for f in as_completed(futures):
            f.result()

    for mlb in mlbs:
        if mlb not in produtos:
            errors.append(f"[{mlb}] Não encontrado ou erro na API do Mercado Livre.")

    ml_fields_by_mlb: dict[str, dict] = {}
    for mlb in mlbs:
        produto = produtos.get(mlb)
        if produto:
            ml_fields_by_mlb[mlb] = _build_ml_fields(produto)
    _attach_ml_descriptions(ml_fields_by_mlb, token, progress_callback)

    any_by_mlb: dict[str, dict] = {}
    if with_any:
        gumga = gumga_token.strip()
        product_cache: dict[str, dict] = {}
        cache_lock = threading.Lock()

        def _fetch_product(product_id: str) -> dict:
            with cache_lock:
                cached = product_cache.get(f"id:{product_id}")
            if cached is not None:
                return cached
            product = get_product(product_id, gumga, any_platform)
            with cache_lock:
                product_cache[f"id:{product_id}"] = product
            return product

        def _lookup_for_mlb(mlb: str, fields: dict) -> tuple[str, dict, list[str]]:
            local_errors: list[str] = []
            import_row = import_map.get(mlb, {})
            sku_hint = str(fields.get("sku") or import_row.get("id_sku") or "").strip()
            product_id = str(import_row.get("id_product") or "").strip()
            product: dict = {}

            if product_id:
                try:
                    product = _fetch_product(product_id)
                except PermissionError as exc:
                    raise PermissionError(str(exc)) from exc
                if not product:
                    local_errors.append(
                        f"[{mlb}] ID_PRODUCT {product_id} não encontrado no AnyMarket."
                    )

            if not product:
                if sku_hint:
                    with cache_lock:
                        cached = product_cache.get(f"sku:{sku_hint}")
                    if cached is None:
                        product = find_product_by_partner_id(sku_hint, gumga, any_platform)
                        with cache_lock:
                            product_cache[f"sku:{sku_hint}"] = product
                    else:
                        product = cached
                if not product and not product_id:
                    local_errors.append(f"[{mlb}] Produto não encontrado no AnyMarket.")

            any_fields = extract_anymarket_fields(product, sku_hint=sku_hint)
            return mlb, any_fields, local_errors

        try:
            with ThreadPoolExecutor(max_workers=min(max(len(ml_fields_by_mlb), 1), MAX_WORKERS)) as pool:
                futures = [
                    pool.submit(_lookup_for_mlb, mlb, fields)
                    for mlb, fields in ml_fields_by_mlb.items()
                ]
                for f in as_completed(futures):
                    mlb, any_fields, local_errors = f.result()
                    any_by_mlb[mlb] = any_fields
                    errors.extend(local_errors)
        except PermissionError as exc:
            return {
                "items": [],
                "summary": {"total": len(mlbs), "divergent": 0, "ok": 0, "attention": 0, "errors": len(mlbs)},
                "errors": [f"[ANYMARKET] {exc}"],
            }

    count_ok = 0
    count_div = 0
    count_att = 0
    count_err = 0

    for mlb in mlbs:
        fields = ml_fields_by_mlb.get(mlb)
        if not fields:
            count_err += 1
            items.append({
                "mlb": mlb,
                "sku": "",
                "title": "Não encontrado ou erro no Mercado Livre",
                "status_geral": "ERRO",
                "summary": "Produto não retornado pela API do Mercado Livre",
                "divergences": ["Produto não encontrado no Mercado Livre"],
                "divergence_count": 1,
                "ml": {},
                "any": {},
                "comparison": [],
                "import_data": import_map.get(mlb, {}),
                "has_any": with_any,
                "has_import": with_import,
            })
            continue

        any_fields = any_by_mlb.get(mlb, extract_anymarket_fields({})) if with_any else {}
        audit_item = build_audit_item(
            fields,
            any_fields,
            import_map.get(mlb),
            with_import=with_import,
            with_any=with_any,
        )
        if audit_item["status_geral"] == "OK":
            count_ok += 1
        elif audit_item["status_geral"] == "DIVERGENTE":
            count_div += 1
        elif audit_item["status_geral"] == "ATENCAO":
            count_att += 1
        else:
            count_ok += 1

        items.append(audit_item)

    return {
        "items": items,
        "summary": {
            "total": len(mlbs),
            "divergent": count_div,
            "ok": count_ok,
            "attention": count_att,
            "errors": count_err,
        },
        "errors": errors,
    }


def _post_sku_webhook(
    hook: str,
    payload: dict,
    client_id: str | None = None,
) -> dict | None:
    global _last_webhook_meta
    import requests as req

    _last_webhook_meta = {
        "called": True,
        "ok": False,
        "url": hook,
        "status": None,
        "error": "",
    }
    sent_skus = payload.get("skus") or payload.get("mlbs") or []
    oi_hint = str(payload.get("oi") or "").strip()
    print(
        f"[N8N WEBHOOK] POST {hook} client={client_id or '-'} oi={oi_hint or '-'} skus={sent_skus}",
        flush=True,
    )
    resp = req.post(hook, json=payload, timeout=30)
    _last_webhook_meta["status"] = resp.status_code
    if resp.status_code != 200:
        _last_webhook_meta["error"] = f"HTTP {resp.status_code}: {resp.text[:200]}"
        print(f"[N8N WEBHOOK ERRO] {_last_webhook_meta['error']}", flush=True)
        return None
    raw = getattr(resp, "content", None)
    text = getattr(resp, "text", None)
    is_empty = (
        (isinstance(raw, (bytes, bytearray)) and not raw.strip())
        or (isinstance(text, str) and not text.strip())
    )
    if is_empty:
        _last_webhook_meta["error"] = "HTTP 200 com corpo vazio (workflow sem Respond to Webhook?)"
        print(f"[N8N WEBHOOK ERRO] {_last_webhook_meta['error']}", flush=True)
        return None
    try:
        data = resp.json() or {}
    except ValueError:
        _last_webhook_meta["error"] = f"Resposta nao-JSON: {resp.text[:200]}"
        print(f"[N8N WEBHOOK ERRO] {_last_webhook_meta['error']}", flush=True)
        return None
    _last_webhook_meta["ok"] = True
    return data


def _resolve_skus_from_anymarket_db(
    skus: list[str],
    webhook_url: str | None = None,
    client_id: str | None = None,
    platform: str | None = None,
    oi: str | None = None,
) -> dict[str, dict]:
    """
    Consulta o banco de leitura do AnyMarket para mapear cada SKU
    aos seus anúncios no Mercado Livre (Catálogo e Tradicional).
    Prioridade 1: Webhook do n8n (ANYMARKET_SKU_WEBHOOK_URL) - ideal para VPS sem acesso direto ao banco.
    Prioridade 2: Conexão direta PostgreSQL (ANYMARKET_DB_HOST) - para ambiente com VPN.
    Retorna { sku: { 'cat': [(mlb, status)], 'trad': [(mlb, status)] } }
    Filtra: market_place = 'MERCADO_LIVRE' AND sku_in_marketplace IN (...)
    """
    global _last_db_error
    _last_db_error = None
    _reset_webhook_meta()
    sku_map: dict[str, dict] = {s: {"cat": [], "trad": []} for s in skus}
    if not skus:
        return sku_map

    hook = _effective_sku_webhook_url(webhook_url)

    # 1. Tentar via Webhook n8n se configurado
    if hook:
        try:
            payload = {
                "skus": [str(s).strip() for s in skus if str(s).strip()],
                "sku": str(skus[0]).strip() if skus else "",
                "include": ["product_id", "sku_id"],
            }
            if client_id:
                payload["client_id"] = client_id
            if platform:
                payload["platform"] = platform
            if oi:
                payload["oi"] = oi
            data = _post_sku_webhook(hook, payload, client_id)
            if data is not None:
                incoming_map = data.get("sku_map") or {}
                for s, val in incoming_map.items():
                    s_clean = str(s).strip()
                    if s_clean in sku_map:
                        cat_list = _mlb_slots_from_webhook(val.get("cat", []))
                        trad_list = _mlb_slots_from_webhook(val.get("trad", []))
                        sku_map[s_clean]["cat"] = cat_list
                        sku_map[s_clean]["trad"] = trad_list
                        _apply_webhook_product_ids(sku_map, s_clean, val if isinstance(val, dict) else {})
                for s in skus:
                    pid = str((sku_map.get(s) or {}).get("any_product_id") or "").strip()
                    sid = str((sku_map.get(s) or {}).get("any_sku_id") or "").strip()
                    if pid:
                        print(
                            f"[N8N WEBHOOK] {s} id_product={pid} sku_id={sid or '-'}",
                            flush=True,
                        )
                webhook_hit = any(sku_map[s]["cat"] or sku_map[s]["trad"] for s in sku_map)
                missing_pid = [
                    s for s in sku_map
                    if (sku_map[s]["cat"] or sku_map[s]["trad"])
                    and not str(sku_map[s].get("any_product_id") or "").strip()
                ]
                if webhook_hit and missing_pid:
                    print(
                        f"[ANYMARKET] webhook sem product_id para {len(missing_pid)} SKU(s)",
                        flush=True,
                    )
                if webhook_hit and (not missing_pid or not ANYMARKET_DB_HOST or not ANYMARKET_DB_USER):
                    return sku_map
        except Exception as exc:
            _last_webhook_meta["error"] = str(exc)
            print(f"[N8N WEBHOOK ERRO] Falha na consulta via n8n: {exc}")

    # 2. Tentar via Conexão Direta ao PostgreSQL
    if not ANYMARKET_DB_HOST or not ANYMARKET_DB_USER:
        if skus and not ANYMARKET_DB_HOST and not hook:
            _last_db_error = "Réplica AnyMarket não configurada (ANYMARKET_DB_HOST/WEBHOOK ausente)."
        return sku_map

    try:
        import psycopg2
        from psycopg2 import sql as psql

        with psycopg2.connect(
            host=ANYMARKET_DB_HOST,
            port=ANYMARKET_DB_PORT,
            dbname=ANYMARKET_DB_NAME,
            user=ANYMARKET_DB_USER.strip().strip("'\""),
            password=ANYMARKET_DB_PASSWORD.strip().strip("'\""),
            sslmode=ANYMARKET_DB_SSLMODE,
            connect_timeout=15,
        ) as conn:
            with conn.cursor() as cur:
                for i in range(0, len(skus), 200):
                    batch = skus[i : i + 200]
                    placeholders = psql.SQL(", ").join(psql.Placeholder() for _ in batch)
                    query = psql.SQL("""
                        SELECT
                            sm.sku_in_marketplace AS sku,
                            sm.id_in_marketplace AS mlb,
                            sm.is_catalog,
                            sm.status_in_marketplace,
                            sm.id AS marketplace_listing_id
                        FROM anymarket_prd.sku_marketplace AS sm
                        WHERE sm.market_place = 'MERCADO_LIVRE'
                          AND sm.id_in_marketplace IS NOT NULL
                          AND sm.sku_in_marketplace IN ({skus})
                        ORDER BY sm.sku_in_marketplace, sm.is_catalog DESC
                    """).format(skus=placeholders)
                    cur.execute(query, batch)
                    for row in cur.fetchall():
                        s = str(row[0]).strip()
                        mlb = str(row[1]).strip().upper()
                        is_cat = int(row[2] or 0)
                        status = str(row[3] or "")
                        listing_id = str(row[4] or "").strip() if len(row) > 4 else ""
                        if s in sku_map and mlb.startswith("MLB"):
                            _append_mlb_slot(sku_map, s, mlb, is_cat == 1, status, listing_id)
                _attach_anymarket_product_ids_from_db(cur, sku_map, skus)
    except Exception as exc:
        _last_db_error = str(exc)
        print(f"[DB ANYMARKET ERRO] Falha ao consultar réplica AnyMarket: {exc}")

    return sku_map


def _resolve_mlbs_from_anymarket_db(
    mlbs: list[str],
    webhook_url: str | None = None,
    client_id: str | None = None,
    platform: str | None = None,
    oi: str | None = None,
) -> dict[str, dict]:
    """
    Resolve MLB(s) → SKU seller via réplica AnyMarket (id_in_marketplace) ou Webhook n8n.
    Retorna mapa keyed pelo sku_in_marketplace.
    """
    global _last_db_error
    sku_map: dict[str, dict] = {}
    if not mlbs:
        return sku_map

    hook = _effective_sku_webhook_url(webhook_url)

    # 1. Tentar via Webhook n8n se configurado
    if hook:
        try:
            payload = {"mlbs": mlbs}
            if client_id:
                payload["client_id"] = client_id
            if platform:
                payload["platform"] = platform
            if oi:
                payload["oi"] = oi
            data = _post_sku_webhook(hook, payload, client_id)
            if data is not None:
                incoming_map = data.get("sku_map") or {}
                _merge_sku_maps(sku_map, incoming_map)
                if sku_map:
                    return sku_map
        except Exception as exc:
            _last_webhook_meta["error"] = str(exc)
            print(f"[N8N WEBHOOK ERRO] Falha na consulta via n8n: {exc}")

    # 2. Tentar via Conexão Direta ao PostgreSQL
    if not ANYMARKET_DB_HOST or not ANYMARKET_DB_USER:
        return sku_map

    try:
        import psycopg2
        from psycopg2 import sql as psql

        with psycopg2.connect(
            host=ANYMARKET_DB_HOST,
            port=ANYMARKET_DB_PORT,
            dbname=ANYMARKET_DB_NAME,
            user=ANYMARKET_DB_USER.strip().strip("'\""),
            password=ANYMARKET_DB_PASSWORD.strip().strip("'\""),
            sslmode=ANYMARKET_DB_SSLMODE,
            connect_timeout=15,
        ) as conn:
            with conn.cursor() as cur:
                for i in range(0, len(mlbs), 200):
                    batch = [m.upper() for m in mlbs[i : i + 200]]
                    placeholders = psql.SQL(", ").join(psql.Placeholder() for _ in batch)
                    query = psql.SQL("""
                        SELECT
                            sm.sku_in_marketplace AS sku,
                            sm.id_in_marketplace AS mlb,
                            sm.is_catalog,
                            sm.status_in_marketplace,
                            sm.id AS marketplace_listing_id
                        FROM anymarket_prd.sku_marketplace AS sm
                        WHERE sm.market_place = 'MERCADO_LIVRE'
                          AND sm.id_in_marketplace IN ({mlbs})
                        ORDER BY sm.sku_in_marketplace, sm.is_catalog DESC
                    """).format(mlbs=placeholders)
                    cur.execute(query, batch)
                    for row in cur.fetchall():
                        s = str(row[0]).strip()
                        mlb = str(row[1]).strip().upper()
                        is_cat = int(row[2] or 0)
                        status = str(row[3] or "")
                        listing_id = str(row[4] or "").strip() if len(row) > 4 else ""
                        if mlb.startswith("MLB") and s:
                            _append_mlb_slot(sku_map, s, mlb, is_cat == 1, status, listing_id)
                _attach_anymarket_product_ids_from_db(cur, sku_map, list(sku_map.keys()))
    except Exception as exc:
        _last_db_error = str(exc)
        print(f"[DB ANYMARKET ERRO] Falha ao consultar MLB na réplica: {exc}")

    return sku_map


def _resolve_mlbs_via_ml_api(mlbs: list[str], token: str) -> dict[str, dict]:
    """Resolve MLB → seller SKU via API live do Mercado Livre."""
    sku_map: dict[str, dict] = {}
    if not mlbs or not token:
        return sku_map

    products = get_products_batch([m.upper() for m in mlbs], token)
    for mlb in mlbs:
        mlb_up = mlb.upper()
        prod = products.get(mlb_up)
        if not prod:
            continue
        fields = _build_ml_fields(prod)
        seller_sku = str(fields.get("sku") or "").strip() or mlb_up
        _append_mlb_slot(
            sku_map,
            seller_sku,
            mlb_up,
            bool(prod.get("catalog_listing")),
            str(prod.get("status") or "active"),
        )
    return sku_map


def _fetch_anymarket_fields_by_skus(
    skus: list[str],
    gumga_token: str,
    any_platform: str | None,
    progress_callback=None,
    product_ids_by_sku: dict[str, str] | None = None,
    sku_ids_by_sku: dict[str, str] | None = None,
    mlbs_by_sku: dict[str, list[str]] | None = None,
    eans_by_sku: dict[str, str] | None = None,
    db_slots_by_sku: dict[str, dict] | None = None,
) -> dict[str, dict]:
    """Busca cadastro AnyMarket via GET /products/{id}, /products/.../skus e /skus/.../marketplaces/...)."""
    unique = list(dict.fromkeys(s.strip() for s in skus if s and str(s).strip() and not _is_mlb(s)))
    out: dict[str, dict] = {}
    if not unique or not (gumga_token or "").strip():
        return out

    gumga = gumga_token.strip()
    total = len(unique)
    completed = 0
    ids_by_sku = product_ids_by_sku or {}
    sku_ids = dict(sku_ids_by_sku or {})
    mlb_map = mlbs_by_sku or {}
    ean_map = eans_by_sku or {}

    slots_by_sku = db_slots_by_sku or {}

    def _one(sku: str) -> tuple[str, dict]:
        product = {}
        sku_id_hint = str(sku_ids.get(sku) or "").strip()
        ean_hint = str(ean_map.get(sku) or "").strip()
        product_id = str(ids_by_sku.get(sku) or "").strip()
        slot = slots_by_sku.get(sku) or {}
        marketplace_pairs = _marketplace_pairs_for_sku(slot, sku_id_hint)
        try:
            product, resolved_sid = load_product_for_sku_audit(
                gumga,
                any_platform,
                product_id=product_id,
                sku_id=sku_id_hint,
                partner_sku=sku,
                marketplace_pairs=marketplace_pairs,
            )
            if resolved_sid and not sku_id_hint:
                sku_id_hint = resolved_sid
        except PermissionError as exc:
            print(f"[ANYMARKET] SKU {sku}: token recusado ({exc})", flush=True)
            product = {}
        except Exception as exc:
            print(f"[ANYMARKET] SKU {sku}: {type(exc).__name__}: {exc}", flush=True)
            product = {}
        if not product:
            try:
                product = find_product_by_partner_id(sku, gumga, any_platform)
            except PermissionError as exc:
                print(f"[ANYMARKET] SKU {sku}: token recusado ({exc})", flush=True)
                product = {}
            except Exception as exc:
                print(f"[ANYMARKET] SKU {sku}: {type(exc).__name__}: {exc}", flush=True)
                product = {}
        if not product:
            for mlb in mlb_map.get(sku) or []:
                try:
                    found, listing_sku_id = resolve_product_by_marketplace_id(mlb, gumga, any_platform)
                except PermissionError as exc:
                    print(f"[ANYMARKET] SKU {sku}: token recusado ({exc})", flush=True)
                    found, listing_sku_id = {}, ""
                except Exception as exc:
                    print(f"[ANYMARKET] SKU {sku}: MLB {mlb} {type(exc).__name__}: {exc}", flush=True)
                    found, listing_sku_id = {}, ""
                if found:
                    product = found
                    if listing_sku_id and not sku_id_hint:
                        sku_id_hint = listing_sku_id
                    print(f"[ANYMARKET] SKU {sku}: cadastro via MLB {mlb}", flush=True)
                    break
        if not product and ean_hint:
            try:
                found, listing_sku_id = find_product_by_ean(ean_hint, gumga, any_platform)
            except PermissionError as exc:
                print(f"[ANYMARKET] SKU {sku}: token recusado ({exc})", flush=True)
                found, listing_sku_id = {}, ""
            except Exception as exc:
                print(f"[ANYMARKET] SKU {sku}: EAN {ean_hint} {type(exc).__name__}: {exc}", flush=True)
                found, listing_sku_id = {}, ""
            if found:
                product = found
                if listing_sku_id and not sku_id_hint:
                    sku_id_hint = listing_sku_id
                print(f"[ANYMARKET] SKU {sku}: cadastro via EAN {ean_hint}", flush=True)
        fields = (
            extract_anymarket_fields(
                product,
                sku_hint=sku,
                sku_id_hint=sku_id_hint,
                ean_hint=ean_hint,
            )
            if product
            else extract_anymarket_fields({})
        )
        if not (fields.get("any_id") or fields.get("title")):
            print(f"[ANYMARKET] SKU {sku}: cadastro não encontrado", flush=True)
        else:
            print(
                f"[ANYMARKET] SKU {sku}: id={fields.get('any_id')} "
                f"fotos={len(fields.get('images_list') or [])}",
                flush=True,
            )
        return sku, fields

    # Sequencial: o debug do Flask costuma engolir falhas em ThreadPool.
    for sku in unique:
        sku_key, fields = _one(sku)
        out[sku_key] = fields
        completed += 1
        if progress_callback:
            pct = int(88 + (completed / total) * 8)
            progress_callback(min(pct, 96), 100, f"AnyMarket: {completed}/{total} SKU(s)...")
    return out


def process_skus_for_catalog_audit(
    sku_list: list[str],
    token: str,
    progress_callback=None,
    gumga_token: str | None = None,
    any_platform: str | None = None,
    sku_webhook_url: str | None = None,
    client_id: str | None = None,
    oi: str | None = None,
) -> dict:
    """
    Recebe uma lista de SKUs, consulta a réplica do AnyMarket para identificar os MLBs
    de Catálogo e Tradicional, baixa os detalhes live da API do Mercado Livre e gera a auditoria.
    Também busca o cadastro AnyMarket pelo SKU (partnerId) para o terceiro quadro.
    """
    skus = [s.strip() for s in sku_list if s.strip()]
    seen = set()
    skus_clean = []
    for s in skus:
        if s not in seen:
            seen.add(s)
            skus_clean.append(s)

    total_skus = len(skus_clean)
    if not skus_clean:
        return {
            "items": [],
            "summary": {"total": 0, "divergent": 0, "ok": 0, "attention": 0, "errors": 0},
            "errors": ["Nenhum SKU informado."],
        }

    sku_inputs = [s for s in skus_clean if not _is_mlb(s)]
    mlb_inputs = [s.upper() for s in skus_clean if _is_mlb(s)]
    # (rótulo exibido, sku usado na busca)
    input_rows: list[tuple[str, str]] = [(s, s) for s in sku_inputs]
    env_gumga = get_gumga_token()
    if env_gumga:
        gumga = env_gumga
        platform = (ANYMARKET_PLATFORM or "SELETA").strip()
    else:
        gumga = (gumga_token if gumga_token is not None else "") or ""
        platform = (any_platform or ANYMARKET_PLATFORM or "SELETA").strip()

    if progress_callback:
        progress_callback(10, 100, f"Mapeando anúncios de {total_skus} entrada(s)...")

    # 1. Réplica AnyMarket: sku_in_marketplace (SKU seller) ou id_in_marketplace (MLB)
    db_map = _resolve_skus_from_anymarket_db(
        sku_inputs,
        webhook_url=sku_webhook_url,
        client_id=client_id,
        platform=platform,
        oi=oi,
    )
    if mlb_inputs:
        _merge_sku_maps(
            db_map,
            _resolve_mlbs_from_anymarket_db(
                mlb_inputs,
                webhook_url=sku_webhook_url,
                client_id=client_id,
                platform=platform,
                oi=oi,
            ),
        )

    user_info = validate_token(token) if token else {}
    user_id = user_info.get("id")

    # 2. MLB(s) via API ML → seller SKU + cat/trad
    if mlb_inputs:
        if user_id:
            _merge_sku_maps(db_map, _resolve_mlbs_via_ml_api(mlb_inputs, token))
            for mlb in mlb_inputs:
                for sku_key, slots in db_map.items():
                    all_mlbs = [m for m, _ in slots["cat"]] + [m for m, _ in slots["trad"]]
                    if mlb in all_mlbs:
                        input_rows.append((mlb, sku_key))
                        break
                else:
                    input_rows.append((mlb, mlb))
        else:
            for mlb in mlb_inputs:
                input_rows.append((mlb, mlb))

    # 3. Fallback: busca seller_sku na conta ML
    missing_skus = [
        s for s in sku_inputs
        if not db_map.get(s, {}).get("cat") and not db_map.get(s, {}).get("trad")
    ]
    if missing_skus and user_id:
        for s in missing_skus:
            _enrich_sku_from_ml_search(s, user_id, token, db_map)

    # 4. Enriquecer via ML só quando falta Catálogo ou Tradicional (evita N chamadas desnecessárias)
    lookup_skus = {lookup for _, lookup in input_rows if not _is_mlb(lookup)}
    if user_id:
        for sku in lookup_skus:
            slots = db_map.get(sku, {"cat": [], "trad": []})
            if not slots.get("cat") or not slots.get("trad"):
                _enrich_sku_from_ml_search(sku, user_id, token, db_map)

    if not input_rows:
        input_rows = [(s, s) for s in skus_clean]

    # 3. Coletar todos os MLBs únicos
    all_mlbs: list[str] = []
    for s, d in db_map.items():
        all_mlbs.extend([m for m, _ in d["cat"]])
        all_mlbs.extend([m for m, _ in d["trad"]])
    all_mlbs = list(dict.fromkeys(all_mlbs))
    for sku_key, slots in db_map.items():
        n_cat = len(slots.get("cat") or [])
        n_trad = len(slots.get("trad") or [])
        if n_cat or n_trad:
            print(
                f"[MLB MAP] SKU {sku_key}: {n_cat} catálogo(s), {n_trad} tradicional(is)",
                flush=True,
            )

    # 4. Baixar todos os produtos em lotes de BATCH_SIZE (20)
    produtos: dict = {}
    lock = threading.Lock()
    if all_mlbs:
        batches = [all_mlbs[i : i + BATCH_SIZE] for i in range(0, len(all_mlbs), BATCH_SIZE)]
        completed_mlbs = 0

        def _fetch(batch):
            nonlocal completed_mlbs
            result = get_products_batch(batch, token)
            with lock:
                produtos.update(result)
                completed_mlbs += len(batch)
                if progress_callback:
                    pct = int(30 + (completed_mlbs / len(all_mlbs)) * 60)
                    progress_callback(pct, 100, f"Baixando detalhes live de {len(all_mlbs)} anúncios...")

        with ThreadPoolExecutor(max_workers=min(len(batches), MAX_WORKERS)) as pool:
            futures = [pool.submit(_fetch, b) for b in batches]
            for f in as_completed(futures):
                f.result()

    # 5. Estruturar campos para cada produto do ML
    ml_fields_by_mlb: dict[str, dict] = {}
    for mlb_id, raw_prod in produtos.items():
        ml_fields_by_mlb[mlb_id] = _build_ml_fields(raw_prod)
    if ml_fields_by_mlb and token:
        if progress_callback:
            progress_callback(78, 100, "Buscando descrições dos anúncios ML...")
        _attach_ml_descriptions(ml_fields_by_mlb, token, progress_callback)

    # 6. Para cada SKU, parear Catálogo e Tradicional
    items: list[dict] = []
    count_div = 0
    count_ok = 0
    count_att = 0
    count_err = 0
    errors: list[str] = []
    db_err = _get_last_db_error()
    if db_err:
        errors.append(f"[ANYMARKET DB] {db_err[:220]}")
    webhook_meta = _get_last_webhook_meta()
    if webhook_meta.get("called") and not webhook_meta.get("ok") and webhook_meta.get("error"):
        errors.append(f"[N8N WEBHOOK] {str(webhook_meta.get('error') or '')[:220]}")
    if mlb_inputs and not user_id:
        errors.append("[MERCADO LIVRE] Token inválido ou expirado — informe um token válido para resolver MLB(s).")
    elif sku_inputs and not user_id and not db_map:
        errors.append("[MERCADO LIVRE] Token inválido ou expirado — fallback por seller_sku indisponível.")

    any_by_sku: dict[str, dict] = {}
    lookup_skus_for_any = [lookup for _, lookup in input_rows if not _is_mlb(lookup)]
    if gumga.strip() and lookup_skus_for_any:
        if progress_callback:
            progress_callback(88, 100, "Buscando cadastro AnyMarket por SKU...")
        mlbs_by_sku: dict[str, list[str]] = {}
        eans_by_sku: dict[str, str] = {}
        for sku in lookup_skus_for_any:
            slots = db_map.get(sku) or {}
            mlbs = [m for m, _ in (slots.get("cat") or [])] + [m for m, _ in (slots.get("trad") or [])]
            if mlbs:
                mlbs_by_sku[sku] = list(dict.fromkeys(mlbs))
            for mlb in mlbs_by_sku.get(sku) or []:
                ean = str((ml_fields_by_mlb.get(mlb) or {}).get("ean") or "").strip()
                if ean:
                    eans_by_sku[sku] = ean
                    break
        any_by_sku = _fetch_anymarket_fields_by_skus(
            lookup_skus_for_any,
            gumga.strip(),
            platform,
            progress_callback,
            product_ids_by_sku={
                sku: str((db_map.get(sku) or {}).get("any_product_id") or "").strip()
                for sku in lookup_skus_for_any
                if str((db_map.get(sku) or {}).get("any_product_id") or "").strip()
            },
            sku_ids_by_sku={
                sku: str((db_map.get(sku) or {}).get("any_sku_id") or "").strip()
                for sku in lookup_skus_for_any
                if str((db_map.get(sku) or {}).get("any_sku_id") or "").strip()
            },
            mlbs_by_sku=mlbs_by_sku,
            eans_by_sku=eans_by_sku,
            db_slots_by_sku={sku: db_map.get(sku) or {} for sku in lookup_skus_for_any},
        )
        found_n = sum(1 for f in any_by_sku.values() if (f or {}).get("any_id"))
        print(f"[ANYMARKET] {found_n}/{len(lookup_skus_for_any)} SKU(s) com cadastro")
        missing_any = [s for s in lookup_skus_for_any if not (any_by_sku.get(s) or {}).get("any_id")]
        if missing_any:
            preview = ", ".join(missing_any[:8])
            extra = f" (+{len(missing_any) - 8})" if len(missing_any) > 8 else ""
            errors.append(f"[ANYMARKET] SKU(s) sem cadastro na API: {preview}{extra}")
    elif lookup_skus_for_any:
        errors.append("[ANYMARKET] Token Gumga ausente (GUMGA_TOKEN) — quadro AnyMarket vazio.")

    def _any_for(lookup: str) -> dict | None:
        fields = any_by_sku.get(lookup)
        if fields and (fields.get("any_id") or fields.get("title") or fields.get("sku")):
            return fields
        return None

    for input_label, lookup_sku in input_rows:
        d = db_map.get(lookup_sku, {"cat": [], "trad": []})
        cats = d.get("cat", [])
        trads = d.get("trad", [])

        if not cats and not trads:
            item = build_catalog_audit_item(lookup_sku, None, None, _any_for(lookup_sku))
            if _is_mlb(input_label):
                item["sku"] = lookup_sku if lookup_sku != input_label else input_label
                item["summary"] = (
                    f"MLB {input_label} não encontrado. "
                    "Verifique o token ML e se o anúncio pertence à conta autenticada."
                )
                item["divergences"] = [f"MLB {input_label} não resolvido"]
            count_err += 1
            items.append(item)
            if _is_mlb(input_label):
                errors.append(f"MLB {input_label}: não foi possível resolver para SKU seller.")
            else:
                errors.append(f"SKU {lookup_sku}: nenhum anúncio vinculado (filtro: sku_in_marketplace / seller_sku ML).")
            continue

        def _pick_best(candidates):
            if not candidates:
                return None
            for m, _ in candidates:
                p = ml_fields_by_mlb.get(m)
                if p and str(p.get("status", "")).lower() == "active":
                    return m
            for m, _ in candidates:
                if m in ml_fields_by_mlb:
                    return m
            return candidates[0][0]

        linked_cat_mlbs = [m for m, _ in cats]
        linked_trad_mlbs = [m for m, _ in trads]

        def _push_audit_item(cat_prod, trad_prod) -> None:
            nonlocal count_div, count_ok, count_att, count_err
            audit_item = build_catalog_audit_item(
                lookup_sku,
                cat_prod,
                trad_prod,
                _any_for(lookup_sku),
            )
            audit_item["mlbs_linked"] = {
                "cat": linked_cat_mlbs,
                "trad": linked_trad_mlbs,
            }
            st = audit_item.get("status_geral")
            if st == "OK":
                count_ok += 1
            elif st == "DIVERGENTE":
                count_div += 1
            elif st == "ATENCAO":
                count_att += 1
            else:
                count_err += 1
            items.append(audit_item)

        # Se o input foi um MLB específico, parear com esse MLB
        if _is_mlb(input_label):
            in_cat = any(m == input_label for m, _ in cats)
            in_trad = any(m == input_label for m, _ in trads)

            def _push_mlb_input_item(cat_prod, trad_prod) -> None:
                audit_item = build_catalog_audit_item(
                    lookup_sku,
                    cat_prod,
                    trad_prod,
                    _any_for(lookup_sku),
                )
                audit_item["input_mlb"] = input_label
                audit_item["mlbs_linked"] = {"cat": linked_cat_mlbs, "trad": linked_trad_mlbs}
                if input_label != lookup_sku:
                    audit_item["summary"] = (
                        f"Entrada MLB {input_label} → SKU {lookup_sku}. {audit_item.get('summary', '')}"
                    )
                st = audit_item.get("status_geral")
                if st == "OK":
                    count_ok += 1
                elif st == "DIVERGENTE":
                    count_div += 1
                elif st == "ATENCAO":
                    count_att += 1
                else:
                    count_err += 1
                items.append(audit_item)

            if in_cat and trads:
                cat_prod = ml_fields_by_mlb.get(input_label)
                for trad_mlb, _ in trads:
                    _push_mlb_input_item(cat_prod, ml_fields_by_mlb.get(trad_mlb))
            elif in_trad and cats:
                trad_prod = ml_fields_by_mlb.get(input_label)
                for cat_mlb, _ in cats:
                    _push_mlb_input_item(ml_fields_by_mlb.get(cat_mlb), trad_prod)
            elif in_cat:
                _push_mlb_input_item(ml_fields_by_mlb.get(input_label), None)
            elif in_trad:
                _push_mlb_input_item(None, ml_fields_by_mlb.get(input_label))
            else:
                _push_mlb_input_item(ml_fields_by_mlb.get(input_label), None)
        else:
            # Input é SKU: todos catálogos × todos tradicionais (cada anúncio vinculado)
            if cats and trads:
                for cat_mlb, _ in cats:
                    cat_prod = ml_fields_by_mlb.get(cat_mlb)
                    for trad_mlb, _ in trads:
                        trad_prod = ml_fields_by_mlb.get(trad_mlb)
                        _push_audit_item(cat_prod, trad_prod)
            elif cats:
                for cat_mlb, _ in cats:
                    cat_prod = ml_fields_by_mlb.get(cat_mlb)
                    _push_audit_item(cat_prod, None)
            elif trads:
                for trad_mlb, _ in trads:
                    trad_prod = ml_fields_by_mlb.get(trad_mlb)
                    _push_audit_item(None, trad_prod)

    return {
        "items": items,
        "summary": {
            "total": len(items),
            "divergent": count_div,
            "ok": count_ok,
            "attention": count_att,
            "errors": count_err,
        },
        "errors": errors,
        "lookup": {
            "client_id": client_id or "",
            "webhook_called": bool(webhook_meta.get("called")),
            "webhook_ok": bool(webhook_meta.get("ok")),
            "webhook_status": webhook_meta.get("status"),
        },
    }


def process_skus_for_catalog_excel(
    sku_list: list[str],
    token: str,
    reviews: dict[str, str] | None = None,
    filter_decision: str = "all",
    audit_items: list[dict] | None = None,
    gumga_token: str | None = None,
    any_platform: str | None = None,
    sku_webhook_url: str | None = None,
    client_id: str | None = None,
    oi: str | None = None,
) -> tuple[list, list]:
    """
    Gera as linhas da planilha comparativa ML Catálogo vs ML Tradicional.
    Se audit_items for informado, reutiliza os dados já auditados (exportação rápida).
    """
    if audit_items is not None:
        items = audit_items
        errors: list[str] = []
    else:
        audit_data = process_skus_for_catalog_audit(
            sku_list,
            token,
            gumga_token=gumga_token,
            any_platform=any_platform,
            sku_webhook_url=sku_webhook_url,
            client_id=client_id,
            oi=oi,
        )
        items = audit_data.get("items") or []
        errors = audit_data.get("errors") or []

    reviews = reviews or {}
    filter_decision = (filter_decision or "all").lower().strip()

    filtered = []
    for item in items:
        sku = item.get("sku", "")
        item_id = item.get("item_id") or (f"{sku}_{item.get('mlb_cat')}" if item.get("mlb_cat") else sku)
        mlb_cat = item.get("mlb_cat", "")
        dec = reviews.get(item_id) or reviews.get(mlb_cat) or reviews.get(sku) or "PENDENTE"
        if filter_decision == "approved" and dec != "APROVADO":
            continue
        if filter_decision == "rejected" and dec != "REPROVADO":
            continue
        if filter_decision == "pending" and dec not in ("PENDENTE", ""):
            continue
        filtered.append(item)

    headers = [
        "SKU",
        "MLB_CATALOGO",
        "MLB_TRADICIONAL",
        "STATUS_CATALOGO",
        "STATUS_TRADICIONAL",
        "Δ_STATUS",
        "PRECO_CATALOGO",
        "PRECO_TRADICIONAL",
        "Δ_PRECO",
        "ESTOQUE_CATALOGO",
        "ESTOQUE_TRADICIONAL",
        "Δ_ESTOQUE",
        "TIPO_CATALOGO",
        "TIPO_TRADICIONAL",
        "Δ_TIPO",
        "ENVIO_CATALOGO",
        "ENVIO_TRADICIONAL",
        "Δ_ENVIO",
        "TITULO_CATALOGO",
        "TITULO_TRADICIONAL",
        "MARCA_CATALOGO",
        "MARCA_TRADICIONAL",
        "VOLTAGEM_CATALOGO",
        "VOLTAGEM_TRADICIONAL",
        "QTD_FOTOS_CATALOGO",
        "QTD_FOTOS_TRADICIONAL",
        "DIVERGENCIAS",
        "STATUS_GERAL",
        "DECISAO_AUDITORIA",
    ]

    rows = [headers]
    for item in filtered:
        sku = item.get("sku", "")
        item_id = item.get("item_id") or (f"{sku}_{item.get('mlb_cat')}" if item.get("mlb_cat") else sku)
        mlb_cat = item.get("mlb_cat", "")
        cat = item.get("ml") or {}
        trad = item.get("any") or {}

        status_cat = cat.get("status", "")
        status_trad = trad.get("status", "")
        d_status = match_values(status_cat, status_trad) if (cat and trad) else "AUSENTE"

        preco_cat = str(cat.get("price", "") or "")
        preco_trad = str(trad.get("price", "") or "")
        d_preco = match_values(preco_cat, preco_trad) if (cat and trad) else "AUSENTE"

        est_cat = str(cat.get("stock", "") or "")
        est_trad = str(trad.get("stock", "") or "")
        d_est = match_values(est_cat, est_trad) if (cat and trad) else "AUSENTE"

        tipo_cat = cat.get("listing_type", "")
        tipo_trad = trad.get("listing_type", "")
        d_tipo = match_values(tipo_cat, tipo_trad) if (cat and trad) else "AUSENTE"

        env_cat = cat.get("shipping_type", "")
        env_trad = trad.get("shipping_type", "")
        d_env = match_values(env_cat, env_trad) if (cat and trad) else "AUSENTE"

        diff_summary = " | ".join(item.get("divergences") or []) if item.get("divergences") else "OK"
        dec = reviews.get(item_id) or reviews.get(mlb_cat) or reviews.get(sku) or "PENDENTE"

        row = [
            sku,
            item.get("mlb_cat", ""),
            item.get("mlb_trad", ""),
            status_cat,
            status_trad,
            d_status,
            preco_cat,
            preco_trad,
            d_preco,
            est_cat,
            est_trad,
            d_est,
            tipo_cat,
            tipo_trad,
            d_tipo,
            env_cat,
            env_trad,
            d_env,
            cat.get("title", ""),
            trad.get("title", ""),
            cat.get("brand", ""),
            trad.get("brand", ""),
            cat.get("voltage", ""),
            trad.get("voltage", ""),
            str(cat.get("image_count", 0)),
            str(trad.get("image_count", 0)),
            diff_summary,
            item.get("status_geral", ""),
            dec,
        ]
        rows.append(row)

    return rows, errors

