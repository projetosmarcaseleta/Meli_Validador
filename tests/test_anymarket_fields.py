from anymarket_api import extract_anymarket_fields


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
