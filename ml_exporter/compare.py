"""
compare.py – Montagem lado a lado ML × AnyMarket e resumo de divergências.
"""

from __future__ import annotations

from anymarket_api import match_values

# Campos comparáveis: (chave_interna, rótulo_planilha)
COMPARE_FIELDS: list[tuple[str, str]] = [
    ("sku", "SKU"),
    ("title", "TITULO"),
    ("description", "DESCRICAO"),
    ("brand", "MARCA"),
    ("model", "MODELO"),
    ("color", "COR"),
    ("size", "TAMANHO"),
    ("gender", "GENERO"),
    ("voltage", "VOLTAGEM"),
    ("kit", "KIT"),
    ("ean", "EAN"),
    ("price", "PRECO"),
    ("stock", "ESTOQUE"),
    ("image_main", "IMAGEM_PRINCIPAL"),
    ("image_count", "QTD_IMAGENS"),
    ("images", "IMAGENS"),
]

ML_ONLY_FIELDS: list[tuple[str, str]] = [
    ("mlb", "MLB"),
    ("listing_type", "TIPO_ANUNCIO"),
    ("shipping_type", "TIPO_ENVIO"),
    ("catalog", "CATALOGO"),
    ("sold_quantity", "QTD_VENDIDA"),
    ("condition", "CONDICAO"),
    ("status", "STATUS_ML"),
    ("category_id", "CATEGORIA_ML"),
    ("permalink", "LINK_ML"),
]

ANY_ONLY_FIELDS: list[tuple[str, str]] = [
    ("any_id", "ANY_ID"),
    ("any_sku_id", "ANY_SKU_ID"),
    ("category", "ANY_CATEGORIA"),
    ("is_active", "ANY_ATIVO"),
    ("has_variations", "ANY_VARIACOES"),
    ("external_id", "ANY_EXTERNAL_ID"),
    ("height", "ANY_ALTURA"),
    ("width", "ANY_LARGURA"),
    ("length", "ANY_PROFUNDIDADE"),
    ("weight", "ANY_PESO"),
]

IMPORT_FIELDS: list[tuple[str, str]] = [
    ("id_sku", "IMP_ID_SKU"),
    ("id_product", "IMP_ID_PRODUCT"),
    ("id_sku_marketplace", "IMP_ID_SKU_MKT"),
    ("title", "IMP_TITULO"),
]


def build_compare_headers(with_import: bool, with_any: bool, with_decision: bool = False) -> list[str]:
    if not with_any:
        headers = [
            "SKU", "MLB", "TITULO", "COR", "TAMANHO", "GÊNERO", "VOLTAGEM", "KIT",
            "TIPO ANÚNCIO", "TIPO ENVIO", "CATÁLOGO", "QTD VENDIDA",
            "IMAGEM PRINCIPAL", "IMAGENS",
        ]
        if with_import:
            headers.extend([label for _, label in IMPORT_FIELDS])
            headers.extend(["Δ_MLB", "Δ_SKU_MKT", "Δ_IMP_TITULO"])
        if with_decision:
            headers.append("DECISAO_AUDITORIA")
        return headers

    headers: list[str] = ["MLB"]
    if with_import:
        headers.extend([label for _, label in IMPORT_FIELDS])
        headers.extend(["Δ_MLB", "Δ_SKU_MKT", "Δ_IMP_TITULO"])

    for _, label in COMPARE_FIELDS:
        headers.extend([f"ML_{label}", f"ANY_{label}", f"Δ_{label}"])

    for _, label in ML_ONLY_FIELDS:
        if label == "MLB":
            continue
        headers.append(f"ML_{label}")

    headers.extend(label for _, label in ANY_ONLY_FIELDS)
    headers.extend(["DIVERGENCIAS", "STATUS_GERAL"])
    if with_decision:
        headers.append("DECISAO_AUDITORIA")
    return headers


def _divergence_text(label: str, ml_val: str, any_val: str, status: str) -> str | None:
    if status in ("OK", "AMBOS_VAZIOS"):
        return None
    if label == "IMAGENS":
        return "Galeria de Fotos: Imagens ou ordenação diferente"
    if label == "IMAGEM_PRINCIPAL":
        return "Foto Principal: Imagem de capa diferente"
    if label == "DESCRICAO":
        return "Descrição: Texto diferente"
    if label == "QTD_IMAGENS":
        return f"Qtd de Fotos: ML={ml_val or '0'} ≠ ANY={any_val or '0'}"
    if status == "DIVERGENTE":
        ml_short = str(ml_val)[:50]
        any_short = str(any_val)[:50]
        return f"{label}: ML='{ml_short}' ≠ ANY='{any_short}'"
    return f"{label}: {status}"


