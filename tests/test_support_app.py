from unittest.mock import patch

from support_app import parse_support_oi, resolve_support_client, search_organizations, support_client_id


def test_support_ids():
    assert support_client_id("259063586.") == "support:259063586"
    assert parse_support_oi("support:259063586") == "259063586."
    assert parse_support_oi("259063586.") == "259063586."
    assert parse_support_oi("seleta") == ""


@patch("support_app.get_support_token", return_value="TOKEN")
@patch("support_app.requests.get")
def test_search_organizations_filters_duplicates(mock_get, _mock_token):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = [
        {"id": 1, "hierarchyCode": "259063586.", "name": "KABUM", "active": True, "value": "secret"},
        {"id": 1, "hierarchyCode": "259063586.", "name": "KABUM", "active": True, "value": "secret"},
        {"id": 2, "hierarchyCode": "259050728.", "name": "FAST SHOP - KABUM", "active": True},
    ]
    result = search_organizations("Kabum")
    assert result["ok"] is True
    assert {item["id"] for item in result["data"]} == {"support:259063586", "support:259050728"}
    assert "value" not in result["data"][0]
    assert "secret" not in str(result["data"])
    path = mock_get.call_args.args[0]
    assert path.endswith("/advancedSearch/Kabum")


@patch("anymarket_auth.validate_gumga_token", return_value={"valid": False, "error": "User not registered"})
@patch("support_app.get_support_token", return_value="TOKEN")
@patch("support_app.requests.get")
def test_resolve_support_client_reads_marketplaces(mock_get, _mock_token, _mock_validate):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = [
        {"integration": "GUMGA", "api_key": "GUMGA-KEY", "active": "ATIVADO"},
        {"integration": "MERCADO LIVRE", "api_key": "APP_USR-ML", "active": "ATIVADO"},
        {"integration": "AMAZON", "api_key": "AMZ", "active": "ATIVADO"},
    ]
    result = resolve_support_client("support:259063586", name="KABUM")
    assert result["ok"] is True
    data = result["data"]
    assert data["id"] == "support:259063586"
    assert data["oi"] == "259063586."
    assert data["platform"] == "KABUM"
    assert data["gumga_token"] == "GUMGA-KEY"
    assert data["meli_access_token"] == "APP_USR-ML"
    assert "AMAZON" in data["marketplaces"]
    assert data["backoffice_api_ok"] is False
    path = mock_get.call_args.args[0]
    assert path.endswith("/advancedSearch/marketplaces/259063586.")


@patch("support_app.resolve_support_client")
def test_api_clients_select_does_not_expose_gumga(mock_resolve):
    mock_resolve.return_value = {
        "ok": True,
        "data": {
            "id": "support:259063586",
            "name": "KABUM",
            "platform": "KABUM",
            "gumga_token": "GUMGA-KEY",
            "sku_webhook_url": "https://example.test/hook",
            "meli_token_webhook_url": "",
            "oi": "259063586.",
            "meli_access_token": "APP_USR-ML",
            "marketplaces": ["GUMGA", "MERCADO LIVRE"],
        },
    }
    from app import app

    response = app.test_client().post(
        "/api/clients/select",
        json={"client_id": "support:259063586", "client_name": "KABUM"},
    )
    data = response.get_json()
    assert response.status_code == 200
    assert data["success"] is True
    assert data["meli_token"] == "APP_USR-ML"
    assert data["client"]["id"] == "support:259063586"
    assert "gumga_token" not in data["client"]
    assert "GUMGA-KEY" not in str(data["client"])
