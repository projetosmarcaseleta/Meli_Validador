"""
import_parser.py – Lê planilha de cruzamento AnyMarket × Mercado Livre.

Colunas esperadas: ID_SKU | ID_PRODUCT | ID_SKU_MARKETPLACE | title | MLB
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass

import openpyxl

REQUIRED_COLUMNS = ("ID_SKU", "ID_PRODUCT", "ID_SKU_MARKETPLACE", "title", "MLB")

COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "ID_SKU": ("id_sku", "idsku", "sku_id", "id sku"),
    "ID_PRODUCT": ("id_product", "idproduct", "product_id", "id produto", "id produto anymarket"),
    "ID_SKU_MARKETPLACE": (
        "id_sku_marketplace",
        "idskumarketplace",
        "sku_marketplace_id",
        "id sku marketplace",
        "id_mlb",
    ),
    "title": ("titulo", "título", "titulo_produto", "product_title"),
    "MLB": ("mlb", "id_mlb", "codigo_mlb", "listing_id"),
}


@dataclass(frozen=True)
class ImportRow:
    id_sku: str
    id_product: str
    id_sku_marketplace: str
    title: str
    mlb: str

    def as_dict(self) -> dict[str, str]:
        return {
            "id_sku": self.id_sku,
            "id_product": self.id_product,
            "id_sku_marketplace": self.id_sku_marketplace,
            "title": self.title,
            "mlb": self.mlb,
        }


def _normalize_header(value: str) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("í", "i").replace("ó", "o").replace("ã", "a").replace("ç", "c")
    text = re.sub(r"[\s\-_]+", "_", text)
    return text.strip("_")


def _resolve_column(header: str) -> str | None:
    norm = _normalize_header(header)
    for canonical, aliases in COLUMN_ALIASES.items():
        if norm == _normalize_header(canonical) or norm in {_normalize_header(a) for a in aliases}:
            return canonical
    return None


def _normalize_mlb(value: str) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    if not text.startswith("MLB"):
        digits = re.sub(r"\D", "", text)
        if digits:
            text = f"MLB{digits}"
    return text if re.fullmatch(r"MLB\d+", text) else ""


def _cell_str(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _rows_from_matrix(matrix: list[list]) -> tuple[list[ImportRow], list[str]]:
    if not matrix:
        return [], ["Planilha vazia."]

    header_row_idx = 0
    mapping: dict[str, int] = {}

    for idx, row in enumerate(matrix[:20]):
        temp: dict[str, int] = {}
        for col_idx, cell in enumerate(row):
            canonical = _resolve_column(_cell_str(cell))
            if canonical and canonical not in temp:
                temp[canonical] = col_idx
        if "MLB" in temp and "ID_PRODUCT" in temp:
            header_row_idx = idx
            mapping = temp
            break

    if not mapping:
        return [], [
            "Cabeçalho não encontrado. Use as colunas: "
            + ", ".join(REQUIRED_COLUMNS)
        ]

    missing = [col for col in REQUIRED_COLUMNS if col not in mapping]
    if missing:
        return [], [f"Colunas ausentes: {', '.join(missing)}"]

    rows: list[ImportRow] = []
    errors: list[str] = []
    seen_mlb: set[str] = set()

    for line_no, row in enumerate(matrix[header_row_idx + 1 :], start=header_row_idx + 2):
        if not row or all(_cell_str(c) == "" for c in row):
            continue

        mlb = _normalize_mlb(_cell_str(row[mapping["MLB"]]))
        if not mlb:
            errors.append(f"Linha {line_no}: MLB inválido ou vazio.")
            continue
        if mlb in seen_mlb:
            errors.append(f"Linha {line_no}: MLB duplicado ({mlb}).")
            continue
        seen_mlb.add(mlb)

        rows.append(
            ImportRow(
                id_sku=_cell_str(row[mapping["ID_SKU"]]),
                id_product=_cell_str(row[mapping["ID_PRODUCT"]]),
                id_sku_marketplace=_normalize_mlb(_cell_str(row[mapping["ID_SKU_MARKETPLACE"]]))
                or _cell_str(row[mapping["ID_SKU_MARKETPLACE"]]),
                title=_cell_str(row[mapping["title"]]),
                mlb=mlb,
            )
        )

    if not rows:
        return [], errors or ["Nenhuma linha válida encontrada na planilha."]

    return rows, errors


def parse_spreadsheet(filename: str, content: bytes) -> tuple[list[ImportRow], list[str]]:
    name = (filename or "").lower()
    if name.endswith(".csv"):
        text = content.decode("utf-8-sig", errors="replace")
        reader = csv.reader(io.StringIO(text))
        matrix = [list(row) for row in reader]
        return _rows_from_matrix(matrix)

    if name.endswith((".xlsx", ".xlsm", ".xltx", ".xltm")):
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        matrix = [[cell for cell in row] for row in ws.iter_rows(values_only=True)]
        wb.close()
        return _rows_from_matrix(matrix)

    return [], ["Formato não suportado. Use .xlsx ou .csv."]