def build_compare_row(
    ml: dict,
    any_data: dict,
    import_row: dict | None = None,
    with_import: bool = False,
    decision: str | None = None,
) -> list:
    row: list = [ml.get("mlb", "")]

    if with_import:
        imp = import_row or {}
        imp_mlb = str(imp.get("mlb") or "").strip().upper()
        imp_mkt = str(imp.get("id_sku_marketplace") or "").strip().upper()
        imp_title = str(imp.get("title") or "").strip()
        row.extend([
            imp.get("id_sku", ""),
            imp.get("id_product", ""),
            imp.get("id_sku_marketplace", ""),
            imp_title,
            match_values(str(ml.get("mlb", "")), imp_mlb),
            match_values(str(ml.get("mlb", "")), imp_mkt),
            match_values(str(ml.get("title", "")), imp_title),
        ])

    divergences: list[str] = []
    compare_statuses: list[str] = []

    for key, label in COMPARE_FIELDS:
        ml_val = str(ml.get(key, "") or "")
        any_val = str(any_data.get(key, "") or "")
        status = match_values(ml_val, any_val)
        compare_statuses.append(status)
        row.extend([ml_val, any_val, status])
        diff = _divergence_text(label, ml_val, any_val, status)
        if diff:
            divergences.append(diff)

    for key, label in ML_ONLY_FIELDS:
        if label == "MLB":
            continue
        row.append(ml.get(key, ""))

    for key, label in ANY_ONLY_FIELDS:
        row.append(any_data.get(key, ""))

    if divergences:
        summary = " | ".join(divergences)
        status_geral = "DIVERGENTE"
    elif any(s not in ("OK", "AMBOS_VAZIOS") for s in compare_statuses):
        status_geral = "ATENCAO"
    else:
        summary = "OK — todos os campos comparáveis iguais"
        status_geral = "OK"

    row.extend([summary, status_geral])
    if decision is not None:
        row.append(decision)
    return row


def build_ml_only_row(
    ml: dict,
    import_row: dict | None = None,
    with_import: bool = False,
    decision: str | None = None,
) -> list:
    row = [
        ml.get("sku", ""),
        ml.get("mlb", ""),
        ml.get("title", ""),
        ml.get("color", ""),
        ml.get("size", ""),
        ml.get("gender", ""),
        ml.get("voltage", ""),
        ml.get("kit", ""),
        ml.get("listing_type", ""),
        ml.get("shipping_type", ""),
        ml.get("catalog", ""),
        ml.get("sold_quantity", 0),
        ml.get("image_main", ""),
        ml.get("images", ""),
    ]
    if with_import:
        imp = import_row or {}
        row.extend([
            imp.get("id_sku", ""),
            imp.get("id_product", ""),
            imp.get("id_sku_marketplace", ""),
            imp.get("title", ""),
            match_values(str(ml.get("mlb", "")), str(imp.get("mlb") or "")),
            match_values(str(ml.get("mlb", "")), str(imp.get("id_sku_marketplace") or "")),
            match_values(str(ml.get("title", "")), str(imp.get("title") or "")),
        ])
    if decision is not None:
        row.append(decision)
    return row


def build_audit_item(
    ml: dict,
    any_data: dict,
    import_row: dict | None = None,
    with_import: bool = False,
    with_any: bool = True,
) -> dict:
    divergences: list[str] = []
    compare_statuses: list[str] = []
    field_comparisons: list[dict] = []

    for key, label in COMPARE_FIELDS:
        ml_val = str(ml.get(key, "") or "")
        any_val = str(any_data.get(key, "") or "") if with_any else ""
        status = match_values(ml_val, any_val) if with_any else "OK"
        if with_any:
            compare_statuses.append(status)
            diff = _divergence_text(label, ml_val, any_val, status)
            if diff:
                divergences.append(diff)
        field_comparisons.append({
            "key": key,
            "label": label,
            "ml_value": ml_val,
            "any_value": any_val,
            "status": status,
        })

    # Verificação de imagens específicas
    ml_imgs = ml.get("images_list") or []
    any_imgs = any_data.get("images_list") or [] if with_any else []

    if not with_any:
        status_geral = "INFO"
        summary = "Somente Mercado Livre (sem validação AnyMarket)"
    elif divergences:
        summary = " | ".join(divergences)
        status_geral = "DIVERGENTE"
    elif any(s not in ("OK", "AMBOS_VAZIOS") for s in compare_statuses):
        status_geral = "ATENCAO"
    else:
        summary = "OK — todos os campos comparáveis iguais"
        status_geral = "OK"

    return {
        "mlb": ml.get("mlb", ""),
        "sku": ml.get("sku") or (any_data.get("sku", "") if with_any else ""),
        "title": ml.get("title") or (any_data.get("title", "") if with_any else ""),
        "status_geral": status_geral,
        "summary": summary,
        "divergences": divergences,
        "ml": ml,
        "any": any_data if with_any else {},
        "comparison": field_comparisons,
    }


