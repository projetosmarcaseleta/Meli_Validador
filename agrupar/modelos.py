from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agrupar.atributos import Attr, nome_attr, mesclar_atributos_anuncio


@dataclass
class AnuncioOrigem:
    mlb: str
    sku: str | None = None
    nome_transmissao: str | None = None
    cor_banco: str | None = None
    genero_grupo: str = "NaoIdentificado"
    genero_origem: str = "nome_transmissao"
    fonte: str = "lote"


@dataclass
class ProdutoMeli:
    mlb: str
    title: str | None = None
    family_name: str | None = None
    family_id: Any = None
    user_product_id: str | None = None
    status: str | None = None
    sold_quantity: int = 0
    last_updated: str | None = None
    category_id: str | None = None
    domain_id: str | None = None
    seller_id: str | None = None
    condition: str | None = None
    attributes: dict[str, Attr] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    origem: AnuncioOrigem | None = None

    @classmethod
    def from_api(cls, payload: dict[str, Any], origem: AnuncioOrigem | None = None) -> ProdutoMeli | None:
        mlb = payload.get("id")
        if not mlb or not str(mlb).startswith("MLB"):
            return None
        return cls(
            mlb=str(mlb),
            title=payload.get("title"),
            family_name=payload.get("family_name"),
            family_id=payload.get("family_id"),
            user_product_id=_as_str(payload.get("user_product_id")),
            status=payload.get("status"),
            sold_quantity=int(payload.get("sold_quantity") or 0),
            last_updated=payload.get("last_updated"),
            category_id=payload.get("category_id"),
            domain_id=payload.get("domain_id"),
            seller_id=_as_str(payload.get("seller_id")),
            condition=payload.get("condition"),
            attributes=mesclar_atributos_anuncio(payload),
            raw=payload,
            origem=origem,
        )


def _as_str(valor: object) -> str | None:
    if valor is None or valor == "":
        return None
    return str(valor)


def valor_parent(produto: ProdutoMeli, attr_id: str) -> str | None:
    return nome_attr(produto.attributes.get(attr_id))
