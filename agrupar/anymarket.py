from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from agrupar.config import Settings

_TAMANHO_LOTE = 400


@dataclass(frozen=True)
class LinhaSkuMlb:
    sku: str
    mlb: str


def faltando_db(settings: Settings) -> list[str]:
    faltando: list[str] = []
    if not settings.anymarket_db_host.strip():
        faltando.append("ANYMARKET_DB_HOST — host do replica de leitura.")
    if not settings.anymarket_db_user.strip():
        faltando.append("ANYMARKET_DB_USER — usuário de leitura do Anymarket.")
    if not settings.anymarket_db_password:
        faltando.append("ANYMARKET_DB_PASSWORD — senha de leitura do Anymarket.")
    if not settings.anymarket_oi.strip():
        faltando.append("ANYMARKET_OI — identificador da conta (oi) no Anymarket.")
    return faltando


def selecionar_mlbs_do_sku(linhas: list[LinhaSkuMlb]) -> list[str]:
    mlbs: list[str] = []
    vistos: set[str] = set()
    for linha in linhas:
        mlb = linha.mlb.strip().upper()
        if not mlb.startswith("MLB") or mlb in vistos:
            continue
        vistos.add(mlb)
        mlbs.append(mlb)
    return mlbs


def agrupar_mlbs_por_sku(linhas: list[LinhaSkuMlb]) -> dict[str, list[str]]:
    por_sku: dict[str, list[LinhaSkuMlb]] = defaultdict(list)
    for linha in linhas:
        sku = str(linha.sku).strip()
        if sku:
            por_sku[sku].append(linha)
    return {sku: selecionar_mlbs_do_sku(grupo) for sku, grupo in por_sku.items()}


def _consultar_skus_sync(settings: Settings, skus: list[str]) -> list[LinhaSkuMlb]:
    import psycopg
    from psycopg import sql as psql

    linhas: list[LinhaSkuMlb] = []
    with psycopg.connect(
        host=settings.anymarket_db_host.strip(),
        port=settings.anymarket_db_port,
        dbname=settings.anymarket_db_name.strip() or "anymarket",
        user=settings.anymarket_db_user.strip(),
        password=settings.anymarket_db_password,
        sslmode=settings.anymarket_db_sslmode.strip() or "require",
        connect_timeout=20,
        autocommit=True,
    ) as conn:
        with conn.cursor() as cur:
            for inicio in range(0, len(skus), _TAMANHO_LOTE):
                lote = skus[inicio : inicio + _TAMANHO_LOTE]
                placeholders = psql.SQL(", ").join(psql.Placeholder() for _ in lote)
                consulta = psql.SQL(
                    """
                    SELECT DISTINCT
                        s.id_in_client,
                        sm.id_in_marketplace
                    FROM anymarket_prd.sku AS s
                    JOIN anymarket_prd.product AS p
                        ON p.id = s.id_product
                    JOIN anymarket_prd.sku_marketplace AS sm
                        ON sm.id_sku = s.id
                    WHERE s.oi = {oi}
                      AND sm.market_place = 'MERCADO_LIVRE'
                      AND sm.is_catalog = '0'
                      AND sm.status_in_marketplace <> 'closed'
                      AND s.id_in_client IN ({skus})
                    ORDER BY s.id_in_client, sm.id_in_marketplace
                    """
                ).format(oi=psql.Placeholder(), skus=placeholders)
                cur.execute(consulta, (settings.anymarket_oi.strip(), *lote))
                for sku, mlb in cur.fetchall():
                    if not sku or not mlb:
                        continue
                    linhas.append(
                        LinhaSkuMlb(
                            sku=str(sku).strip(),
                            mlb=str(mlb).strip().upper(),
                        )
                    )
    return linhas


async def buscar_linhas_por_skus(
    settings: Settings,
    skus: list[str],
) -> dict[str, Any]:
    if not skus:
        return {"ok": True, "data": []}
    faltantes = faltando_db(settings)
    if faltantes:
        return {
            "ok": False,
            "error": "Configuração do Anymarket ausente para resolver SKUs.",
            "faltando": faltantes,
        }

    unicos: list[str] = []
    vistos: set[str] = set()
    for sku in skus:
        valor = str(sku).strip()
        if not valor or valor in vistos:
            continue
        vistos.add(valor)
        unicos.append(valor)
    if not unicos:
        return {"ok": True, "data": []}

    try:
        import psycopg  # noqa: F401
    except ImportError:
        return {
            "ok": False,
            "error": "Dependência psycopg ausente. Instale com: pip install 'psycopg[binary]'.",
            "faltando": ["psycopg"],
        }

    try:
        linhas = await asyncio.to_thread(_consultar_skus_sync, settings, unicos)
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Falha ao consultar SKUs no Anymarket: {exc}",
            "faltando": [],
        }
    return {"ok": True, "data": linhas}