CATALOG_COMPARE_FIELDS: list[tuple[str, str]] = [
    ("status", "STATUS"),
    ("price", "PREÇO"),
    ("listing_type", "TIPO ANÚNCIO"),
    ("shipping_type", "TIPO DE ENVIO"),
    ("stock", "ESTOQUE"),
    ("title", "TÍTULO"),
    ("brand", "MARCA"),
    ("model", "MODELO"),
    ("color", "COR"),
    ("size", "TAMANHO"),
    ("voltage", "VOLTAGEM"),
    ("ean", "EAN / GTIN"),
    ("sold_quantity", "VENDAS"),
    ("description", "DESCRIÇÃO"),
    ("image_count", "QTD FOTOS"),
]


def build_catalog_audit_item(sku: str, cat_item: dict | None, trad_item: dict | None) -> dict:
    cat = cat_item or {}
    trad = trad_item or {}
    divergences: list[str] = []
    field_comparisons: list[dict] = []

    has_cat = bool(cat_item)
    has_trad = bool(trad_item)

    if not has_cat and not has_trad:
        return {
            "sku": sku,
            "title": f"SKU {sku} (Não encontrado)",
            "mlb": "N/A",
            "mlb_cat": "",
            "mlb_trad": "",
            "status_geral": "ERRO",
            "summary": "Nenhum anúncio encontrado para este SKU no Mercado Livre",
            "divergences": ["Anúncio não encontrado no ML"],
            "ml": {"images_list": []},
            "any": {"images_list": []},
            "comparison": [],
        }

    if not has_cat:
        divergences.append("⚠️ Anúncio de Catálogo AUSENTE no ML")
    if not has_trad:
        divergences.append("⚠️ Anúncio Tradicional AUSENTE no ML")

    for key, label in CATALOG_COMPARE_FIELDS:
        cat_val = str(cat.get(key, "") or "")
        trad_val = str(trad.get(key, "") or "")
        status = match_values(cat_val, trad_val) if (has_cat and has_trad) else ("AUSENTE_CAT" if not has_cat else "AUSENTE_TRAD")

        if has_cat and has_trad and status not in ("OK", "AMBOS_VAZIOS"):
            if key == "image_count":
                diff = f"Qtd Fotos: Catálogo ({cat_val}) ≠ Tradicional ({trad_val})"
            elif key == "price":
                diff = f"Preço: Catálogo R$ {cat_val} ≠ Tradicional R$ {trad_val}"
            elif key == "status":
                diff = f"Status: Catálogo ({cat_val}) ≠ Tradicional ({trad_val})"
            elif key == "shipping_type":
                diff = f"Envio: Catálogo ({cat_val}) ≠ Tradicional ({trad_val})"
            elif key == "listing_type":
                diff = f"Tipo: Catálogo ({cat_val}) ≠ Tradicional ({trad_val})"
            elif key == "description":
                diff = "Descrição diferente"
            else:
                diff = f"{label}: Catálogo='{cat_val[:40]}' ≠ Tradicional='{trad_val[:40]}'"
            divergences.append(diff)

        field_comparisons.append({
            "key": key,
            "label": label,
            "ml_value": cat_val,
            "any_value": trad_val,
            "status": status,
        })

    if not has_cat or not has_trad:
        status_geral = "ATENCAO"
        summary = "Anúncio ausente em uma das modalidades (Catálogo ou Tradicional)"
    elif divergences:
        status_geral = "DIVERGENTE"
        summary = " | ".join(divergences)
    else:
        status_geral = "OK"
        summary = "Catálogo e Tradicional 100% iguais"

    main_title = trad.get("title") or cat.get("title") or f"SKU {sku}"
    main_mlb = trad.get("mlb") or cat.get("mlb") or ""

    return {
        "sku": sku,
        "title": main_title,
        "mlb": main_mlb,
        "mlb_cat": cat.get("mlb", ""),
        "mlb_trad": trad.get("mlb", ""),
        "status_geral": status_geral,
        "summary": summary,
        "divergences": divergences,
        "ml": cat,
        "any": trad,
        "comparison": field_comparisons,
    }
