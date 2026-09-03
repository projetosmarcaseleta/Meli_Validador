"""
exporter.py – Extrai campos do Mercado Livre e AnyMarket lado a lado com divergências.
"""

from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from anymarket_api import extract_anymarket_fields, find_product_by_partner_id, get_product
from api import BATCH_SIZE, LISTING_LABELS, LOGISTIC_LABELS, get_products_batch, search_items_by_seller_sku, validate_token
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
)
from import_parser import ImportRow

HEADERS = [
    "SKU", "MLB", "TITULO", "COR", "TAMANHO", "GÊNERO", "VOLTAGEM", "KIT",
    "TIPO ANÚNCIO", "TIPO ENVIO", "CATÁLOGO", "QTD VENDIDA",
    "IMAGEM PRINCIPAL", "IMAGENS",
]

_MLB_PATTERN = re.compile(r"^MLB\d+$", re.IGNORECASE)
_last_db_error: str | None = None


def _is_mlb(value: str) -> bool:
    return bool(_MLB_PATTERN.match(str(value or "").strip()))


def _get_last_db_error() -> str | None:
    return _last_db_error


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


def _append_mlb_slot(sku_map: dict[str, dict], sku: str, mlb: str, is_catalog: bool, status: str = "") -> None:
    if sku not in sku_map:
        sku_map[sku] = {"cat": [], "trad": []}
    side = "cat" if is_catalog else "trad"
    existing = {m for m, _ in sku_map[sku][side]}
    if mlb not in existing:
        sku_map[sku][side].append((mlb, status or "active"))


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


def _build_ml_fields(produto: dict) -> dict[str, str | int | list]:
    listing_id = produto.get("listing_type_id", "")
    attrs = _attrs_map(produto)
    image_urls = _resolve_image_urls(produto)
    description = str(produto.get("descriptions") or produto.get("description") or "")
    if isinstance(produto.get("descriptions"), list):
        parts = []
        for block in produto.get("descriptions") or []:
            if isinstance(block, dict):
                parts.append(str(block.get("plain_text") or block.get("text") or ""))
        description = " ".join(parts)
    description = str(description).strip()
    if len(description) > 500:
        description = description[:497] + "..."

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
        "catalog_product_id": str(produto.get("catalog_product_id") or ""),
        "permalink": str(produto.get("permalink") or ""),
        "image_main": image_urls[0] if image_urls else "",
        "image_count": str(len(image_urls)),
        "images": " | ".join(image_urls),
        "images_list": image_urls,
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


