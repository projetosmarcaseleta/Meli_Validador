"""Integra preview.html (export estático) em templates/index.html (Flask/Jinja)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREVIEW = ROOT / "preview.html"
INDEX = ROOT / "templates" / "index.html"


def main() -> None:
    text = PREVIEW.read_text(encoding="utf-8")

    text = text.replace(
        'href="/static/logo.png"',
        'href="{{ url_for(\'static\', filename=\'logo.png\') }}"',
    )

    text = text.replace(
        '<div id="view-config" class="view-container" style="display: none;">',
        '<div id="view-config" class="view-container">',
        1,
    )
    text = text.replace(
        '<div id="view-audit" class="view-container" style="display: flex;">',
        '<div id="view-audit" class="view-container" style="display:none;">',
        1,
    )

    select_jinja = """<select id="input-client" aria-label="Clientes salvos no servidor" tabindex="0">
            {% for client in clients %}
            <option value="{{ client.id }}" {% if client.id == default_client_id %}selected{% endif %}>
              {{ client.name }}{% if client.platform %} · {{ client.platform }}{% endif %}
            </option>
            {% endfor %}
          </select>"""
    text = re.sub(
        r"<select id=\"input-client\"[^>]*>.*?</select>",
        select_jinja,
        text,
        count=1,
        flags=re.DOTALL,
    )

    text = re.sub(
        r'<div id="client-chip" class="token-status[^"]*"[^>]*>.*?</div>',
        '<div id="client-chip" class="token-status"></div>',
        text,
        count=1,
        flags=re.DOTALL,
    )
    text = re.sub(
        r'<div id="token-chip" class="token-status[^"]*"[^>]*>.*?</div>',
        '<div id="token-chip" class="token-status"></div>',
        text,
        count=1,
        flags=re.DOTALL,
    )
    text = re.sub(
        r'<div id="import-chip" class="token-status[^"]*"[^>]*>.*?</div>',
        '<div id="import-chip" class="token-status"></div>',
        text,
        count=1,
        flags=re.DOTALL,
    )

    text = re.sub(
        r'(<div id="items-list" style="display:flex; flex-direction:column; gap:5px;">).*?(</div>\s*</div>\s*\n\s*<!-- Detail Area -->)',
        r'\1\2',
        text,
        count=1,
        flags=re.DOTALL,
    )
    text = re.sub(
        r'<span id="sidebar-count">\d+</span>',
        '<span id="sidebar-count">0</span>',
        text,
        count=1,
    )

    text = re.sub(
        r"<tbody id=\"attributes-table-body\">.*?</tbody>",
        '<tbody id="attributes-table-body"></tbody>',
        text,
        count=1,
        flags=re.DOTALL,
    )

    text = re.sub(
        r'const SERVER_CLIENTS = \[.*?\];',
        "const SERVER_CLIENTS = {{ clients | default([]) | tojson }};",
        text,
        count=1,
        flags=re.DOTALL,
    )
    text = re.sub(
        r'const DEFAULT_CLIENT_ID = "[^"]*";',
        "const DEFAULT_CLIENT_ID = {{ default_client_id | default('seleta') | tojson }};",
        text,
        count=1,
    )

    url_map = [
        (
            "fetch(`/auditarcatalogo/api/clients/search?q=${encodeURIComponent(term)}`)",
            'fetch(`{{ url_for("api_clients_search") }}?q=${encodeURIComponent(term)}`)',
        ),
        (
            "fetch('/auditarcatalogo/api/clients/select'",
            'fetch(\'{{ url_for("api_clients_select") }}\'',
        ),
        (
            "fetch('/auditarcatalogo/api/import_spreadsheet'",
            'fetch(\'{{ url_for("api_import_spreadsheet") }}\'',
        ),
        (
            "fetch('/auditarcatalogo/api/refresh_token'",
            'fetch(\'{{ url_for("api_refresh_token") }}\'',
        ),
        (
            "fetch('/auditarcatalogo/api/validate_token'",
            'fetch(\'{{ url_for("api_validate_token") }}\'',
        ),
        (
            "fetch('/auditarcatalogo/api/audit'",
            'fetch(\'{{ url_for("api_audit") }}\'',
        ),
        (
            "fetch('/auditarcatalogo/api/export'",
            'fetch(\'{{ url_for("api_export") }}\'',
        ),
        (
            "fetch('/auditarcatalogo/api/validate-ads'",
            'fetch(\'{{ url_for("api_validate_ads") }}\'',
        ),
        (
            "fetch('/api/sync_google_sheet'",
            'fetch(\'{{ url_for("sync_google_sheet") }}\'',
        ),
        (
            "fetch('/auditarcatalogo/api/sync_google_sheet'",
            'fetch(\'{{ url_for("sync_google_sheet") }}\'',
        ),
    ]
    for old, new in url_map:
        text = text.replace(old, new)

    text = re.sub(
        r'<script type="module" src="https://static\.cloudflareinsights\.com.*?</script>\s*',
        "",
        text,
        flags=re.DOTALL,
    )

    # Limpa imagens/thumbs de demo na área de fotos
    for img_id in ("cat-main-img", "trad-main-img", "any-main-img"):
        text = re.sub(
            rf'(<img id="{img_id}"[^>]*)\ssrc="[^"]*"',
            r'\1 src=""',
            text,
            count=1,
        )
    for strip_id in ("cat-thumbs", "trad-thumbs", "any-thumbs"):
        text = re.sub(
            rf'(<div id="{strip_id}" class="thumbs-strip">).*?(</div>)',
            rf"\1\2",
            text,
            count=1,
            flags=re.DOTALL,
        )

    text = text.replace('id="prog-fill" class="fill" style="width: 100%;"', 'id="prog-fill" class="fill" style="width: 0%;"', 1)
    text = text.replace('id="prog-num" class="prog-pct">100%', 'id="prog-num" class="prog-pct">0%', 1)
    text = re.sub(
        r'<span id="prog-msg" class="prog-detail">Carregando auditoria\.\.\.</span>',
        '<span id="prog-msg" class="prog-detail"></span>',
        text,
        count=1,
    )

    if "{% for client in clients %}" not in text:
        raise RuntimeError("Bloco Jinja de clientes não encontrado após merge.")
    if '{{ url_for("api_audit") }}' not in text:
        raise RuntimeError("url_for api_audit não aplicado.")

    INDEX.write_text(text, encoding="utf-8", newline="\n")
    print(f"OK: {INDEX} ({INDEX.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
