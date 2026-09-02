from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from agrupar.meli import MeliClient, MeliError
from agrupar.modelos import AnuncioOrigem, ProdutoMeli

MAX_IRMAOS = 400
_UPS_POR_BUSCA = 15
_LIMITE_BUSCA = 50


def site_id_de_produtos(produtos: list[ProdutoMeli]) -> str:
    for produto in produtos:
        if produto.category_id:
            return str(produto.category_id)[:3]
        if produto.mlb:
            return str(produto.mlb)[:3]
    return "MLB"


def extrair_user_product_ids(payload: dict[str, Any]) -> list[str]:
    bruto = payload.get("user_products_ids") or payload.get("user_product_ids") or []
    if not isinstance(bruto, list):
        return []
    saida: list[str] = []
    vistos: set[str] = set()
    for item in bruto:
        valor = str(item).strip() if item is not None else ""
        if not valor or valor in vistos:
            continue
        vistos.add(valor)
        saida.append(valor)
    return saida


def extrair_mlbs_busca(payload: dict[str, Any]) -> tuple[list[str], int]:
    results = payload.get("results") or []
    mlbs: list[str] = []
    if isinstance(results, list):
        for item in results:
            if isinstance(item, str) and item.startswith("MLB"):
                mlbs.append(item)
            elif isinstance(item, dict):
                ident = str(item.get("id") or "")
                if ident.startswith("MLB"):
                    mlbs.append(ident)
    paging = payload.get("paging") if isinstance(payload.get("paging"), dict) else {}
    total = int(paging.get("total") or len(mlbs))
    return mlbs, total


def _chunk(valores: list[str], tamanho: int) -> list[list[str]]:
    return [valores[i : i + tamanho] for i in range(0, len(valores), tamanho)]


async def _ups_da_familia(
    client: MeliClient,
    family_id: str,
    site_id: str,
) -> tuple[list[str], str | None]:
    seller_id: str | None = None
    try:
        site = await client.get_site_family(site_id, str(family_id))
        seller = site.get("user_id")
        if seller is not None and str(seller).strip():
            seller_id = str(seller)
        ups = extrair_user_product_ids(site)
        if ups:
            return ups, seller_id
    except MeliError:
        pass
    try:
        variantes = await client.get_family_user_products(str(family_id))
        return extrair_user_product_ids(variantes), seller_id
    except MeliError:
        return [], seller_id


async def _mlbs_dos_ups(
    client: MeliClient,
    seller_id: str,
    user_product_ids: list[str],
) -> list[str]:
    encontrados: list[str] = []
    vistos: set[str] = set()
    for lote_ups in _chunk(sorted(set(user_product_ids)), _UPS_POR_BUSCA):
        offset = 0
        while True:
            try:
                payload = await client.search_items_by_user_products(
                    seller_id,
                    lote_ups,
                    offset=offset,
                    limit=_LIMITE_BUSCA,
                )
            except MeliError:
                break
            mlbs, total = extrair_mlbs_busca(payload)
            for mlb in mlbs:
                if mlb in vistos:
                    continue
                vistos.add(mlb)
                encontrados.append(mlb)
            if not mlbs or offset + len(mlbs) >= total:
                break
            offset += len(mlbs)
    return encontrados


async def expandir_irmaos(
    client: MeliClient,
    produtos: list[ProdutoMeli],
) -> tuple[list[AnuncioOrigem], list[str]]:
    """Um salto: UPs da família + itens desses UPs que não estavam no lote."""
    avisos: list[str] = []
    if not produtos:
        return [], avisos

    conhecidos = {p.mlb for p in produtos}
    site_id = site_id_de_produtos(produtos)
    ups_por_seller: dict[str, set[str]] = defaultdict(set)

    for produto in produtos:
        if produto.seller_id and produto.user_product_id:
            ups_por_seller[str(produto.seller_id)].add(produto.user_product_id)

    family_ids = sorted(
        {str(p.family_id) for p in produtos if p.family_id not in (None, "")}
    )
    familias = await asyncio.gather(
        *(_ups_da_familia(client, family_id, site_id) for family_id in family_ids)
    )
    for ups, seller_familia in familias:
        if not ups:
            continue
        if seller_familia:
            ups_por_seller[seller_familia].update(ups)
            continue
        if len(ups_por_seller) == 1:
            unico = next(iter(ups_por_seller))
            ups_por_seller[unico].update(ups)

    mlbs_novos: list[str] = []
    vistos_novos: set[str] = set()
    sellers = sorted(ups_por_seller.items())
    resultados_sellers = await asyncio.gather(
        *(
            _mlbs_dos_ups(client, seller_id, sorted(ups))
            for seller_id, ups in sellers
        )
    )
    for mlbs_encontrados in resultados_sellers:
        for mlb in mlbs_encontrados:
            if mlb in conhecidos or mlb in vistos_novos:
                continue
            vistos_novos.add(mlb)
            mlbs_novos.append(mlb)
            if len(mlbs_novos) >= MAX_IRMAOS:
                avisos.append(
                    f"Expansão de irmãos limitada a {MAX_IRMAOS} MLBs extras."
                )
                break
        if len(mlbs_novos) >= MAX_IRMAOS:
            break

    origens = [
        AnuncioOrigem(
            mlb=mlb,
            genero_grupo="NaoIdentificado",
            genero_origem="irmao",
            fonte="irmao",
        )
        for mlb in mlbs_novos
    ]
    return origens, avisos