def _resolve_skus_from_anymarket_db(skus: list[str]) -> dict[str, dict]:
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
    sku_map: dict[str, dict] = {s: {"cat": [], "trad": []} for s in skus}
    if not skus:
        return sku_map

    # 1. Tentar via Webhook n8n se configurado
    if ANYMARKET_SKU_WEBHOOK_URL:
        try:
            import requests as req
            resp = req.post(
                ANYMARKET_SKU_WEBHOOK_URL,
                json={"skus": skus},
                timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json() or {}
                incoming_map = data.get("sku_map") or {}
                for s, val in incoming_map.items():
                    s_clean = str(s).strip()
                    if s_clean in sku_map:
                        cat_list = [(str(m[0]).upper(), str(m[1])) for m in val.get("cat", []) if m and len(m) >= 2]
                        trad_list = [(str(m[0]).upper(), str(m[1])) for m in val.get("trad", []) if m and len(m) >= 2]
                        sku_map[s_clean]["cat"] = cat_list
                        sku_map[s_clean]["trad"] = trad_list
                if any(sku_map[s]["cat"] or sku_map[s]["trad"] for s in sku_map):
                    return sku_map
            else:
                print(f"[N8N WEBHOOK ERRO] HTTP {resp.status_code}: {resp.text[:200]}")
        except Exception as exc:
            print(f"[N8N WEBHOOK ERRO] Falha na consulta via n8n: {exc}")

    # 2. Tentar via Conexão Direta ao PostgreSQL
    if not ANYMARKET_DB_HOST or not ANYMARKET_DB_USER:
        if skus and not ANYMARKET_DB_HOST and not ANYMARKET_SKU_WEBHOOK_URL:
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
                        SELECT DISTINCT
                            sm.sku_in_marketplace AS sku,
                            sm.id_in_marketplace AS mlb,
                            sm.is_catalog,
                            sm.status_in_marketplace
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
                        if s in sku_map and mlb.startswith("MLB"):
                            _append_mlb_slot(sku_map, s, mlb, is_cat == 1, status)
    except Exception as exc:
        _last_db_error = str(exc)
        print(f"[DB ANYMARKET ERRO] Falha ao consultar réplica AnyMarket: {exc}")

    return sku_map


def _resolve_mlbs_from_anymarket_db(mlbs: list[str]) -> dict[str, dict]:
    """
    Resolve MLB(s) → SKU seller via réplica AnyMarket (id_in_marketplace) ou Webhook n8n.
    Retorna mapa keyed pelo sku_in_marketplace.
    """
    global _last_db_error
    sku_map: dict[str, dict] = {}
    if not mlbs:
        return sku_map

    # 1. Tentar via Webhook n8n se configurado
    if ANYMARKET_SKU_WEBHOOK_URL:
        try:
            import requests as req
            resp = req.post(
                ANYMARKET_SKU_WEBHOOK_URL,
                json={"mlbs": mlbs},
                timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json() or {}
                incoming_map = data.get("sku_map") or {}
                _merge_sku_maps(sku_map, incoming_map)
                if sku_map:
                    return sku_map
            else:
                print(f"[N8N WEBHOOK ERRO] HTTP {resp.status_code}: {resp.text[:200]}")
        except Exception as exc:
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
                        SELECT DISTINCT
                            sm.sku_in_marketplace AS sku,
                            sm.id_in_marketplace AS mlb,
                            sm.is_catalog,
                            sm.status_in_marketplace
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
                        if mlb.startswith("MLB") and s:
                            _append_mlb_slot(sku_map, s, mlb, is_cat == 1, status)
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


def process_skus_for_catalog_audit(
    sku_list: list[str],
    token: str,
    progress_callback=None,
) -> dict:
    """
    Recebe uma lista de SKUs, consulta a réplica do AnyMarket para identificar os MLBs
    de Catálogo e Tradicional, baixa os detalhes live da API do Mercado Livre e gera a auditoria.
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

    if progress_callback:
        progress_callback(10, 100, f"Mapeando anúncios de {total_skus} entrada(s)...")

    # 1. Réplica AnyMarket: sku_in_marketplace (SKU seller) ou id_in_marketplace (MLB)
    db_map = _resolve_skus_from_anymarket_db(sku_inputs)
    if mlb_inputs:
        _merge_sku_maps(db_map, _resolve_mlbs_from_anymarket_db(mlb_inputs))

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
    if mlb_inputs and not user_id:
        errors.append("[MERCADO LIVRE] Token inválido ou expirado — informe um token válido para resolver MLB(s).")
    elif sku_inputs and not user_id and not db_map:
        errors.append("[MERCADO LIVRE] Token inválido ou expirado — fallback por seller_sku indisponível.")

    for input_label, lookup_sku in input_rows:
        d = db_map.get(lookup_sku, {"cat": [], "trad": []})
        cats = d.get("cat", [])
        trads = d.get("trad", [])

        if not cats and not trads:
            item = build_catalog_audit_item(lookup_sku, None, None)
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

        trad_mlb = _pick_best(trads)
        trad_prod = ml_fields_by_mlb.get(trad_mlb) if trad_mlb else None

        # Se o input foi um MLB específico, parear com esse MLB
        if _is_mlb(input_label):
            if any(m == input_label for m, _ in cats):
                cat_mlb = input_label
                cat_prod = ml_fields_by_mlb.get(cat_mlb)
            elif any(m == input_label for m, _ in trads):
                trad_mlb = input_label
                trad_prod = ml_fields_by_mlb.get(trad_mlb)
                cat_mlb = _pick_best(cats)
                cat_prod = ml_fields_by_mlb.get(cat_mlb) if cat_mlb else None
            else:
                cat_mlb = input_label
                cat_prod = ml_fields_by_mlb.get(cat_mlb)

            audit_item = build_catalog_audit_item(lookup_sku, cat_prod, trad_prod)
            audit_item["input_mlb"] = input_label
            if input_label != lookup_sku:
                audit_item["summary"] = f"Entrada MLB {input_label} → SKU {lookup_sku}. {audit_item.get('summary', '')}"
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
        else:
            # Input é SKU: se tiver múltiplos catálogos vinculados, gera um item para cada catálogo contra o tradicional
            if cats:
                for cat_entry in cats:
                    cat_mlb = cat_entry[0]
                    cat_prod = ml_fields_by_mlb.get(cat_mlb)
                    audit_item = build_catalog_audit_item(lookup_sku, cat_prod, trad_prod)
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
            else:
                # Sem catálogo, apenas tradicional
                audit_item = build_catalog_audit_item(lookup_sku, None, trad_prod)
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
    }


def process_skus_for_catalog_excel(
    sku_list: list[str],
    token: str,
    reviews: dict[str, str] | None = None,
    filter_decision: str = "all",
    audit_items: list[dict] | None = None,
) -> tuple[list, list]:
    """
    Gera as linhas da planilha comparativa ML Catálogo vs ML Tradicional.
    Se audit_items for informado, reutiliza os dados já auditados (exportação rápida).
    """
    if audit_items is not None:
        items = audit_items
        errors: list[str] = []
    else:
        audit_data = process_skus_for_catalog_audit(sku_list, token)
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

