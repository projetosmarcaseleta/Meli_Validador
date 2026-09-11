from anymarket_api import _sku_lookup_candidates, extract_anymarket_fields


def test_sku_lookup_candidates_keep_leading_zeros():
    assert _sku_lookup_candidates("085865500")[0] == "085865500"
    assert "85865500" in _sku_lookup_candidates("085865500")


def test_extract_title_uses_sku_title_not_product_title():
    product = {
        "id": 10,
        "title": "Título do produto (pai)",
        "skus": [
            {"id": 1, "partnerId": "238601800", "title": "Título do SKU 127V", "ean": "789"},
            {"id": 2, "partnerId": "238601801", "title": "Título do SKU 220V", "ean": "790"},
        ],
    }
    fields = extract_anymarket_fields(product, sku_hint="238601800")
    assert fields["title"] == "Título do SKU 127V"
    assert fields["any_sku_id"] == "1"


def test_extract_title_falls_back_to_product_when_sku_has_no_title():
    product = {
        "id": 10,
        "title": "Título do produto",
        "skus": [{"id": 1, "partnerId": "SKU1", "ean": "123"}],
    }
    fields = extract_anymarket_fields(product, sku_hint="SKU1")
    assert fields["title"] == "Título do produto"


def test_extract_color_voltage_size_from_sku_variations_not_product_chars():
    product = {
        "id": 7132021646,
        "title": "Lavadora pai",
        "characteristics": [
            {"name": "Voltagem", "value": "110V"},
            {"name": "Cor", "value": "Branco"},
            {"name": "Tamanho", "value": "Único"},
        ],
        "skus": [
            {
                "id": 128103849,
                "partnerId": "240158200",
                "title": "SKU 110V",
                "variations": [
                    {"description": "Branco", "type": {"name": "color"}},
                    {"description": "110V", "type": {"name": "voltage"}},
                ],
            },
            {
                "id": 128118609,
                "partnerId": "240158300",
                "title": "SKU 220V",
                "variations": [
                    {"description": "Branco", "type": {"name": "color"}},
                    {"description": "220V", "type": {"name": "voltage"}},
                    {"description": "18kg", "type": {"name": "size"}},
                ],
            },
        ],
    }
    sku_110 = extract_anymarket_fields(product, sku_hint="240158200")
    assert sku_110["color"] == "Branco"
    assert sku_110["voltage"] == "110V"
    assert sku_110["size"] == ""

    sku_220 = extract_anymarket_fields(product, sku_hint="240158300")
    assert sku_220["color"] == "Branco"
    assert sku_220["voltage"] == "220V"
    assert sku_220["size"] == "18kg"


def test_extract_keeps_characteristic_that_only_contains_cor_as_substring():
    product = {
        "id": 1,
        "title": "Pai",
        "characteristics": [
            {"name": "Painel de Controle", "value": "Digital (Tact)"},
            {"name": "Cor", "value": "Branco"},
        ],
        "skus": [{"id": 1, "partnerId": "SKU1", "title": "SKU"}],
    }
    fields = extract_anymarket_fields(product, sku_hint="SKU1")
    assert fields["extra_attrs"]["painel de controle"]["value"] == "Digital (Tact)"
    assert "cor" not in fields["extra_attrs"]


def test_extract_description_model_and_extra_characteristics():
    product = {
        "id": 10,
        "title": "Pai",
        "description": "<p>Texto da descrição AnyMarket</p>",
        "characteristics": [
            {"name": "Modelo", "value": "BWF18AB"},
            {"name": "Capacidade de Lavagem", "value": "18kg"},
            {"name": "Potência", "value": "480W"},
            {"name": "Tipo de Lavadora", "value": "Automática"},
            {"name": "Destaques", "value": "<iframe src='x'></iframe>"},
        ],
        "skus": [{"id": 1, "partnerId": "SKU1", "title": "SKU", "ean": "123"}],
    }
    fields = extract_anymarket_fields(product, sku_hint="SKU1")
    assert fields["description"] == "Texto da descrição AnyMarket"
    assert fields["model"] == "BWF18AB"
    assert fields["capacity"] == "18kg"
    assert fields["power"] == "480W"
    assert "tipo de lavadora" in fields["extra_attrs"]
    assert fields["extra_attrs"]["tipo de lavadora"]["value"] == "Automática"
    assert "destaques" not in fields["extra_attrs"]


def test_extract_images_filter_by_sku_visual_variation():
    product = {
        "id": 1,
        "title": "Pai",
        "images": [
            {"url": "https://cdn.example/branco-1.jpg", "main": True, "index": 1, "variation": "Branco", "idVariation": 111},
            {"url": "https://cdn.example/branco-2.jpg", "main": False, "index": 2, "variation": "Branco", "idVariation": 111},
            {"url": "https://cdn.example/preto-1.jpg", "main": False, "index": 3, "variation": "Preto", "idVariation": 222},
        ],
        "skus": [
            {
                "id": 10,
                "partnerId": "SKU-BRANCO",
                "title": "SKU Branco",
                "variations": [
                    {"id": 111, "description": "Branco", "type": {"name": "color", "visualVariation": True}},
                    {"id": 333, "description": "110V", "type": {"name": "voltage", "visualVariation": False}},
                ],
            },
            {
                "id": 11,
                "partnerId": "SKU-PRETO",
                "title": "SKU Preto",
                "variations": [
                    {"id": 222, "description": "Preto", "type": {"name": "color", "visualVariation": True}},
                    {"id": 333, "description": "110V", "type": {"name": "voltage", "visualVariation": False}},
                ],
            },
        ],
    }
    branco = extract_anymarket_fields(product, sku_hint="SKU-BRANCO")
    assert branco["images_list"] == [
        "https://cdn.example/branco-1.jpg",
        "https://cdn.example/branco-2.jpg",
    ]
    preto = extract_anymarket_fields(product, sku_hint="SKU-PRETO")
    assert preto["images_list"] == ["https://cdn.example/preto-1.jpg"]


def test_extract_images_keep_all_when_sku_has_no_visual_variation():
    product = {
        "id": 1,
        "title": "Pai",
        "images": [
            {"url": "https://cdn.example/a.jpg", "main": True, "index": 1},
            {"url": "https://cdn.example/b.jpg", "main": False, "index": 2},
        ],
        "skus": [
            {
                "id": 10,
                "partnerId": "SKU-110",
                "title": "SKU 110V",
                "variations": [
                    {"id": 93, "description": "110V", "type": {"name": "voltage", "visualVariation": False}},
                ],
            }
        ],
    }
    fields = extract_anymarket_fields(product, sku_hint="SKU-110")
    assert fields["images_list"] == ["https://cdn.example/a.jpg", "https://cdn.example/b.jpg"]
