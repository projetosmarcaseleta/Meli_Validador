"""
triage_engine.py – Motor de Triagem Inteligente e Detecção de Divergências Críticas (Hard Mismatches)
Analisa anúncios de Catálogo vs Tradicional e categoriza descartes imediatos com alto rigor técnico.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed

from api import BATCH_SIZE, get_products_batch, search_items_by_seller_sku, validate_token, LISTING_LABELS, LOGISTIC_LABELS
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

# ── NORMALIZADORES DE TEXTO E ATRIBUTOS ──

def _normalize_str(val: str | None) -> str:
    if not val:
        return ""
    text = unicodedata.normalize("NFKD", str(val).strip().lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_attrs(produto: dict) -> dict[str, str]:
    """Extrai atributos relevantes em um dicionário normalizado id -> value_name."""
    attrs = {}
    for a in produto.get("attributes") or []:
        aid = str(a.get("id") or "").upper()
        vname = str(a.get("value_name") or "").strip()
        if aid and vname:
            attrs[aid] = vname
    return attrs


# Normalização de Cores
COLOR_MAP = {
    "branco": "branco",
    "white": "branco",
    "off white": "off_white",
    "off-white": "off_white",
    "preto": "preto",
    "black": "preto",
    "cinza": "cinza",
    "grey": "cinza",
    "gray": "cinza",
    "fendi": "fendi",
    "grafite": "grafite",
    "marrom": "marrom",
    "brown": "marrom",
    "castanho": "marrom",
    "freijo": "amadeirado",
    "freijó": "amadeirado",
    "amadeirado": "amadeirado",
    "madeira": "amadeirado",
    "carvalho": "amadeirado",
    "ipe": "amadeirado",
    "azul": "azul",
    "blue": "azul",
    "verde": "verde",
    "green": "verde",
    "vermelho": "vermelho",
    "red": "vermelho",
    "amarelo": "amarelo",
    "yellow": "amarelo",
    "rosa": "rosa",
    "pink": "rosa",
    "bege": "bege",
    "nude": "bege",
    "inox": "inox",
    "aco inox": "inox",
    "aco escovado": "inox",
    "dourado": "dourado",
    "gold": "dourado",
    "prata": "prata",
    "silver": "prata",
}

def normalize_color(color_str: str) -> str:
    norm = _normalize_str(color_str)
    if not norm:
        return ""
    for k, v in sorted(COLOR_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        if k in norm:
            return v
    return norm


# Normalização de Voltagem
def normalize_voltage(voltage_str: str) -> str:
    norm = _normalize_str(voltage_str)
    if not norm or norm in ("na", "n/a", "nao se aplica", "sem voltagem", "0"):
        return "N/A"
    if "bivolt" in norm or "110v/220v" in norm or "127v/220v" in norm or "todas" in norm:
        return "BIVOLT"
    if "110" in norm or "127" in norm:
        return "110V"
    if "220" in norm:
        return "220V"
    return norm.upper()


# Normalização de Marca
def normalize_brand(brand_str: str) -> str:
    norm = _normalize_str(brand_str)
    # Remove ruídos comuns em marketplaces
    norm = re.sub(r"\b(moveis|móveis|eletro|eletros|brasil|ltda|me|s/a|sa|ind|industria)\b", "", norm)
    norm = re.sub(r"[^\w\s]", "", norm)
    return norm.strip()


# Normalização de Tamanho (Camas / Guarda-roupas / Roupas)
SIZE_GROUPS = {
    "solteiro": "solteiro",
    "solteirao": "solteiro",
    "casal": "casal",
    "queen": "queen",
    "king": "king",
    "super king": "king",
    "infantil": "infantil",
    "bebe": "infantil",
    "berco": "infantil",
    "juvenil": "juvenil",
}

def normalize_size(size_str: str) -> str:
    norm = _normalize_str(size_str)
    if not norm:
        return ""
    for k, v in SIZE_GROUPS.items():
        if k in norm:
            return v
    return norm


def normalize_ean(ean_str: str) -> str:
    digits = re.sub(r"\D", "", str(ean_str or ""))
    # Ignora EANs fictícios comuns (ex: 0000000000000, 1111111111111)
    if not digits or len(set(digits)) == 1:
        return ""
    if len(digits) in (8, 12, 13, 14):
        return digits
    return ""


# ── ESTRUTURAÇÃO DE PRODUTO ──

def build_product_summary(produto: dict | None) -> dict:
    if not produto:
        return {
            "exists": False,
            "mlb": "",
            "title": "",
            "status": "",
            "price": 0.0,
            "stock": 0,
            "brand": "",
            "model": "",
            "color": "",
            "color_raw": "",
            "voltage": "",
            "voltage_raw": "",
            "size": "",
            "size_raw": "",
            "ean": "",
            "image_count": 0,
            "image_main": "",
            "images": [],
            "listing_type": "",
            "shipping_type": "",
            "permalink": "",
        }

    attrs = _extract_attrs(produto)
    
    color_raw = attrs.get("COLOR") or attrs.get("MAIN_COLOR") or attrs.get("COLOUR") or ""
    voltage_raw = attrs.get("VOLTAGE") or ""
    size_raw = attrs.get("SIZE") or attrs.get("FILTRABLE_SIZE") or ""
    brand_raw = attrs.get("BRAND") or ""
    model_raw = attrs.get("MODEL") or ""
    ean_raw = attrs.get("GTIN") or attrs.get("EAN") or ""

    pictures = produto.get("pictures") or []
    image_urls = [p.get("secure_url") or p.get("url") for p in pictures if isinstance(p, dict) and (p.get("secure_url") or p.get("url"))]
    image_main = image_urls[0] if image_urls else (produto.get("thumbnail") or "")

    listing_type_id = produto.get("listing_type_id") or ""
    listing_type = LISTING_LABELS.get(listing_type_id, listing_type_id)

    shipping = produto.get("shipping") or {}
    logistic_type = shipping.get("logistic_type") or shipping.get("mode") or ""
    shipping_type = LOGISTIC_LABELS.get(logistic_type, logistic_type)

    sku = produto.get("seller_custom_field") or attrs.get("SELLER_SKU") or ""

    return {
        "exists": True,
        "sku": sku,
        "mlb": produto.get("id", ""),
        "title": produto.get("title", ""),
        "status": str(produto.get("status") or "active").lower(),
        "price": float(produto.get("price") or 0.0),
        "stock": int(produto.get("available_quantity") or 0),
        "brand": normalize_brand(brand_raw),
        "brand_raw": brand_raw,
        "model": _normalize_str(model_raw),
        "model_raw": model_raw,
        "color": normalize_color(color_raw),
        "color_raw": color_raw,
        "voltage": normalize_voltage(voltage_raw),
        "voltage_raw": voltage_raw,
        "size": normalize_size(size_raw),
        "size_raw": size_raw,
        "ean": normalize_ean(ean_raw),
        "image_count": len(image_urls),
        "image_main": image_main,
        "images": image_urls,
        "listing_type": listing_type,
        "shipping_type": shipping_type,
        "permalink": produto.get("permalink") or f"https://produto.mercadolivre.com.br/{produto.get('id', '')}",
        "catalog_listing": bool(produto.get("catalog_listing")),
    }


# ── MOTOR DE COMPARAÇÃO & CLASSIFICAÇÃO DE TRIAGEM ──

@dataclass
class TriageItem:
    item_id: str
    sku: str
    mlb_cat: str
    mlb_trad: str
    category: str  # HARD_MISMATCH | CLEAN_MATCH | SOFT_DIFF | INCOMPLETE
    category_label: str
    severity_score: int  # 0 a 100 (quanto maior, mais grave a divergência)
    hard_mismatches: list[str] = field(default_factory=list)
    soft_diffs: list[str] = field(default_factory=list)
    reasons_summary: str = ""
    cat_data: dict = field(default_factory=dict)
    trad_data: dict = field(default_factory=dict)
    field_diffs: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "sku": self.sku,
            "mlb_cat": self.mlb_cat,
            "mlb_trad": self.mlb_trad,
            "category": self.category,
            "category_label": self.category_label,
            "severity_score": self.severity_score,
            "hard_mismatches": self.hard_mismatches,
            "soft_diffs": self.soft_diffs,
            "reasons_summary": self.reasons_summary,
            "cat": self.cat_data,
            "trad": self.trad_data,
            "field_diffs": self.field_diffs,
        }


def evaluate_triage_pair(sku: str, cat_raw: dict | None, trad_raw: dict | None) -> TriageItem:
    cat = build_product_summary(cat_raw)
    trad = build_product_summary(trad_raw)

    cat_mlb = cat.get("mlb", "")
    trad_mlb = trad.get("mlb", "")
    item_id = f"{sku}_{cat_mlb}" if cat_mlb else (f"{sku}_{trad_mlb}" if trad_mlb else f"{sku}_na")

    if not cat.get("exists") and not trad.get("exists"):
        return TriageItem(
            item_id=item_id,
            sku=sku,
            mlb_cat="",
            mlb_trad="",
            category="INCOMPLETE",
            category_label="Não Encontrado",
            severity_score=90,
            hard_mismatches=["Nenhum anúncio encontrado no Mercado Livre para este item"],
            reasons_summary="Nenhum anúncio encontrado no Mercado Livre",
            cat_data=cat,
            trad_data=trad,
        )

    if not cat.get("exists"):
        return TriageItem(
            item_id=item_id,
            sku=sku,
            mlb_cat="",
            mlb_trad=trad_mlb,
            category="INCOMPLETE",
            category_label="Sem Catálogo",
            severity_score=60,
            hard_mismatches=["Anúncio de Catálogo ausente no ML"],
            reasons_summary="Anúncio de Catálogo AUSENTE no Mercado Livre",
            cat_data=cat,
            trad_data=trad,
        )

    if not trad.get("exists"):
        return TriageItem(
            item_id=item_id,
            sku=sku,
            mlb_cat=cat_mlb,
            mlb_trad="",
            category="INCOMPLETE",
            category_label="Sem Tradicional",
            severity_score=60,
            hard_mismatches=["Anúncio Tradicional (sem catálogo) ausente no ML"],
            reasons_summary="Anúncio Tradicional AUSENTE no Mercado Livre",
            cat_data=cat,
            trad_data=trad,
        )

    hard_mismatches: list[str] = []
    soft_diffs: list[str] = []
    field_diffs: dict[str, dict] = {}
    severity = 0

    # 1. Comparação de COR (Crítica)
    cat_color = cat.get("color", "")
    trad_color = trad.get("color", "")
    if cat_color and trad_color:
        if cat_color != trad_color:
            hard_mismatches.append(f"Cor incompatível: Catálogo '{cat.get('color_raw')}' ≠ Tradicional '{trad.get('color_raw')}'")
            severity += 40
            field_diffs["color"] = {"status": "HARD_MISMATCH", "cat": cat.get("color_raw"), "trad": trad.get("color_raw")}
        else:
            field_diffs["color"] = {"status": "MATCH", "cat": cat.get("color_raw"), "trad": trad.get("color_raw")}
    elif (cat_color or trad_color) and (cat.get("color_raw") != trad.get("color_raw")):
        soft_diffs.append(f"Cor preenchida em apenas um: Catálogo='{cat.get('color_raw')}' vs Trad='{trad.get('color_raw')}'")
        field_diffs["color"] = {"status": "MISSING_ONE", "cat": cat.get("color_raw"), "trad": trad.get("color_raw")}

    # 2. Comparação de VOLTAGEM (Crítica)
    cat_volt = cat.get("voltage", "")
    trad_volt = trad.get("voltage", "")
    if cat_volt not in ("", "N/A") and trad_volt not in ("", "N/A"):
        if (cat_volt == "110V" and trad_volt == "220V") or (cat_volt == "220V" and trad_volt == "110V"):
            hard_mismatches.append(f"Voltagem incompatível: Catálogo '{cat_volt}' ≠ Tradicional '{trad_volt}'")
            severity += 50
            field_diffs["voltage"] = {"status": "HARD_MISMATCH", "cat": cat_volt, "trad": trad_volt}
        elif cat_volt != trad_volt:
            soft_diffs.append(f"Voltagem divergente ({cat_volt} ≠ {trad_volt})")
            severity += 15
            field_diffs["voltage"] = {"status": "SOFT_DIFF", "cat": cat_volt, "trad": trad_volt}
        else:
            field_diffs["voltage"] = {"status": "MATCH", "cat": cat_volt, "trad": trad_volt}

    # 3. Comparação de MODELO (Crítica)
    cat_model = cat.get("model", "")
    trad_model = trad.get("model", "")
    if cat_model and trad_model:
        # Se ambos possuem modelos bem definidos e não são substrings
        if cat_model != trad_model and cat_model not in trad_model and trad_model not in cat_model:
            hard_mismatches.append(f"Modelo divergente: Catálogo '{cat.get('model_raw')}' ≠ Tradicional '{trad.get('model_raw')}'")
            severity += 35
            field_diffs["model"] = {"status": "HARD_MISMATCH", "cat": cat.get("model_raw"), "trad": trad.get("model_raw")}
        else:
            field_diffs["model"] = {"status": "MATCH", "cat": cat.get("model_raw"), "trad": trad.get("model_raw")}

    # 4. Comparação de MARCA (Crítica se totalmente diferente)
    cat_brand = cat.get("brand", "")
    trad_brand = trad.get("brand", "")
    if cat_brand and trad_brand:
        if cat_brand != trad_brand and cat_brand not in trad_brand and trad_brand not in cat_brand:
            hard_mismatches.append(f"Marca diferente: Catálogo '{cat.get('brand_raw')}' ≠ Tradicional '{trad.get('brand_raw')}'")
            severity += 30
            field_diffs["brand"] = {"status": "HARD_MISMATCH", "cat": cat.get("brand_raw"), "trad": trad.get("brand_raw")}
        else:
            field_diffs["brand"] = {"status": "MATCH", "cat": cat.get("brand_raw"), "trad": trad.get("brand_raw")}

    # 5. Comparação de TAMANHO (Crítica para Móveis/Colchões)
    cat_size = cat.get("size", "")
    trad_size = trad.get("size", "")
    if cat_size and trad_size:
        if cat_size != trad_size:
            hard_mismatches.append(f"Tamanho incompatível: Catálogo '{cat.get('size_raw')}' ≠ Tradicional '{trad.get('size_raw')}'")
            severity += 35
            field_diffs["size"] = {"status": "HARD_MISMATCH", "cat": cat.get("size_raw"), "trad": trad.get("size_raw")}
        else:
            field_diffs["size"] = {"status": "MATCH", "cat": cat.get("size_raw"), "trad": trad.get("size_raw")}

    # 6. Comparação de EAN / GTIN (Crítica se ambos válidos e divergentes)
    cat_ean = cat.get("ean", "")
    trad_ean = trad.get("ean", "")
    if cat_ean and trad_ean:
        if cat_ean != trad_ean:
            hard_mismatches.append(f"EAN/GTIN diferente: Catálogo '{cat_ean}' ≠ Tradicional '{trad_ean}'")
            severity += 25
            field_diffs["ean"] = {"status": "HARD_MISMATCH", "cat": cat_ean, "trad": trad_ean}
        else:
            field_diffs["ean"] = {"status": "MATCH", "cat": cat_ean, "trad": trad_ean}

    # 7. Comparação de FOTOS
    cat_imgs = cat.get("image_count", 0)
    trad_imgs = trad.get("image_count", 0)
    if abs(cat_imgs - trad_imgs) >= 3:
        soft_diffs.append(f"Qtd Fotos muito discrepante ({cat_imgs} fotos catálogo vs {trad_imgs} tradicional)")
        severity += 10
        field_diffs["photos"] = {"status": "SOFT_DIFF", "cat": str(cat_imgs), "trad": str(trad_imgs)}
    else:
        field_diffs["photos"] = {"status": "MATCH", "cat": str(cat_imgs), "trad": str(trad_imgs)}

    # 8. Comparação de STATUS
    if cat.get("status") != trad.get("status"):
        soft_diffs.append(f"Status diferente (Catálogo={cat.get('status')} | Trad={trad.get('status')})")
        field_diffs["status"] = {"status": "SOFT_DIFF", "cat": cat.get("status"), "trad": trad.get("status")}

    # Determinação da Categoria Final
    if hard_mismatches:
        category = "HARD_MISMATCH"
        category_label = "🔴 Descarte Imediato"
        reasons_summary = " | ".join(hard_mismatches)
        severity = min(max(severity, 60), 100)
    elif soft_diffs:
        category = "SOFT_DIFF"
        category_label = "⚠️ Divergência Leve"
        reasons_summary = " | ".join(soft_diffs)
        severity = min(severity, 40)
    else:
        category = "CLEAN_MATCH"
        category_label = "🟢 Apto / 100% Compatível"
        reasons_summary = "Atributos técnicos perfeitamente compatíveis"
        severity = 0

    return TriageItem(
        item_id=item_id,
        sku=sku,
        mlb_cat=cat_mlb,
        mlb_trad=trad_mlb,
        category=category,
        category_label=category_label,
        severity_score=severity,
        hard_mismatches=hard_mismatches,
        soft_diffs=soft_diffs,
        reasons_summary=reasons_summary,
        cat_data=cat,
        trad_data=trad,
        field_diffs=field_diffs,
    )


# ── RESOLUÇÃO DE SKUS/MLBS VIA BANCO OU API ──

def _resolve_skus_from_anymarket_db(skus: list[str]) -> dict[str, dict]:
    """Consulta réplica AnyMarket ou webhook n8n para mapear SKU -> MLBs."""
    sku_map: dict[str, dict] = {s: {"cat": [], "trad": []} for s in skus}
    if not skus:
        return sku_map

    # 1. Webhook n8n
    if ANYMARKET_SKU_WEBHOOK_URL:
        try:
            import requests as req
            resp = req.post(ANYMARKET_SKU_WEBHOOK_URL, json={"skus": skus}, timeout=25)
            if resp.status_code == 200:
                data = resp.json() or {}
                incoming = data.get("sku_map") or {}
                for k, v in incoming.items():
                    if k in sku_map:
                        sku_map[k] = v
                if any(sku_map[s]["cat"] or sku_map[s]["trad"] for s in skus):
                    return sku_map
        except Exception as exc:
            print(f"[N8N WEBHOOK] Erro: {exc}")

    # 2. Conexão direta PostgreSQL
    if ANYMARKET_DB_HOST and ANYMARKET_DB_USER:
        try:
            import psycopg2
            from psycopg2 import sql as psql
            with psycopg2.connect(
                host=ANYMARKET_DB_HOST,
                port=ANYMARKET_DB_PORT,
                dbname=ANYMARKET_DB_NAME,
                user=ANYMARKET_DB_USER,
                password=ANYMARKET_DB_PASSWORD,
                sslmode=ANYMARKET_DB_SSLMODE,
                connect_timeout=10,
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
                            is_cat = int(row[2] or 0) == 1
                            status = str(row[3] or "")
                            if s in sku_map and mlb.startswith("MLB"):
                                side = "cat" if is_cat else "trad"
                                if not any(m == mlb for m, _ in sku_map[s][side]):
                                    sku_map[s][side].append((mlb, status))
        except Exception as exc:
            print(f"[DB ANYMARKET] Erro: {exc}")

    return sku_map


def _resolve_mlbs_from_anymarket_db(mlbs: list[str]) -> dict[str, dict]:
    """Resolve MLBs -> SKU seller via réplica do AnyMarket."""
    sku_map: dict[str, dict] = {}
    if not mlbs:
        return sku_map

    if ANYMARKET_DB_HOST and ANYMARKET_DB_USER:
        try:
            import psycopg2
            from psycopg2 import sql as psql
            with psycopg2.connect(
                host=ANYMARKET_DB_HOST,
                port=ANYMARKET_DB_PORT,
                dbname=ANYMARKET_DB_NAME,
                user=ANYMARKET_DB_USER,
                password=ANYMARKET_DB_PASSWORD,
                sslmode=ANYMARKET_DB_SSLMODE,
                connect_timeout=10,
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
                        """).format(mlbs=placeholders)
                        cur.execute(query, batch)
                        for row in cur.fetchall():
                            s = str(row[0]).strip()
                            mlb = str(row[1]).strip().upper()
                            is_cat = int(row[2] or 0) == 1
                            status = str(row[3] or "")
                            if s not in sku_map:
                                sku_map[s] = {"cat": [], "trad": []}
                            side = "cat" if is_cat else "trad"
                            if not any(m == mlb for m, _ in sku_map[s][side]):
                                sku_map[s][side].append((mlb, status))
        except Exception as exc:
            print(f"[DB ANYMARKET] Erro ao resolver MLBs: {exc}")

    return sku_map


