from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Awaitable

from agrupar.anymarket import agrupar_mlbs_por_sku, buscar_linhas_por_skus
from agrupar.config import Settings
from agrupar.logs import OnLog, emitir
from agrupar.modelos import AnuncioOrigem

_SPLIT = re.compile(r"[\s,;]+")
_MLB = re.compile(r"^MLB\d+$")
_SKU = re.compile(r"^(?=.*\d)[A-Za-z0-9._-]+$")

BuscarSkus = Callable[[Settings, list[str]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class EntradaLote:
    mlbs: list[str]
    skus: list[str]

    @property
    def vazia(self) -> bool:
        return not self.mlbs and not self.skus


def parse_mlbs(*blocos: str) -> list[str]:
    return parse_entrada(*blocos).mlbs


def parse_entrada(*blocos: str) -> EntradaLote:
    mlbs: list[str] = []
    skus: list[str] = []
    vistos_mlb: set[str] = set()
    vistos_sku: set[str] = set()
    for bloco in blocos:
        for linha in bloco.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            sem_comentario = linha.split("#", 1)[0]
            for token in _SPLIT.split(sem_comentario):
                bruto = token.strip()
                if not bruto:
                    continue
                mlb = bruto.upper()
                if _MLB.fullmatch(mlb):
                    if mlb not in vistos_mlb:
                        vistos_mlb.add(mlb)
                        mlbs.append(mlb)
                    continue
                if _SKU.fullmatch(bruto) and bruto not in vistos_sku:
                    vistos_sku.add(bruto)
                    skus.append(bruto)
    return EntradaLote(mlbs=mlbs, skus=skus)


def ler_mlbs_arquivo(caminho: Path) -> list[str]:
    if not caminho.exists():
        return []
    return parse_mlbs(caminho.read_text(encoding="utf-8"))


def ler_entrada_arquivo(caminho: Path) -> EntradaLote:
    if not caminho.exists():
        return EntradaLote(mlbs=[], skus=[])
    return parse_entrada(caminho.read_text(encoding="utf-8"))


def _origem(mlb: str, sku: str | None, fonte: str) -> AnuncioOrigem:
    return AnuncioOrigem(
        mlb=mlb,
        sku=sku,
        genero_grupo="NaoIdentificado",
        genero_origem="pendente_meli",
        fonte=fonte,
    )


def carregar_origem(
    settings: Settings,
    mlbs_cli: list[str] | None = None,
) -> list[AnuncioOrigem]:
    mlbs = parse_mlbs(*mlbs_cli) if mlbs_cli is not None else ler_mlbs_arquivo(settings.mlbs_file)
    return [_origem(mlb, None, "mlb") for mlb in mlbs]


def _fonte(tem_mlb: bool, tem_sku: bool) -> str:
    if tem_mlb and tem_sku:
        return "misto"
    if tem_sku:
        return "skus_anymarket"
    return "lista_mlbs"


async def resolver_origem(
    settings: Settings,
    blocos: list[str] | None = None,
    on_log: OnLog = None,
    buscar_skus: BuscarSkus = buscar_linhas_por_skus,
) -> dict[str, Any]:
    entrada = parse_entrada(*blocos) if blocos is not None else ler_entrada_arquivo(settings.mlbs_file)
    if entrada.vazia:
        return {
            "ok": False,
            "error": "Nenhum MLB ou SKU para processar.",
            "faltando": [
                "Cole MLBs (MLB123...) e/ou SKUs na tela, passe na linha de comando, "
                "ou grave um por linha em data/mlbs.txt."
            ],
            "origens": [],
            "fonte_origem": "lista_mlbs",
            "skus_nao_encontrados": [],
            "avisos": [],
        }

    origens: list[AnuncioOrigem] = []
    vistos: set[str] = set()
    avisos: list[str] = []
    skus_nao_encontrados: list[str] = []
    mlbs_de_sku = 0

    for mlb in entrada.mlbs:
        if mlb in vistos:
            continue
        vistos.add(mlb)
        origens.append(_origem(mlb, None, "mlb"))

    if entrada.skus:
        emitir(
            on_log,
            "info",
            f"Resolvendo {len(entrada.skus)} SKU(s) no Anymarket...",
        )
        consulta = await buscar_skus(settings, entrada.skus)
        if not consulta.get("ok"):
            return {
                "ok": False,
                "error": consulta.get("error") or "Falha ao resolver SKUs no Anymarket.",
                "faltando": consulta.get("faltando") or [],
                "origens": [],
                "fonte_origem": _fonte(bool(entrada.mlbs), True),
                "skus_nao_encontrados": entrada.skus,
                "avisos": [],
            }

        por_sku = agrupar_mlbs_por_sku(consulta.get("data") or [])
        for sku in entrada.skus:
            mlbs = por_sku.get(sku) or []
            if not mlbs:
                skus_nao_encontrados.append(sku)
                continue
            for mlb in mlbs:
                mlbs_de_sku += 1
                if mlb in vistos:
                    continue
                vistos.add(mlb)
                origens.append(_origem(mlb, sku, "sku"))

        encontrados = len(entrada.skus) - len(skus_nao_encontrados)
        emitir(
            on_log,
            "ok" if encontrados else "error",
            (
                f"{encontrados} SKU(s) viraram {len([o for o in origens if o.fonte == 'sku'])} "
                f"MLB(s) únicos no Anymarket."
            ),
        )
        if skus_nao_encontrados:
            amostra = ", ".join(skus_nao_encontrados[:12])
            extra = f" +{len(skus_nao_encontrados) - 12}" if len(skus_nao_encontrados) > 12 else ""
            aviso = f"{len(skus_nao_encontrados)} SKU(s) sem anúncio ML: {amostra}{extra}."
            avisos.append(aviso)
            emitir(on_log, "warn", aviso)

    if not origens:
        if skus_nao_encontrados:
            return {
                "ok": False,
                "error": "Nenhum SKU da lista tem anúncio no Mercado Livre.",
                "faltando": [
                    "Confira os SKUs, o ANYMARKET_OI e se os anúncios estão no marketplace MERCADO_LIVRE."
                ],
                "origens": [],
                "fonte_origem": _fonte(bool(entrada.mlbs), bool(entrada.skus)),
                "skus_nao_encontrados": skus_nao_encontrados,
                "avisos": avisos,
            }
        return {
            "ok": False,
            "error": "Nenhum MLB ou SKU para processar.",
            "faltando": [
                "Cole MLBs (MLB123...) e/ou SKUs na tela, passe na linha de comando, "
                "ou grave um por linha em data/mlbs.txt."
            ],
            "origens": [],
            "fonte_origem": "lista_mlbs",
            "skus_nao_encontrados": [],
            "avisos": avisos,
        }

    return {
        "ok": True,
        "origens": origens,
        "fonte_origem": _fonte(bool(entrada.mlbs), bool(entrada.skus)),
        "skus_nao_encontrados": skus_nao_encontrados,
        "avisos": avisos,
        "total_skus": len(entrada.skus),
        "total_mlbs_de_sku": len([o for o in origens if o.fonte == "sku"]),
        "mlbs_mapeados": mlbs_de_sku,
    }
