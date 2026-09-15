from unittest.mock import patch

from anymarket_auth import env_backoffice_override, resolve_backoffice_credentials


def test_env_backoffice_override(monkeypatch):
    monkeypatch.setenv("ANYMARKET_GUMGA_OI_259063586", "TOKEN-OI")
    monkeypatch.setenv("ANYMARKET_PLATFORM_OI_259063586", "KABUM-API")
    gumga, platform = env_backoffice_override("259063586.")
    assert gumga == "TOKEN-OI"
    assert platform == "KABUM-API"


@patch("anymarket_auth.validate_gumga_token")
def test_resolve_backoffice_picks_working_platform(mock_validate):
    mock_validate.side_effect = lambda _token, platform: {"valid": platform == "SELETA"}
    gumga, platform, ok = resolve_backoffice_credentials(
        "RAW",
        "KABUM",
        oi="259063586.",
        display_name="KABUM",
    )
    assert ok is True
    assert gumga == "RAW"
    assert platform == "SELETA"


@patch("anymarket_auth.validate_gumga_token", return_value={"valid": False, "error": "User not registered"})
def test_resolve_backoffice_none_valid(mock_validate):
    gumga, platform, ok = resolve_backoffice_credentials(
        "RAW",
        "KABUM",
        oi="259063586.",
        display_name="KABUM",
    )
    assert ok is False
    assert gumga == "RAW"
    assert platform
