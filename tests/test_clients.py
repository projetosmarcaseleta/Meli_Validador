from unittest.mock import MagicMock, patch

from clients import get_client, get_default_client, list_clients, public_clients
from exporter import _resolve_skus_from_anymarket_db


def test_default_client_is_seleta_with_n8n_webhook(monkeypatch):
    monkeypatch.delenv("CLIENTS", raising=False)
    monkeypatch.delenv("CLIENT_SELETA_SKU_WEBHOOK_URL", raising=False)
    client = get_default_client()
    assert client.id == "seleta"
    assert client.sku_webhook_url.endswith("/webhook/consultar-skus-anymarket")
    public = public_clients()
    assert public[0]["id"] == "seleta"
    assert "gumga_token" not in public[0]
    assert public[0]["has_sku_webhook"] is True


def test_extra_client_from_env(monkeypatch):
    monkeypatch.setenv("CLIENTS", "seleta,magalu")
    monkeypatch.setenv("CLIENT_MAGALU_NAME", "Magazine Luiza")
    monkeypatch.setenv("CLIENT_MAGALU_PLATFORM", "MAGALU")
    monkeypatch.setenv("CLIENT_MAGALU_GUMGA_TOKEN", "TOKEN-MAGALU")
    monkeypatch.setenv("CLIENT_MAGALU_SKU_WEBHOOK_URL", "https://example.test/magalu")

    clients = list_clients()
    ids = [c.id for c in clients]
    assert ids == ["seleta", "magalu"]
    magalu = get_client("magalu")
    assert magalu is not None
    assert magalu.name == "Magazine Luiza"
    assert magalu.platform == "MAGALU"
    assert magalu.gumga_token == "TOKEN-MAGALU"
    assert magalu.sku_webhook_url == "https://example.test/magalu"


def test_unknown_client_falls_back_to_default():
    assert get_client("naoexiste") is None
    assert get_default_client().id == "seleta"


@patch("exporter.ANYMARKET_DB_HOST", "")
@patch("exporter.ANYMARKET_DB_USER", "")
@patch("requests.post")
def test_resolve_skus_uses_explicit_webhook_url(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "sku_map": {
            "238034500": {
                "cat": [{"mlb": "MLB5125868231", "status": "Ativo"}],
                "trad": [],
                "id_product": "7131999157",
                "sku_id": "128109841",
            }
        }
    }
    mock_post.return_value = mock_resp

    sku_map = _resolve_skus_from_anymarket_db(
        ["238034500"],
        webhook_url="https://example.test/client-hook",
        client_id="seleta",
        platform="SELETA",
    )
    assert sku_map["238034500"]["any_product_id"] == "7131999157"
    mock_post.assert_called_once()
    assert mock_post.call_args.args[0] == "https://example.test/client-hook"
    sent = mock_post.call_args.kwargs["json"]
    assert sent["skus"] == ["238034500"]
    assert sent["sku"] == "238034500"
    assert sent["client_id"] == "seleta"
    assert sent["platform"] == "SELETA"


@patch("exporter.ANYMARKET_DB_HOST", "")
@patch("exporter.ANYMARKET_DB_USER", "")
@patch("requests.post")
def test_webhook_sends_typed_sku_not_previous_one(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'{"sku_map":{}}'
    mock_resp.text = '{"sku_map":{}}'
    mock_resp.json.return_value = {"sku_map": {}}
    mock_post.return_value = mock_resp

    _resolve_skus_from_anymarket_db(
        ["1003742"],
        webhook_url="https://example.test/hook",
        client_id="support:259063586",
        platform="KABUM",
        oi="259063586.",
    )
    sent = mock_post.call_args.kwargs["json"]
    assert sent["skus"] == ["1003742"]
    assert sent["sku"] == "1003742"
    assert "228887000" not in sent["skus"]


@patch("exporter.ANYMARKET_DB_HOST", "")
@patch("exporter.ANYMARKET_DB_USER", "")
@patch("requests.post")
def test_empty_webhook_body_is_not_ok(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b""
    mock_resp.text = ""
    mock_post.return_value = mock_resp

    sku_map = _resolve_skus_from_anymarket_db(
        ["238034500"],
        webhook_url="https://example.test/empty",
    )
    assert sku_map["238034500"]["cat"] == []
    mock_post.assert_called_once()


@patch("app.validate_gumga_token", return_value={"valid": True})
@patch("app.get_gumga_token", return_value="ENV-GUMGA")
def test_client_credentials_prefers_env_gumga_over_support(mock_get_gumga, _mock_validate):
    from app import _client_credentials

    creds = _client_credentials({
        "client_id": "support:259063586",
        "client_name": "KABUM",
    })
    assert creds["gumga_token"] == "ENV-GUMGA"
    assert creds["any_platform"] == "SELETA"
    assert creds["backoffice_api_ok"] is True


def test_api_clients_hides_secrets():
    from app import app

    response = app.test_client().get("/api/clients")
    data = response.get_json()
    assert response.status_code == 200
    assert data["success"] is True
    assert data["default_id"] == "seleta"
    assert data["clients"]
    first = data["clients"][0]
    assert first["id"] == "seleta"
    assert "gumga_token" not in first
    assert "sku_webhook_url" not in first
