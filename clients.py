"""Registro de clientes AnyMarket / n8n (um token + webhook por conta)."""

from __future__ import annotations

from dataclasses import dataclass
import os
import re

from config import (
    ANYMARKET_OI,
    ANYMARKET_PLATFORM,
    ANYMARKET_SKU_WEBHOOK_URL,
    MELI_TOKEN_WEBHOOK_URL,
    SELETA_SKU_WEBHOOK_URL,
    get_gumga_token,
)

DEFAULT_CLIENT_ID = "seleta"

_CLIENT_ENV_RE = re.compile(r"^CLIENT_([A-Z0-9]+)_([A-Z0-9_]+)$")
_FIELD_MAP = {
    "NAME": "name",
    "PLATFORM": "platform",
    "GUMGA_TOKEN": "gumga_token",
    "SKU_WEBHOOK_URL": "sku_webhook_url",
    "MELI_TOKEN_WEBHOOK_URL": "meli_token_webhook_url",
    "OI": "oi",
}


@dataclass(frozen=True)
class ClientConfig:
    id: str
    name: str
    platform: str
    gumga_token: str = ""
    sku_webhook_url: str = ""
    meli_token_webhook_url: str = ""
    oi: str = ""
    meli_access_token: str = ""
    source: str = "env"
    marketplaces: tuple[str, ...] = ()
    backoffice_api_ok: bool = True

    def public_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "platform": self.platform,
            "oi": self.oi,
            "source": self.source,
            "has_gumga": bool(self.gumga_token),
            "has_sku_webhook": bool(self.sku_webhook_url),
            "has_meli_token_webhook": bool(self.meli_token_webhook_url),
            "has_ml": bool(self.meli_access_token),
            "marketplaces": list(self.marketplaces),
            "backoffice_api_ok": self.backoffice_api_ok,
        }


def _clean(value: str | None) -> str:
    return (value or "").strip().strip("'\"")


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").strip().lower())


def _default_seleta() -> ClientConfig:
    webhook = (
        _clean(os.environ.get("CLIENT_SELETA_SKU_WEBHOOK_URL"))
        or _clean(ANYMARKET_SKU_WEBHOOK_URL)
        or SELETA_SKU_WEBHOOK_URL
    )
    return ClientConfig(
        id="seleta",
        name=_clean(os.environ.get("CLIENT_SELETA_NAME")) or "Marca Seleta",
        platform=_clean(os.environ.get("CLIENT_SELETA_PLATFORM")) or _clean(ANYMARKET_PLATFORM) or "SELETA",
        gumga_token=_clean(os.environ.get("CLIENT_SELETA_GUMGA_TOKEN")) or get_gumga_token(),
        sku_webhook_url=webhook,
        meli_token_webhook_url=(
            _clean(os.environ.get("CLIENT_SELETA_MELI_TOKEN_WEBHOOK_URL"))
            or _clean(MELI_TOKEN_WEBHOOK_URL)
        ),
        oi=_clean(os.environ.get("CLIENT_SELETA_OI")) or _clean(ANYMARKET_OI),
    )


def _overrides_from_env() -> dict[str, dict]:
    found: dict[str, dict] = {}
    for key, raw in os.environ.items():
        match = _CLIENT_ENV_RE.match(key)
        if not match:
            continue
        field = _FIELD_MAP.get(match.group(2))
        if not field:
            continue
        client_id = match.group(1).lower()
        found.setdefault(client_id, {})[field] = _clean(raw)
    return found


def _merge(base: ClientConfig, override: dict) -> ClientConfig:
    data = {
        "id": base.id,
        "name": base.name,
        "platform": base.platform,
        "gumga_token": base.gumga_token,
        "sku_webhook_url": base.sku_webhook_url,
        "meli_token_webhook_url": base.meli_token_webhook_url,
        "oi": base.oi,
        "meli_access_token": base.meli_access_token,
        "source": base.source,
        "marketplaces": base.marketplaces,
        "backoffice_api_ok": base.backoffice_api_ok,
    }
    data.update({k: v for k, v in override.items() if v})
    return ClientConfig(**data)


def _extra_client(client_id: str, override: dict) -> ClientConfig:
    return ClientConfig(
        id=client_id,
        name=override.get("name") or client_id.replace("_", " ").title(),
        platform=override.get("platform") or client_id.upper(),
        gumga_token=override.get("gumga_token") or "",
        sku_webhook_url=override.get("sku_webhook_url") or "",
        meli_token_webhook_url=override.get("meli_token_webhook_url") or _clean(MELI_TOKEN_WEBHOOK_URL),
        oi=override.get("oi") or "",
    )


def list_clients() -> list[ClientConfig]:
    overrides = _overrides_from_env()
    default = _default_seleta()
    if "seleta" in overrides:
        default = _merge(default, overrides.pop("seleta"))

    by_id: dict[str, ClientConfig] = {"seleta": default}
    for client_id, override in overrides.items():
        by_id[client_id] = _extra_client(client_id, override)

    ordered_ids = [
        _slug(part)
        for part in _clean(os.environ.get("CLIENTS")).replace(";", ",").split(",")
        if _slug(part)
    ]
    if not ordered_ids:
        ordered_ids = ["seleta"] + [cid for cid in sorted(by_id) if cid != "seleta"]

    result: list[ClientConfig] = []
    seen: set[str] = set()
    for client_id in ordered_ids:
        client = by_id.get(client_id)
        if not client or client_id in seen:
            continue
        seen.add(client_id)
        result.append(client)
    for client_id, client in by_id.items():
        if client_id not in seen:
            result.append(client)
    return result


def get_default_client() -> ClientConfig:
    clients = list_clients()
    preferred = _slug(os.environ.get("CLIENT_DEFAULT_ID") or DEFAULT_CLIENT_ID)
    for client in clients:
        if client.id == preferred:
            return client
    return clients[0] if clients else _default_seleta()


def _client_from_support_payload(payload: dict) -> ClientConfig:
    return ClientConfig(
        id=str(payload.get("id") or "").strip(),
        name=str(payload.get("name") or "").strip(),
        platform=str(payload.get("platform") or "").strip(),
        gumga_token=str(payload.get("gumga_token") or "").strip(),
        sku_webhook_url=str(payload.get("sku_webhook_url") or "").strip(),
        meli_token_webhook_url=str(payload.get("meli_token_webhook_url") or "").strip(),
        oi=str(payload.get("oi") or "").strip(),
        meli_access_token=str(payload.get("meli_access_token") or "").strip(),
        source="support",
        marketplaces=tuple(payload.get("marketplaces") or ()),
        backoffice_api_ok=bool(payload.get("backoffice_api_ok", True)),
    )


def get_support_client(client_id: str | None, name: str = "") -> ClientConfig | None:
    from support_app import parse_support_oi, resolve_support_client

    if not parse_support_oi(client_id):
        return None
    result = resolve_support_client(client_id or "", name=name)
    if not result.get("ok"):
        return None
    return _client_from_support_payload(result.get("data") or {})


def get_client(client_id: str | None) -> ClientConfig | None:
    raw = str(client_id or "").strip()
    if not raw:
        return None
    support = get_support_client(raw)
    if support:
        return support
    wanted = _slug(raw)
    for client in list_clients():
        if client.id == wanted:
            return client
    return None


def public_clients() -> list[dict]:
    return [client.public_dict() for client in list_clients()]
