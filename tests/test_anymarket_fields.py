from unittest.mock import MagicMock, patch

from anymarket_api import (
    _item_matches_sku,
    _product_id_from_listing,
    _sku_lookup_candidates,
    extract_anymarket_fields,
    find_product_by_ean,
    find_product_by_partner_id,
    get_product,
    get_product_sku,
    list_product_skus,
    load_product_for_sku_audit,
    merge_sku_into_product,
    resolve_product_by_marketplace_id,
)


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


def test_item_matches_sku_expands_leading_zeros():
    item = {"skus": [{"partnerId": "085865500"}]}
    assert _item_matches_sku(item, {"85865500", "085865500"})


def test_find_product_accepts_unique_sku_filter_without_nested_skus():
    class FakeResp:
        def __init__(self, payload, status=200):
            self.status_code = status
            self._payload = payload
            self.text = ""

        def json(self):
            return self._payload

    session = MagicMock()
    session.get.return_value = FakeResp({
        "content": [{"id": 7131999157, "title": "iPhone sem skus na listagem"}],
    })
    full = {
        "id": 7131999157,
        "title": "iPhone 15 256 Preto",
        "skus": [{"partnerId": "238834500", "title": "iPhone SKU"}],
    }
    with patch("anymarket_api._session", return_value=session), patch(
        "anymarket_api.get_product", return_value=full
    ):
        product = find_product_by_partner_id("238834500", "TOKEN", "SELETA")
    assert product["id"] == 7131999157
    assert product["skus"][0]["partnerId"] == "238834500"


def test_merge_sku_into_product_puts_specific_sku_first():
    product = {
        "id": 7131999157,
        "skus": [
            {"id": 1, "title": "Outra cor"},
            {"id": 128109841, "title": "Antigo"},
        ],
    }
    sku = {"id": 128109841, "title": "iPhone 15 256 Preto", "ean": "0195949036828"}
    merged = merge_sku_into_product(product, sku)
    assert merged["skus"][0]["title"] == "iPhone 15 256 Preto"
    assert [s["id"] for s in merged["skus"]] == [128109841, 1]


def test_get_product_calls_official_endpoint():
    class FakeResp:
        def __init__(self, payload, status=200):
            self.status_code = status
            self._payload = payload
            self.text = ""

        def json(self):
            return self._payload

        def raise_for_status(self):
            return None

    session = MagicMock()
    session.get.return_value = FakeResp({"id": 7131999157, "title": "Produto", "skus": []})
    with patch("anymarket_api._session", return_value=session):
        product = get_product("7131999157", "TOKEN", "SELETA")
    assert product["id"] == 7131999157
    args, _kwargs = session.get.call_args
    assert args[0].endswith("/products/7131999157")


def test_list_product_skus_calls_official_endpoint():
    class FakeResp:
        def __init__(self, payload, status=200):
            self.status_code = status
            self._payload = payload
            self.text = ""

        def json(self):
            return self._payload

        def raise_for_status(self):
            return None

    session = MagicMock()
    session.get.return_value = FakeResp([{"id": 1, "partnerId": "ABC"}])
    with patch("anymarket_api._session", return_value=session):
        skus = list_product_skus("7131999157", "TOKEN", "SELETA")
    assert len(skus) == 1
    args, _kwargs = session.get.call_args
    assert args[0].endswith("/products/7131999157/skus")


def test_load_product_for_sku_audit_uses_product_and_sku_paths():
    with patch("anymarket_api.get_product", return_value={"id": 10, "title": "P"}), patch(
        "anymarket_api.get_product_sku", return_value={"id": 99, "partnerId": "X"}
    ) as mock_sku:
        product, sid = load_product_for_sku_audit("TOKEN", "SELETA", product_id="10", sku_id="99")
    assert sid == "99"
    assert product["skus"][0]["id"] == 99
    mock_sku.assert_called_once()


def test_get_product_sku_calls_official_endpoint():
    class FakeResp:
        def __init__(self, payload, status=200):
            self.status_code = status
            self._payload = payload
            self.text = ""

        def json(self):
            return self._payload

        def raise_for_status(self):
            return None

    session = MagicMock()
    session.get.return_value = FakeResp({"id": 128109841, "title": "iPhone SKU", "partnerId": "MTPG3BR/A"})
    with patch("anymarket_api._session", return_value=session):
        sku = get_product_sku("7131999157", "128109841", "TOKEN", "SELETA")
    assert sku["id"] == 128109841
    assert sku["title"] == "iPhone SKU"
    args, kwargs = session.get.call_args
    assert args[0].endswith("/products/7131999157/skus/128109841")


