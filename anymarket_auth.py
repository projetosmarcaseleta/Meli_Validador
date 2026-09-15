"""Resolve gumgaToken + platform válidos para a API Backoffice v2."""

from __future__ import annotations

import os
import re

from anymarket_api import validate_gumga_token
from config import ANYMARKET_PLATFORM

_OI_DIGITS = re.compile(r"^(\d+)")


def _oi_digits(oi: str | None) -> str:
    raw = str(oi or "").strip().rstrip(".")
    match = _OI_DIGITS.match(raw)
    return match.group(1) if match else ""


def env_backoffice_override(oi: str | None) -> tuple[str, str]:
    """ANYMARKET_GUMGA_OI_<oi> e ANYMARKET_PLATFORM_OI_<oi> no .env."""
    digits = _oi_digits(oi)
    if not digits:
        return "", ""
    gumga = (os.environ.get(f"ANYMARKET_GUMGA_OI_{digits}") or "").strip()
    platform = (os.environ.get(f"ANYMARKET_PLATFORM_OI_{digits}") or "").strip()
    return gumga, platform


def _platform_candidates(oi: str | None, display_name: str, preferred: str = "") -> list[str]:
    seen: set[str] = set()
    out: list[str] = []

    def add(value: str) -> None:
        clean = (value or "").strip()
        if not clean or clean in seen:
            return
        seen.add(clean)
        out.append(clean)

    add(preferred)
    add(env_backoffice_override(oi)[1])
    digits = _oi_digits(oi)
    if digits:
        add(digits)
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", (display_name or "").upper())
    add(cleaned)
    add(ANYMARKET_PLATFORM or "SELETA")
    return out


def resolve_backoffice_credentials(
    gumga_token: str,
    platform: str,
    oi: str | None = None,
    display_name: str = "",
) -> tuple[str, str, bool]:
    """
    Retorna (gumga_token, platform, api_ok).
    api_ok=True quando validate_gumga_token passou em algum platform candidato.
    """
    env_gumga, env_platform = env_backoffice_override(oi)
    token = (env_gumga or gumga_token or "").strip()
    if not token:
        return "", (env_platform or platform or ANYMARKET_PLATFORM or "SELETA").strip(), False

    for candidate in _platform_candidates(oi, display_name, env_platform or platform):
        result = validate_gumga_token(token, candidate)
        if result.get("valid"):
            return token, candidate, True

    fallback = (env_platform or platform or _platform_candidates(oi, display_name)[0]).strip()
    return token, fallback, False
