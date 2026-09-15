from unittest.mock import patch

from n8n_client import client_webhook_configured, search_clients_via_n8n


@patch("n8n_client.ANYMARKET_CLIENT_WEBHOOK_URL", "")
def test_client_webhook_not_configured():
    assert client_webhook_configured() is False
    result = search_clients_via_n8n("259063586")
    assert result["ok"] is False


@patch("n8n_client.post_n8n_webhook")
@patch("n8n_client.ANYMARKET_CLIENT_WEBHOOK_URL", "https://example.test/hook")
def test_search_clients_via_n8n(mock_post):
    mock_post.return_value = {
        "success": True,
        "clients": [{"id": "support:259063586", "name": "KABUM", "oi": "259063586.", "active": True}],
    }
    result = search_clients_via_n8n("Kabum")
    assert result["ok"] is True
    assert result["data"][0]["id"] == "support:259063586"
    mock_post.assert_called_once()
    assert mock_post.call_args[0][1]["action"] == "search"
