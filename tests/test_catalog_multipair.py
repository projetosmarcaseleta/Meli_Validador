"""
test_catalog_multipair.py – Testes para pareamento de múltiplos catálogos por SKU
"""

import pytest
from unittest.mock import patch, MagicMock

import compare
import exporter


def test_build_catalog_audit_item_unique_id():
    cat = {"mlb": "MLB7523586708", "title": "Guarda-roupa", "status": "active"}
    trad = {"mlb": "MLB7520745830", "title": "Guarda-roupa", "status": "active"}
    
    item = compare.build_catalog_audit_item("241686700", cat, trad)
    assert item["item_id"] == "241686700_MLB7523586708"
    assert item["mlb_cat"] == "MLB7523586708"
    assert item["mlb_trad"] == "MLB7520745830"
    assert item["sku"] == "241686700"


def test_build_catalog_audit_item_missing_catalog():
    trad = {"mlb": "MLB7520745830", "title": "Guarda-roupa", "status": "active"}
    item = compare.build_catalog_audit_item("241686700", None, trad)
    assert item["item_id"] == "241686700_MLB7520745830"
    assert item["mlb_cat"] == ""
    assert item["mlb_trad"] == "MLB7520745830"
    assert item["status_geral"] == "ATENCAO"


def test_build_catalog_audit_item_includes_anymarket_by_sku():
    cat = {"mlb": "MLB1", "title": "Lavadora 127V", "brand": "Brastemp", "voltage": "127V", "ean": "123"}
    trad = {"mlb": "MLB2", "title": "Lavadora 110V", "brand": "Brastemp", "voltage": "110V", "ean": "123"}
    any_mkt = {
        "any_id": "999",
        "sku": "238601800",
        "title": "Lavadora Any",
        "brand": "Brastemp",
        "voltage": "127V",
        "ean": "123",
        "images_list": ["https://example.com/a.jpg"],
    }
    item = compare.build_catalog_audit_item("238601800", cat, trad, any_mkt)
    assert item["anymarket"]["any_id"] == "999"
    voltage = next(c for c in item["comparison"] if c["key"] == "voltage")
    assert voltage["any_mkt_value"] == "127V"
    assert voltage["any_value"] == "110V"
    assert voltage["status"] == "DIVERGENTE"
    assert any("VOLTAGEM" in d or "AnyMarket" in d for d in item["divergences"])


@patch("exporter.validate_token")
@patch("exporter._resolve_skus_from_anymarket_db")
@patch("exporter.get_products_batch")
def test_process_skus_for_catalog_audit_multiple_catalogs(mock_get_batch, mock_db, mock_token):
    mock_token.return_value = {"id": 12345, "nickname": "SELETA"}
    
    # Simula SKU 241686700 com 2 catálogos (MLB_CAT1, MLB_CAT2) e 1 tradicional (MLB_TRAD1)
    mock_db.return_value = {
        "241686700": {
            "cat": [("MLB7523586708", "active"), ("MLB7523623932", "active")],
            "trad": [("MLB7520745830", "active")],
        }
    }
    
    def fake_prod(mlb, is_cat):
        return {
            "id": mlb,
            "title": f"Produto {mlb}",
            "catalog_listing": is_cat,
            "status": "active",
            "price": 1499.90,
            "available_quantity": 25,
            "listing_type_id": "gold_pro" if is_cat else "gold_special",
            "shipping": {"mode": "me2", "logistic_type": "cross_docking"},
            "pictures": [{"url": f"https://httpbin.org/img/{mlb}.jpg"}],
            "attributes": [{"id": "BRAND", "value_name": "Henn"}],
        }

    mock_get_batch.return_value = {
        "MLB7523586708": fake_prod("MLB7523586708", True),
        "MLB7523623932": fake_prod("MLB7523623932", True),
        "MLB7520745830": fake_prod("MLB7520745830", False),
    }

    res = exporter.process_skus_for_catalog_audit(["241686700"], "FAKE_TOKEN", gumga_token="")
    items = res.get("items", [])
    
    # Deve gerar 2 itens de auditoria para o mesmo SKU!
    assert len(items) == 2
    assert res["summary"]["total"] == 2

    item1 = items[0]
    item2 = items[1]

    assert item1["sku"] == "241686700"
    assert item1["mlb_cat"] == "MLB7523586708"
    assert item1["mlb_trad"] == "MLB7520745830"
    assert item1["item_id"] == "241686700_MLB7523586708"

    assert item2["sku"] == "241686700"
    assert item2["mlb_cat"] == "MLB7523623932"
    assert item2["mlb_trad"] == "MLB7520745830"
    assert item2["item_id"] == "241686700_MLB7523623932"


def test_process_skus_for_catalog_excel_independent_decisions():
    items = [
        {
            "sku": "241686700",
            "item_id": "241686700_MLB7523586708",
            "mlb_cat": "MLB7523586708",
            "mlb_trad": "MLB7520745830",
            "status_geral": "DIVERGENTE",
            "divergences": ["Cor diferente"],
            "ml": {"status": "active", "price": "1499.90", "stock": "25", "title": "Catálogo 1"},
            "any": {"status": "active", "price": "1499.90", "stock": "25", "title": "Tradicional"},
        },
        {
            "sku": "241686700",
            "item_id": "241686700_MLB7523623932",
            "mlb_cat": "MLB7523623932",
            "mlb_trad": "MLB7520745830",
            "status_geral": "OK",
            "divergences": [],
            "ml": {"status": "active", "price": "1499.90", "stock": "25", "title": "Catálogo 2"},
            "any": {"status": "active", "price": "1499.90", "stock": "25", "title": "Tradicional"},
        },
    ]

    reviews = {
        "241686700_MLB7523586708": "REPROVADO",
        "241686700_MLB7523623932": "APROVADO",
    }

    # Exportar apenas Aprovados
    rows_app, _ = exporter.process_skus_for_catalog_excel(
        ["241686700"],
        "FAKE_TOKEN",
        reviews=reviews,
        filter_decision="approved",
        audit_items=items,
    )
    # Header + 1 linha (apenas o MLB7523623932)
    assert len(rows_app) == 2
    assert rows_app[1][1] == "MLB7523623932"
    assert rows_app[1][28] == "APROVADO"

    # Exportar apenas Reprovados
    rows_rej, _ = exporter.process_skus_for_catalog_excel(
        ["241686700"],
        "FAKE_TOKEN",
        reviews=reviews,
        filter_decision="rejected",
        audit_items=items,
    )
    # Header + 1 linha (apenas o MLB7523586708)
    assert len(rows_rej) == 2
    assert rows_rej[1][1] == "MLB7523586708"
    assert rows_rej[1][28] == "REPROVADO"
