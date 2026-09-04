"""test_refresh_token.py – Extração e endpoint de renovação do token ML via n8n."""

from unittest.mock import MagicMock, patch

from n8n_token import extract_meli_token_from_payload, fetch_meli_token_from_n8n


SAMPLE_TOKEN = "APP_USR-000000000000000-000000-abcdef0123456789abcdef0123456789-0000000000"


def test_extract_token_from_n8n_list_api_key():
    payload = [{"api_key": SAMPLE_TOKEN}]
    assert extract_meli_token_from_payload(payload) == SAMPLE_TOKEN


def test_extract_token_from_nested_json():
    payload = {"json": {"access_token": SAMPLE_TOKEN}}
    assert extract_meli_token_from_payload(payload) == SAMPLE_TOKEN


def test_extract_token_empty_payload():
    assert extract_meli_token_from_payload({}) == ""
    assert extract_meli_token_from_payload([]) == ""
    assert extract_meli_token_from_payload(None) == ""


@patch("n8n_token.requests.post")
def test_fetch_meli_token_from_n8n_ok(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [{"api_key": SAMPLE_TOKEN}]
    mock_post.return_value = mock_resp

    result = fetch_meli_token_from_n8n("https://api.marcaseleta.shop/webhook/example")
    assert result["ok"] is True
    assert result["token"] == SAMPLE_TOKEN
    mock_post.assert_called_once()
    assert mock_post.call_args.kwargs["json"] == {}


@patch("n8n_token.requests.post")
def test_fetch_meli_token_from_n8n_404(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_post.return_value = mock_resp

    result = fetch_meli_token_from_n8n("https://api.marcaseleta.shop/webhook/example")
    assert result["ok"] is False
    assert "inativo" in result["error"].lower() or "webhook" in result["error"].lower()


@patch("app.validate_token")
@patch("app.fetch_meli_token_from_n8n")
def test_api_refresh_token_endpoint(mock_fetch, mock_validate):
    mock_fetch.return_value = {"ok": True, "token": SAMPLE_TOKEN}
    mock_validate.return_value = {"id": 3617093472, "nickname": "SELETA"}

    from app import app

    client = app.test_client()
    response = client.post("/api/refresh_token")
    data = response.get_json()

    assert response.status_code == 200
    assert data["success"] is True
    assert data["token"] == SAMPLE_TOKEN
    assert data["nickname"] == "SELETA"
    assert data["id"] == 3617093472
