"""
test_triage_engine.py – Testes unitários do motor de triagem do Meli_Triagem
"""

import pytest
import triage_engine
import exporter


def test_color_normalization():
    assert triage_engine.normalize_color("Branco Brilhante") == "branco"
    assert triage_engine.normalize_color("Cinza Fendi") == "cinza"
    assert triage_engine.normalize_color("Preto Fosco") == "preto"
    assert triage_engine.normalize_color("Freijó") == "amadeirado"
    assert triage_engine.normalize_color("Off White") == "off_white"


def test_voltage_normalization():
    assert triage_engine.normalize_voltage("110V") == "110V"
    assert triage_engine.normalize_voltage("127V") == "110V"
    assert triage_engine.normalize_voltage("220V") == "220V"
    assert triage_engine.normalize_voltage("Bivolt Automático") == "BIVOLT"
    assert triage_engine.normalize_voltage("Não se aplica") == "N/A"


def test_hard_mismatch_color():
    cat = {
        "id": "MLB7523586708",
        "title": "Guarda-roupa Branco",
        "attributes": [
            {"id": "COLOR", "value_name": "Branco"},
            {"id": "BRAND", "value_name": "Henn"},
            {"id": "MODEL", "value_name": "HN-I113-05"},
        ],
    }
    trad = {
        "id": "MLB7520745830",
        "title": "Guarda-roupa Cinza",
        "attributes": [
            {"id": "COLOR", "value_name": "Cinza"},
            {"id": "BRAND", "value_name": "Móveis Henn"},
            {"id": "MODEL", "value_name": "HN-I113-05"},
        ],
    }

    item = triage_engine.evaluate_triage_pair("241686700", cat, trad)
    assert item.category == "HARD_MISMATCH"
    assert any("Cor incompatível" in r for r in item.hard_mismatches)


def test_hard_mismatch_voltage():
    cat = {
        "id": "MLB111",
        "title": "Air Fryer 110V",
        "attributes": [
            {"id": "VOLTAGE", "value_name": "110V"},
            {"id": "BRAND", "value_name": "Mondial"},
            {"id": "MODEL", "value_name": "AFN-40"},
        ],
    }
    trad = {
        "id": "MLB222",
        "title": "Air Fryer 220V",
        "attributes": [
            {"id": "VOLTAGE", "value_name": "220V"},
            {"id": "BRAND", "value_name": "Mondial"},
            {"id": "MODEL", "value_name": "AFN-40"},
        ],
    }

    item = triage_engine.evaluate_triage_pair("SKU_AIRFRYER", cat, trad)
    assert item.category == "HARD_MISMATCH"
    assert any("Voltagem incompatível" in r for r in item.hard_mismatches)


def test_clean_match():
    cat = {
        "id": "MLB111",
        "title": "Cadeira Gamer Preta",
        "status": "active",
        "price": 599.90,
        "attributes": [
            {"id": "COLOR", "value_name": "Preto"},
            {"id": "BRAND", "value_name": "ThunderX3"},
            {"id": "MODEL", "value_name": "TGC12"},
        ],
    }
    trad = {
        "id": "MLB222",
        "title": "Cadeira Gamer Preta TGC12",
        "status": "active",
        "price": 599.90,
        "attributes": [
            {"id": "COLOR", "value_name": "Preto"},
            {"id": "BRAND", "value_name": "ThunderX3"},
            {"id": "MODEL", "value_name": "TGC12"},
        ],
    }

    item = triage_engine.evaluate_triage_pair("SKU_CHAIR", cat, trad)
    assert item.category == "CLEAN_MATCH"
    assert len(item.hard_mismatches) == 0


def test_export_excel():
    items = [
        {
            "item_id": "SKU1_MLB1",
            "sku": "SKU1",
            "mlb_cat": "MLB1",
            "mlb_trad": "MLB2",
            "category": "HARD_MISMATCH",
            "category_label": "🔴 Descarte Imediato",
            "reasons_summary": "Cor incompatível: Branco ≠ Preto",
            "cat": {"color_raw": "Branco", "title": "Cat 1"},
            "trad": {"color_raw": "Preto", "title": "Trad 1"},
        },
        {
            "item_id": "SKU2_MLB3",
            "sku": "SKU2",
            "mlb_cat": "MLB3",
            "mlb_trad": "MLB4",
            "category": "CLEAN_MATCH",
            "category_label": "🟢 Apto",
            "reasons_summary": "Atributos compatíveis",
            "cat": {"color_raw": "Preto", "title": "Cat 2"},
            "trad": {"color_raw": "Preto", "title": "Trad 2"},
        },
    ]

    buf = exporter.generate_triage_excel(items, filter_category="all")
    assert buf is not None
    assert buf.getvalue()[:2] == b"PK"  # Zip/Excel signature