def run_batch_triage(
    inputs: list[str],
    token: str,
    progress_callback=None,
) -> dict:
    """
    Executa a triagem rápida para uma lista de SKUs ou MLBs.
    """
    clean_inputs = [x.strip() for x in inputs if x.strip()]
    seen = set()
    inputs_unique = []
    for x in clean_inputs:
        if x not in seen:
            seen.add(x)
            inputs_unique.append(x)

    if not inputs_unique:
        return {"items": [], "summary": {"total": 0, "hard_mismatch": 0, "clean_match": 0, "incomplete": 0, "soft_diff": 0}}

    sku_inputs = [x for x in inputs_unique if not x.upper().startswith("MLB")]
    mlb_inputs = [x.upper() for x in inputs_unique if x.upper().startswith("MLB")]

    if progress_callback:
        progress_callback(10, "Mapeando anúncios no banco de dados...")

    db_map = _resolve_skus_from_anymarket_db(sku_inputs)
    if mlb_inputs:
        mlb_db_map = _resolve_mlbs_from_anymarket_db(mlb_inputs)
        for k, v in mlb_db_map.items():
            if k not in db_map:
                db_map[k] = v
            else:
                for side in ("cat", "trad"):
                    for mlb_t in v[side]:
                        if not any(m == mlb_t[0] for m in [x[0] for x in db_map[k][side]]):
                            db_map[k][side].append(mlb_t)

    # Coletar todos os MLBs necessários para baixar em lote da API ML
    all_mlbs: set[str] = set(mlb_inputs)
    for _, slots in db_map.items():
        for m, _ in slots.get("cat", []):
            all_mlbs.add(m)
        for m, _ in slots.get("trad", []):
            all_mlbs.add(m)

    mlb_list = list(all_mlbs)
    produtos: dict[str, dict] = {}

    if progress_callback:
        progress_callback(30, f"Baixando detalhes de {len(mlb_list)} anúncios no Mercado Livre...")

    if mlb_list and token:
        batches = [mlb_list[i : i + BATCH_SIZE] for i in range(0, len(mlb_list), BATCH_SIZE)]
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = [pool.submit(get_products_batch, b, token) for b in batches]
            for f in as_completed(futures):
                try:
                    produtos.update(f.result() or {})
                except Exception as exc:
                    print(f"[API ERROR BATCH] {exc}")

    # Montar pares e executar a triagem
    if progress_callback:
        progress_callback(80, "Classificando divergências críticas...")

    triage_items: list[TriageItem] = []
    
    # Processa SKUs
    for sku in sku_inputs:
        slots = db_map.get(sku, {"cat": [], "trad": []})
        cats = slots.get("cat", [])
        trads = slots.get("trad", [])

        trad_mlb = trads[0][0] if trads else None
        trad_prod = produtos.get(trad_mlb) if trad_mlb else None

        if cats:
            for cat_tuple in cats:
                cat_mlb = cat_tuple[0]
                cat_prod = produtos.get(cat_mlb)
                item = evaluate_triage_pair(sku, cat_prod, trad_prod)
                triage_items.append(item)
        elif trads:
            item = evaluate_triage_pair(sku, None, trad_prod)
            triage_items.append(item)
        else:
            item = evaluate_triage_pair(sku, None, None)
            triage_items.append(item)

    # Processa MLBs avulsos que foram passados na entrada
    for mlb in mlb_inputs:
        # Se já foi coberto nos SKUs acima, pula
        if any(item.mlb_cat == mlb or item.mlb_trad == mlb for item in triage_items):
            continue
        prod = produtos.get(mlb)
        is_cat = bool(prod.get("catalog_listing")) if prod else False
        sku = (prod.get("seller_custom_field") if prod else "") or mlb

        # Procura par nos produtos já baixados se possível
        if is_cat:
            item = evaluate_triage_pair(sku, prod, None)
        else:
            item = evaluate_triage_pair(sku, None, prod)
        triage_items.append(item)

    # Estatísticas
    count_hard = sum(1 for x in triage_items if x.category == "HARD_MISMATCH")
    count_clean = sum(1 for x in triage_items if x.category == "CLEAN_MATCH")
    count_soft = sum(1 for x in triage_items if x.category == "SOFT_DIFF")
    count_inc = sum(1 for x in triage_items if x.category == "INCOMPLETE")

    if progress_callback:
        progress_callback(100, "Triagem concluída!")

    return {
        "items": [it.as_dict() for it in triage_items],
        "summary": {
            "total": len(triage_items),
            "hard_mismatch": count_hard,
            "clean_match": count_clean,
            "soft_diff": count_soft,
            "incomplete": count_inc,
        },
    }
