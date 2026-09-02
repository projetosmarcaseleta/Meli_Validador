from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agrupar.textos import normalizar_texto


@dataclass(frozen=True)
class Attr:
    id: str
    name: str | None = None
    value_id: str | None = None
    value_name: str | None = None
    values: list[dict[str, Any]] = field(default_factory=list)
    value_type: str | None = None


def _as_str(valor: object) -> str | None:
    if valor is None or valor == "":
        return None
    return str(valor)


def normalizar_attributes(attributes: object) -> dict[str, Attr]:
    resultado: dict[str, Attr] = {}
    if not attributes:
        return resultado

    if isinstance(attributes, list):
        pares = [(item.get("id"), item) for item in attributes if isinstance(item, dict)]
    elif isinstance(attributes, dict):
        pares = list(attributes.items())
    else:
        return resultado

    for raw_id, attr in pares:
        if not raw_id or not isinstance(attr, dict):
            continue
        attr_id = str(raw_id)
        resultado[attr_id] = Attr(
            id=attr_id,
            name=_as_str(attr.get("name")),
            value_id=_as_str(attr.get("value_id")),
            value_name=_as_str(attr.get("value_name")),
            values=attr.get("values") if isinstance(attr.get("values"), list) else [],
            value_type=_as_str(attr.get("value_type")),
        )
    return resultado


def nome_attr(attr: Attr | None) -> str | None:
    if attr is None:
        return None
    if attr.value_name:
        return attr.value_name.strip()
    if attr.values and attr.values[0].get("name"):
        return str(attr.values[0]["name"]).strip()
    return None


def id_attr(attr: Attr | None) -> str | None:
    if attr is None:
        return None
    if attr.value_id:
        return str(attr.value_id)
    if len(attr.values) == 1 and attr.values[0].get("id"):
        return str(attr.values[0]["id"])
    return None


def chave_attr(attr: Attr | None) -> str | None:
    if attr is None:
        return None
    value_id = id_attr(attr)
    if value_id:
        return f"ID:{value_id}"
    nome = normalizar_texto(nome_attr(attr))
    return f"NAME:{nome}" if nome else None


def _valor_preenchido(attr: Attr | None) -> bool:
    return bool(attr and (nome_attr(attr) or id_attr(attr)))


def mesclar_atributos_anuncio(payload: dict[str, Any]) -> dict[str, Attr]:
    destino = normalizar_attributes(payload.get("attributes"))
    extras: dict[str, list[dict[str, Any]]] = {}
    for variation in payload.get("variations") or []:
        if not isinstance(variation, dict):
            continue
        for chave in ("attribute_combinations", "attributes"):
            bloco = variation.get(chave)
            if not isinstance(bloco, list):
                continue
            for item in bloco:
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                extras.setdefault(str(item["id"]), []).append(item)
    for attr_id, itens in extras.items():
        if _valor_preenchido(destino.get(attr_id)):
            continue
        nomes: list[str] = []
        vistos: set[str] = set()
        value_id: str | None = None
        name: str | None = None
        for item in itens:
            attr = normalizar_attributes([item]).get(attr_id)
            if attr is None:
                continue
            if name is None:
                name = attr.name
            ident = id_attr(attr)
            if ident and value_id is None:
                value_id = ident
            nome = nome_attr(attr)
            if nome and nome not in vistos:
                vistos.add(nome)
                nomes.append(nome)
        if not nomes and not value_id:
            continue
        destino[attr_id] = Attr(
            id=attr_id,
            name=name,
            value_id=value_id if len(nomes) <= 1 else None,
            value_name=" / ".join(nomes) if nomes else None,
        )
    return destino


def payload_attr(attr_id: str, attr: Attr | None) -> dict[str, str] | None:
    if attr is None:
        return None
    value_id = id_attr(attr)
    if value_id:
        return {"id": attr_id, "value_id": value_id}
    value_name = nome_attr(attr)
    if value_name:
        return {"id": attr_id, "value_name": value_name}
    return None