def test_product_id_from_nested_listing():
    listing = {
        "idInMarketplace": "MLB5125868231",
        "sku": {"id": 128196441, "productId": 7131999157, "partnerId": "MTPG3BR/A"},
    }
    assert _product_id_from_listing(listing) == "7131999157"


def test_extract_selects_sku_by_ean_when_partner_id_differs():
    product = {
        "id": 10,
        "title": "Pai",
        "skus": [
            {"id": 1, "partnerId": "AAA", "title": "Outra cor", "ean": "111"},
            {"id": 2, "partnerId": "MTPG3BR/A", "title": "iPhone Preto", "ean": "0195949036828"},
        ],
    }
    fields = extract_anymarket_fields(product, sku_hint="238034500", ean_hint="0195949036828")
    assert fields["title"] == "iPhone Preto"
    assert fields["any_sku_id"] == "2"
    assert fields["ean"] == "0195949036828"


def test_resolve_product_by_marketplace_id_uses_listing_product_id():
    class FakeResp:
        def __init__(self, payload, status=200):
            self.status_code = status
            self._payload = payload
            self.text = ""

        def json(self):
            return self._payload

    session = MagicMock()
    session.get.return_value = FakeResp({
        "content": [{
            "idInMarketplace": "MLB5125868231",
            "productId": 7131999157,
            "skuId": 128196441,
        }],
    })
    full = {"id": 7131999157, "title": "iPhone Any"}
    with patch("anymarket_api._session", return_value=session), patch(
        "anymarket_api.get_product", return_value=full
    ):
        product, sku_id = resolve_product_by_marketplace_id("MLB5125868231", "TOKEN", "SELETA")
    assert product["id"] == 7131999157
    assert sku_id == "128196441"


def test_resolve_product_rejects_unrelated_first_listing():
    class FakeResp:
        def __init__(self, payload, status=200):
            self.status_code = status
            self._payload = payload
            self.text = ""

        def json(self):
            return self._payload

    session = MagicMock()
    session.get.return_value = FakeResp({
        "content": [{
            "idInMarketplace": "MLB0000000001",
            "productId": 111,
            "skuId": 222,
            "title": "Mousepad Gamer Husky",
        }],
    })
    with patch("anymarket_api._session", return_value=session), patch(
        "anymarket_api.get_product", return_value={"id": 111, "title": "Mousepad Gamer Husky"}
    ) as mock_get:
        product, sku_id = resolve_product_by_marketplace_id("MLB5125868231", "TOKEN", "SELETA")
    assert product == {}
    assert sku_id == ""
    mock_get.assert_not_called()


def test_find_product_by_ean_rejects_unrelated_first_page():
    class FakeResp:
        def __init__(self, payload, status=200):
            self.status_code = status
            self._payload = payload
            self.text = ""

        def json(self):
            return self._payload

    session = MagicMock()
    session.get.return_value = FakeResp({
        "content": [{"id": 111, "title": "Mousepad Gamer Husky", "ean": "789"}],
    })
    with patch("anymarket_api._session", return_value=session), patch(
        "anymarket_api.get_product", return_value={"id": 111, "title": "Mousepad", "skus": [{"ean": "789"}]}
    ):
        product, sku_id = find_product_by_ean("0195949036828", "TOKEN", "SELETA")
    assert product == {}
    assert sku_id == ""


def test_find_product_by_ean_loads_full_product():
    class FakeResp:
        def __init__(self, payload, status=200):
            self.status_code = status
            self._payload = payload
            self.text = ""

        def json(self):
            return self._payload

    session = MagicMock()
    session.get.return_value = FakeResp({
        "content": [{"id": 7131999157, "title": "iPhone listagem"}],
    })
    full = {
        "id": 7131999157,
        "title": "iPhone Any",
        "skus": [{"id": 2, "ean": "0195949036828", "title": "Preto"}],
    }
    with patch("anymarket_api._session", return_value=session), patch(
        "anymarket_api.get_product", return_value=full
    ):
        product, sku_id = find_product_by_ean("0195949036828", "TOKEN", "SELETA")
    assert product["id"] == 7131999157
    assert sku_id == "2"
