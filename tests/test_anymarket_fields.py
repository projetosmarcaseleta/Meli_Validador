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
