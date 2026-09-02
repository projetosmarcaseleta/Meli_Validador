from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agrupar.atributos import nome_attr
from agrupar.logs import detalhe_erro_api
from agrupar.modelos import ProdutoMeli
from agrupar.plano import (
    CHILD_PK,
    PARENT_PK_EDITAVEIS,
    PARENT_PK_READ_ONLY,
    PlanoCluster,
    PutPlanejado,
    montar_quase_familias,
)
from agrupar.textos import normalizar_texto

PARENT_PK_TODOS = PARENT_PK_EDITAVEIS + PARENT_PK_READ_ONLY


def _attr_nome(produto: ProdutoMeli, attr_id: str) -> str | None:
    return nome_attr(produto.attributes.get(attr_id))


def _mapa_pk(produto: ProdutoMeli | None, ids: tuple[str, ...]) -> dict[str, str]:
    if produto is None:
        return {attr_id: "" for attr_id in ids}
    return {attr_id: _attr_nome(produto, attr_id) or "" for attr_id in ids}


def snapshot_antes(produtos: list[ProdutoMeli]) -> list[dict[str, Any]]:
    saida = []
    for produto in produtos:
        origem = produto.origem
        saida.append(
            {
                "mlb": produto.mlb,
                "sku": origem.sku if origem else produto.raw.get("seller_custom_field"),
                "nome_transmissao": origem.nome_transmissao if origem else None,
                "genero_grupo": origem.genero_grupo if origem else None,
                "title_antes": produto.title,
                "family_id_antes": produto.family_id,
                "family_name_antes": produto.family_name,
                "user_product_id_antes": produto.user_product_id,
                "status_antes": produto.status,
                "sold_quantity_antes": produto.sold_quantity,
                "fonte": origem.fonte if origem else "lote",
                "category_id": produto.category_id,
                "domain_id": produto.domain_id,
                "seller_id": produto.seller_id,
                "color_antes": _attr_nome(produto, "COLOR"),
                "size_antes": _attr_nome(produto, "SIZE"),
                "gender_antes": _attr_nome(produto, "GENDER"),
                "model_antes": _attr_nome(produto, "MODEL"),
                "alphanumeric_model_antes": _attr_nome(produto, "ALPHANUMERIC_MODEL"),
                "parent_pk": _mapa_pk(produto, PARENT_PK_TODOS),
                "child_pk": _mapa_pk(produto, CHILD_PK),
            }
        )
    return saida


def _chave_familia(registro: dict[str, Any], fase: str) -> str:
    campo = "family_id_antes" if fase == "antes" else "family_id_depois"
    family = registro.get(campo)
    if family not in (None, ""):
        return str(family)
    return f"SEM_FAMILIA:{registro['mlb']}"


def _grupos(registros: list[dict[str, Any]], fase: str) -> list[dict[str, Any]]:
    mapa: dict[str, dict[str, Any]] = {}
    for registro in registros:
        chave = _chave_familia(registro, fase)
        if chave not in mapa:
            mapa[chave] = {
                "family_id": None if chave.startswith("SEM_FAMILIA:") else chave,
                "sem_family_id": chave.startswith("SEM_FAMILIA:"),
                "quantidade_produtos": 0,
                "mlbs": [],
                "skus": [],
                "generos": set(),
                "family_names": set(),
                "user_product_ids": set(),
                "cores": set(),
                "tamanhos": set(),
                "familias_origem": set(),
            }
        grupo = mapa[chave]
        grupo["quantidade_produtos"] += 1
        grupo["mlbs"].append(registro["mlb"])
        if registro.get("sku"):
            grupo["skus"].append(registro["sku"])
        if registro.get("genero_grupo"):
            grupo["generos"].add(registro["genero_grupo"])
        fname = registro.get("family_name_antes" if fase == "antes" else "family_name_depois")
        if fname:
            grupo["family_names"].add(fname)
        up = registro.get("user_product_id_antes" if fase == "antes" else "user_product_id_depois")
        if up:
            grupo["user_product_ids"].add(up)
        if registro.get("color"):
            grupo["cores"].add(registro["color"])
        if registro.get("size"):
            grupo["tamanhos"].add(registro["size"])
        if fase == "depois":
            grupo["familias_origem"].add(_chave_familia(registro, "antes"))

    saida = []
    for grupo in mapa.values():
        item = {
            "family_id": grupo["family_id"],
            "sem_family_id": grupo["sem_family_id"],
            "quantidade_produtos": grupo["quantidade_produtos"],
            "mlbs": sorted(grupo["mlbs"]),
            "skus": sorted(set(grupo["skus"])),
            "generos": sorted(grupo["generos"]),
            "family_names": list(grupo["family_names"]),
            "user_product_ids": sorted(grupo["user_product_ids"]),
            "cores": sorted(grupo["cores"]),
            "tamanhos": sorted(grupo["tamanhos"]),
        }
        if fase == "depois":
            origens = [
                None if x.startswith("SEM_FAMILIA:") else x for x in grupo["familias_origem"]
            ]
            item["family_ids_origem"] = origens
            item["quantidade_familias_origem"] = len(grupo["familias_origem"])
        saida.append(item)
    saida.sort(key=lambda g: g["quantidade_produtos"], reverse=True)
    return saida


def montar_relatorio(
    produtos_antes: list[ProdutoMeli],
    produtos_depois: list[ProdutoMeli] | None,
    planos: list[PlanoCluster],
    resultados_put: list[dict[str, Any]],
    dry_run: bool,
    poll: dict[str, Any] | None = None,
) -> dict[str, Any]:
    antes = snapshot_antes(produtos_antes)
    depois_por_mlb = {
        p.mlb: p for p in (produtos_depois or []) if p.mlb
    }
    comparacao = []
    for registro in antes:
        mlb = registro["mlb"]
        depois = depois_por_mlb.get(mlb)
        color = _attr_nome(depois, "COLOR") if depois else registro.get("color_antes")
        size = _attr_nome(depois, "SIZE") if depois else registro.get("size_antes")
        family_depois = depois.family_id if depois else None
        up_depois = depois.user_product_id if depois else None
        family_name_depois = depois.family_name if depois else None
        gender_depois = _attr_nome(depois, "GENDER") if depois else None
        revalidou = depois is not None
        comparacao.append(
            {
                **registro,
                "color": color,
                "size": size,
                "family_id_depois": family_depois,
                "family_name_depois": family_name_depois,
                "gender_depois": gender_depois,
                "user_product_id_depois": up_depois,
                "family_id_mudou": revalidou
                and str(registro.get("family_id_antes") or "") != str(family_depois or ""),
                "family_name_mudou": revalidou
                and normalizar_texto(registro.get("family_name_antes"))
                != normalizar_texto(family_name_depois),
                "gender_mudou": revalidou
                and (registro.get("gender_antes") or "") != (gender_depois or ""),
                "user_product_id_mudou": revalidou
                and str(registro.get("user_product_id_antes") or "") != str(up_depois or ""),
                "revalidacao_ok": revalidou,
                "status_depois": depois.status if depois else None,
                "last_updated_depois": depois.last_updated if depois else None,
            }
        )

    grupos_antes = _grupos(comparacao, "antes")
    grupos_depois = _grupos(comparacao, "depois") if produtos_depois else grupos_antes
    total_antes = len(grupos_antes)
    total_depois = len(grupos_depois)
    reducao = total_antes - total_depois
    percentual = round((reducao / total_antes) * 100, 2) if total_antes else 0
    fusoes = [
        {
            "family_id_depois": g["family_id"],
            "quantidade_produtos": g["quantidade_produtos"],
            "quantidade_familias_unificadas": g["quantidade_familias_origem"],
            "family_ids_antes": g["family_ids_origem"],
            "mlbs": g["mlbs"],
            "skus": g["skus"],
        }
        for g in grupos_depois
        if g.get("quantidade_familias_origem", 0) > 1
    ]
    migracoes = [r for r in comparacao if r["family_id_mudou"]]
    sem_revalidacao = [r for r in comparacao if not r["revalidacao_ok"]]

    por_genero = []
    for genero in sorted({r.get("genero_grupo") for r in comparacao if r.get("genero_grupo")}):
        rs = [r for r in comparacao if r.get("genero_grupo") == genero]
        ga = _grupos(rs, "antes")
        gd = _grupos(rs, "depois") if produtos_depois else ga
        por_genero.append(
            {
                "genero": genero,
                "total_produtos": len(rs),
                "familias_antes": len(ga),
                "familias_depois": len(gd),
                "reducao_familias": len(ga) - len(gd),
                "produtos_que_mudaram_de_familia": sum(1 for r in rs if r["family_id_mudou"]),
            }
        )

    status = "DRY_RUN" if dry_run else "SEM_ALTERACAO"
    if not dry_run and produtos_depois:
        if total_depois < total_antes:
            status = "MELHOROU"
        elif total_depois > total_antes:
            status = "PIOROU"

    resumo = (
        f"{len(comparacao)} produtos estavam em {total_antes} família(s) antes. "
        f"Depois ficaram em {total_depois}. Redução: {reducao}."
    )
    quase = montar_quase_familias(produtos_depois or produtos_antes)
    detalhe_mlbs = montar_detalhe_mlbs(comparacao, resultados_put)
    listagem = montar_listagem_family_name(detalhe_mlbs)
    fluxos = _fluxos_family_id(detalhe_mlbs)
    return {
        "relatorio": "AGRUPAMENTO_MERCADO_LIVRE",
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "status_agrupamento": status,
        "resumo": resumo,
        "total_produtos": len(comparacao),
        "antes": {"total_familias": total_antes, "grupos": grupos_antes},
        "depois": {"total_familias": total_depois, "grupos": grupos_depois},
        "resultado": {
            "reducao_familias": reducao,
            "percentual_reducao_familias": percentual,
            "total_produtos_que_mudaram_de_familia": len(migracoes),
            "total_fusoes_detectadas": len(fusoes),
            "fusoes_detectadas": fusoes,
            "por_genero": por_genero,
            "fluxos_family_id": fluxos,
            "total_puts": len(resultados_put),
            "puts_ok": sum(1 for p in resultados_put if p.get("status") == "ok"),
            "puts_erro": sum(1 for p in resultados_put if p.get("status") == "erro"),
            "puts_planejado": sum(1 for p in resultados_put if p.get("status") == "planejado"),
        },
        "quase_familias": quase,
        "listagem_family_name": listagem,
        "detalhe_mlbs": detalhe_mlbs,
        "poll": poll,
        "migracoes": migracoes,
        "revalidacao": {
            "total_reconsultados_com_sucesso": len(comparacao) - len(sem_revalidacao),
            "total_sem_resposta_valida": len(sem_revalidacao),
            "mlbs_sem_resposta_valida": [r["mlb"] for r in sem_revalidacao],
        },
        "puts": resultados_put,
        "planos": [_plano_publico(p) for p in planos],
        "observacao": (
            "family_id é a unidade de agrupamento. A revalidação faz poll até o "
            "family_id mudar ou estourar REVALIDACAO_SEGUNDOS. "
            "quase_familias lista splits só de texto (gênero/Confortável) para o seller center."
        ),
    }


def _plano_publico(plano: PlanoCluster) -> dict[str, Any]:
    return {
        "genero_alvo": plano.genero_alvo,
        "cluster_id": plano.cluster_id,
        "total_produtos": len(plano.produtos),
        "mlbs": [p.mlb for p in plano.produtos],
        "family_name_referencia": plano.family_name_referencia,
        "parent_pk_referencia": plano.parent_pk_referencia,
        "total_puts_parent_pk": len(plano.puts_parent_pk),
        "total_puts_family_name": len(plano.puts_family_name),
        "total_puts_familia": len(plano.puts_familia),
        "bloqueios_estruturais": plano.bloqueios_estruturais,
        "quase_familias": plano.quase_familias,
        "puts_parent_pk": [_put_publico(p) for p in plano.puts_parent_pk],
        "puts_family_name": [_put_publico(p) for p in plano.puts_family_name],
        "puts_familia": [_put_publico(p) for p in plano.puts_familia],
        "diagnosticos": [d.payload | {"request_type": d.request_type} for d in plano.diagnosticos],
    }


def _put_publico(put: PutPlanejado) -> dict[str, Any]:
    return {
        "request_type": put.request_type,
        "mlb": put.mlb,
        "user_product_id": put.user_product_id,
        "url": put.url,
        "body": put.body,
        **put.extra,
    }


def achatar_relatorio(relatorio: dict[str, Any]) -> list[dict[str, Any]]:
    """Corrige o bug do n8n: lê antes.grupos / depois.grupos, não .familias."""
    linhas: list[dict[str, Any]] = []
    base_vazio = {
        "family_id_antes": "",
        "family_id_depois": "",
        "family_name": "",
        "quantidade_produtos": "",
        "mlb": "",
        "sku": "",
        "cor": "",
        "tamanho": "",
        "user_product_id_antes": "",
        "user_product_id_depois": "",
        "family_id_mudou": "",
        "user_product_id_mudou": "",
        "familias_unificadas": "",
        "family_ids_origem": "",
    }
    linhas.append(
        {
            "tipo_registro": "RESUMO",
            "status_agrupamento": relatorio.get("status_agrupamento", ""),
            "total_produtos": relatorio.get("total_produtos", ""),
            "familias_antes": relatorio.get("antes", {}).get("total_familias", ""),
            "familias_depois": relatorio.get("depois", {}).get("total_familias", ""),
            "reducao_familias": relatorio.get("resultado", {}).get("reducao_familias", ""),
            "percentual_reducao": relatorio.get("resultado", {}).get("percentual_reducao_familias", ""),
            "produtos_que_mudaram": relatorio.get("resultado", {}).get(
                "total_produtos_que_mudaram_de_familia", ""
            ),
            "total_fusoes": relatorio.get("resultado", {}).get("total_fusoes_detectadas", ""),
            "resumo": relatorio.get("resumo", ""),
            **base_vazio,
        }
    )

    def texto(valor: object) -> str:
        if valor is None:
            return ""
        if isinstance(valor, list):
            return ", ".join(str(v) for v in valor if v is not None)
        if isinstance(valor, dict):
            return json.dumps(valor, ensure_ascii=False)
        return str(valor)

    for familia in relatorio.get("antes", {}).get("grupos", []):
        linhas.append(
            {
                "tipo_registro": "FAMILIA_ANTES",
                "status_agrupamento": "",
                "total_produtos": "",
                "familias_antes": "",
                "familias_depois": "",
                "reducao_familias": "",
                "percentual_reducao": "",
                "produtos_que_mudaram": "",
                "total_fusoes": "",
                "resumo": "",
                "family_id_antes": familia.get("family_id") or "",
                "family_id_depois": "",
                "family_name": texto(familia.get("family_names")),
                "quantidade_produtos": familia.get("quantidade_produtos", ""),
                "mlb": texto(familia.get("mlbs")),
                "sku": texto(familia.get("skus")),
                "cor": texto(familia.get("cores")),
                "tamanho": texto(familia.get("tamanhos")),
                "user_product_id_antes": texto(familia.get("user_product_ids")),
                "user_product_id_depois": "",
                "family_id_mudou": "",
                "user_product_id_mudou": "",
                "familias_unificadas": "",
                "family_ids_origem": "",
            }
        )

    for familia in relatorio.get("depois", {}).get("grupos", []):
        linhas.append(
            {
                "tipo_registro": "FAMILIA_DEPOIS",
                "status_agrupamento": "",
                "total_produtos": "",
                "familias_antes": "",
                "familias_depois": "",
                "reducao_familias": "",
                "percentual_reducao": "",
                "produtos_que_mudaram": "",
                "total_fusoes": "",
                "resumo": "",
                "family_id_antes": "",
                "family_id_depois": familia.get("family_id") or "",
                "family_name": texto(familia.get("family_names")),
                "quantidade_produtos": familia.get("quantidade_produtos", ""),
                "mlb": texto(familia.get("mlbs")),
                "sku": texto(familia.get("skus")),
                "cor": texto(familia.get("cores")),
                "tamanho": texto(familia.get("tamanhos")),
                "user_product_id_antes": "",
                "user_product_id_depois": texto(familia.get("user_product_ids")),
                "family_id_mudou": "",
                "user_product_id_mudou": "",
                "familias_unificadas": familia.get("quantidade_familias_origem") or "",
                "family_ids_origem": texto(familia.get("family_ids_origem")),
            }
        )

    for quase in relatorio.get("quase_familias", []):
        for familia in quase.get("familias", []):
            linhas.append(
                {
                    "tipo_registro": "QUASE_FAMILIA",
                    "status_agrupamento": "",
                    "total_produtos": quase.get("total_produtos", ""),
                    "familias_antes": quase.get("total_familias", ""),
                    "familias_depois": "",
                    "reducao_familias": "",
                    "percentual_reducao": "",
                    "produtos_que_mudaram": "",
                    "total_fusoes": "",
                    "resumo": quase.get("acao") or quase.get("chave") or "",
                    "family_id_antes": familia.get("family_id") or "",
                    "family_id_depois": "",
                    "family_name": familia.get("family_name") or "",
                    "quantidade_produtos": len(familia.get("mlbs") or []),
                    "mlb": texto(familia.get("mlbs")),
                    "sku": "",
                    "cor": "",
                    "tamanho": "",
                    "user_product_id_antes": "",
                    "user_product_id_depois": "",
                    "family_id_mudou": "",
                    "user_product_id_mudou": "",
                    "familias_unificadas": "SIM" if familia.get("bloqueado_vendas") else "NÃO",
                    "family_ids_origem": quase.get("chave") or "",
                }
            )

    for migracao in relatorio.get("migracoes", []):
        linhas.append(
            {
                "tipo_registro": "MIGRACAO",
                "status_agrupamento": "",
                "total_produtos": "",
                "familias_antes": "",
                "familias_depois": "",
                "reducao_familias": "",
                "percentual_reducao": "",
                "produtos_que_mudaram": "",
                "total_fusoes": "",
                "resumo": "",
                "family_id_antes": migracao.get("family_id_antes") or "",
                "family_id_depois": migracao.get("family_id_depois") or "",
                "family_name": migracao.get("family_name_depois") or "",
                "quantidade_produtos": "",
                "mlb": migracao.get("mlb") or "",
                "sku": migracao.get("sku") or "",
                "cor": migracao.get("color") or "",
                "tamanho": migracao.get("size") or "",
                "user_product_id_antes": migracao.get("user_product_id_antes") or "",
                "user_product_id_depois": migracao.get("user_product_id_depois") or "",
                "family_id_mudou": "SIM" if migracao.get("family_id_mudou") else "NÃO",
                "user_product_id_mudou": "SIM" if migracao.get("user_product_id_mudou") else "NÃO",
                "familias_unificadas": "",
                "family_ids_origem": "",
            }
        )
    return linhas


def _campo(valor: object) -> str:
    if valor is None or valor == "":
        return "-"
    return str(valor)


def _resumo_put(put: dict[str, Any]) -> dict[str, Any]:
    body = put.get("body") if isinstance(put.get("body"), dict) else {}
    atributos: list[dict[str, Any]] = []
    for attr in body.get("attributes") or []:
        if not isinstance(attr, dict):
            continue
        atributos.append(
            {
                "id": attr.get("id"),
                "value_id": attr.get("value_id"),
                "value_name": attr.get("value_name"),
            }
        )
    family_name = body.get("family_name")
    n_campos = len(atributos) + (1 if family_name else 0)
    return {
        "request_type": put.get("request_type"),
        "status": put.get("status"),
        "status_code": put.get("status_code"),
        "erro": put.get("erro"),
        "url": put.get("url"),
        "family_name": family_name,
        "attributes": atributos,
        "n_campos": n_campos,
        "mensagem_api": detalhe_erro_api(put.get("resposta")) or None,
    }


def montar_detalhe_mlbs(
    comparacao: list[dict[str, Any]],
    resultados_put: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    puts_por_mlb: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for put in resultados_put:
        mlb = put.get("mlb")
        if mlb:
            puts_por_mlb[str(mlb)].append(_resumo_put(put))

    detalhes: list[dict[str, Any]] = []
    for registro in comparacao:
        mlb = str(registro["mlb"])
        puts = puts_por_mlb.get(mlb, [])
        detalhes.append(
            {
                "mlb": mlb,
                "fonte": registro.get("fonte") or "lote",
                "status_antes": registro.get("status_antes"),
                "status_depois": registro.get("status_depois") or registro.get("status_antes"),
                "sold_quantity": registro.get("sold_quantity_antes") or 0,
                "gender_antes": registro.get("gender_antes"),
                "gender_depois": registro.get("gender_depois") or registro.get("gender_antes"),
                "gender_mudou": bool(registro.get("gender_mudou")),
                "color": registro.get("color") or registro.get("color_antes"),
                "size": registro.get("size") or registro.get("size_antes"),
                "user_product_id": registro.get("user_product_id_antes"),
                "family_id_antes": registro.get("family_id_antes"),
                "family_id_depois": registro.get("family_id_depois"),
                "family_id_mudou": bool(registro.get("family_id_mudou")),
                "family_name_antes": registro.get("family_name_antes"),
                "family_name_depois": registro.get("family_name_depois")
                or registro.get("family_name_antes"),
                "family_name_mudou": bool(registro.get("family_name_mudou")),
                "parent_pk": registro.get("parent_pk") or {},
                "child_pk": registro.get("child_pk") or {},
                "revalidacao_ok": bool(registro.get("revalidacao_ok")),
                "puts": puts,
                "total_puts": len(puts),
                "puts_ok": sum(1 for p in puts if p.get("status") == "ok"),
                "puts_erro": sum(1 for p in puts if p.get("status") == "erro"),
                "puts_planejado": sum(1 for p in puts if p.get("status") == "planejado"),
                "campos_enviados": sum(int(p.get("n_campos") or 0) for p in puts),
            }
        )
    detalhes.sort(key=lambda item: item["mlb"])
    return detalhes


def _fluxos_family_id(detalhes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    contagem: dict[tuple[str, str], list[str]] = defaultdict(list)
    for item in detalhes:
        if not item.get("family_id_mudou"):
            continue
        origem = _campo(item.get("family_id_antes"))
        destino = _campo(item.get("family_id_depois"))
        contagem[(origem, destino)].append(item["mlb"])
    saida = [
        {
            "family_id_antes": origem,
            "family_id_depois": destino,
            "quantidade": len(mlbs),
            "mlbs": sorted(mlbs),
        }
        for (origem, destino), mlbs in contagem.items()
    ]
    saida.sort(key=lambda item: -item["quantidade"])
    return saida


def montar_listagem_family_name(detalhes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grupos: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in detalhes:
        nome = (item.get("family_name_depois") or item.get("family_name_antes") or "").strip()
        grupos[nome or "(sem family_name)"].append(item)

    blocos: list[dict[str, Any]] = []
    for nome, membros in grupos.items():
        closed = [p["mlb"] for p in membros if p.get("status_depois") == "closed"]
        abertos = [p["mlb"] for p in membros if p.get("status_depois") != "closed"]
        fluxos = _fluxos_family_id(membros)
        blocos.append(
            {
                "family_name": nome,
                "n": len(membros),
                "vendas": sum(int(p.get("sold_quantity") or 0) for p in membros),
                "closed": len(closed),
                "family_ids": sorted(
                    {
                        str(fid)
                        for p in membros
                        if (
                            fid := (
                                p.get("family_id_depois")
                                if p.get("revalidacao_ok")
                                else p.get("family_id_antes")
                            )
                        )
                        not in (None, "")
                    }
                ),
                "status": sorted({p.get("status_depois") for p in membros if p.get("status_depois")}),
                "gender": sorted(
                    {p.get("gender_depois") or p.get("gender_antes") for p in membros if p.get("gender_depois") or p.get("gender_antes")}
                ),
                "mlbs": sorted(p["mlb"] for p in membros),
                "mlbs_closed": sorted(closed),
                "mlbs_abertos": sorted(abertos),
                "mlbs_que_mudaram_family_id": sorted(p["mlb"] for p in membros if p.get("family_id_mudou")),
                "quantidade_que_mudaram_family_id": sum(1 for p in membros if p.get("family_id_mudou")),
                "quantidade_puts": sum(int(p.get("total_puts") or 0) for p in membros),
                "quantidade_puts_ok": sum(int(p.get("puts_ok") or 0) for p in membros),
                "quantidade_puts_erro": sum(int(p.get("puts_erro") or 0) for p in membros),
                "fluxos_family_id": fluxos,
                "detalhes": membros,
            }
        )
    blocos.sort(key=lambda item: (-item["n"], item["family_name"]))
    maior = blocos[0]["n"] if blocos else 0
    for bloco in blocos:
        bloco["da_para_juntar"] = _da_para_juntar(bloco, maior)
    return blocos


def _da_para_juntar(bloco: dict[str, Any], maior_n: int) -> str:
    if bloco["family_name"] == "(sem family_name)":
        return "não — sem family_name"
    if bloco["n"] and bloco["closed"] == bloco["n"]:
        return "não — closed"
    if bloco["n"] == maior_n:
        return "já é o grupo maior"
    if bloco["vendas"] > 0:
        return "não — nome diferente"
    return "não — closed"


def _linha_alteracao_put(put: dict[str, Any]) -> str:
    status = put.get("status") or "?"
    tipo = put.get("request_type") or "put"
    partes = [f"    [{status}] {tipo}"]
    attrs = put.get("attributes") or []
    if attrs:
        desc = []
        for attr in attrs:
            valor = attr.get("value_name") or attr.get("value_id") or ""
            desc.append(f"{attr.get('id')}={valor}" if valor else str(attr.get("id")))
        partes.append("atributos: " + ", ".join(desc))
    if put.get("family_name"):
        partes.append(f'family_name="{put["family_name"]}"')
    if put.get("status_code"):
        partes.append(f"HTTP {put['status_code']}")
    if put.get("mensagem_api"):
        partes.append(str(put["mensagem_api"]))
    elif put.get("erro"):
        partes.append(str(put["erro"]))
    return " · ".join(partes)


def _bloco_mlb(item: dict[str, Any]) -> list[str]:
    fid_antes = _campo(item.get("family_id_antes"))
    fid_depois = _campo(item.get("family_id_depois")) if item.get("revalidacao_ok") else "(não revalidado)"
    fname_antes = _campo(item.get("family_name_antes"))
    fname_depois = _campo(item.get("family_name_depois")) if item.get("revalidacao_ok") else fname_antes
    gender_antes = _campo(item.get("gender_antes"))
    gender_depois = _campo(item.get("gender_depois")) if item.get("revalidacao_ok") else gender_antes
    status_antes = _campo(item.get("status_antes"))
    status_depois = _campo(item.get("status_depois"))
    linhas = [
        item["mlb"],
        (
            f"  status: {status_antes} → {status_depois} · vendas: {item.get('sold_quantity') or 0} · "
            f"fonte: {item.get('fonte')} · UP: {_campo(item.get('user_product_id'))}"
        ),
        f"  cor/tamanho: {_campo(item.get('color'))} / {_campo(item.get('size'))}",
        f"  GENDER: {gender_antes} → {gender_depois}"
        + ("  MUDOU" if item.get("gender_mudou") else ""),
        f"  family_id: {fid_antes} → {fid_depois}"
        + ("  MUDOU" if item.get("family_id_mudou") else ""),
        f"  family_name: {fname_antes} → {fname_depois}"
        + ("  MUDOU" if item.get("family_name_mudou") else ""),
        (
            f"  alterações neste MLB: {item.get('total_puts') or 0} PUT(s) "
            f"({item.get('puts_ok') or 0} ok, {item.get('puts_erro') or 0} erro, "
            f"{item.get('puts_planejado') or 0} planejado) · "
            f"{item.get('campos_enviados') or 0} campo(s) no body"
        ),
    ]
    if item.get("puts"):
        linhas.extend(_linha_alteracao_put(put) for put in item["puts"])
    else:
        linhas.append("    (nenhum PUT enviado neste MLB)")
    return linhas


def texto_listagem_family_name(
    relatorio: dict[str, Any],
    *,
    gerado_em: str | None = None,
) -> str:
    listagem = relatorio.get("listagem_family_name") or []
    detalhes = relatorio.get("detalhe_mlbs") or []
    resultado = relatorio.get("resultado") or {}
    fluxos = resultado.get("fluxos_family_id") or []
    total = sum(int(item["n"]) for item in listagem)
    mudaram = sum(1 for item in detalhes if item.get("family_id_mudou"))
    linhas = [
        "MLBs por family_name",
        f"Gerado em: {gerado_em or relatorio.get('gerado_em') or datetime.now(timezone.utc).isoformat()}",
        f"Modo: {'DRY-RUN (PUTs não enviados)' if relatorio.get('dry_run') else 'APPLY'}",
        f"Status agrupamento: {relatorio.get('status_agrupamento') or '-'}",
        f"Total: {total} anúncio(s) em {len(listagem)} family_name(s)",
        "",
        "RESUMO DE ALTERAÇÕES",
        f"- Anúncios que mudaram de family_id: {mudaram} de {total}",
        (
            f"- PUTs: {resultado.get('total_puts') or 0} "
            f"({resultado.get('puts_ok') or 0} ok, "
            f"{resultado.get('puts_erro') or 0} erro, "
            f"{resultado.get('puts_planejado') or 0} planejado)"
        ),
        f"- Famílias (family_id) antes → depois: "
        f"{(relatorio.get('antes') or {}).get('total_familias', '-')} → "
        f"{(relatorio.get('depois') or {}).get('total_familias', '-')}",
        "",
        "MIGRAÇÕES family_id (origem → destino)",
    ]
    if fluxos:
        for fluxo in fluxos:
            linhas.append(
                f"  {fluxo['quantidade']} item(ns): "
                f"{fluxo['family_id_antes']} → {fluxo['family_id_depois']}"
            )
    else:
        linhas.append("  (nenhuma mudança de family_id detectada nesta execução)")

    linhas.extend(["", "Itens\tfamily_name\tVendas\tMudaram family_id\tPUTs\tDá para juntar?"])
    for item in listagem:
        linhas.append(
            f"{item['n']}\t{item['family_name']}\t{item['vendas']}\t"
            f"{item.get('quantidade_que_mudaram_family_id') or 0}\t"
            f"{item.get('quantidade_puts') or 0}\t{item.get('da_para_juntar') or '-'}"
        )

    for item in listagem:
        linhas.extend(["", f"=== {item['n']} — {item['family_name']} ==="])
        extra = []
        if item.get("gender"):
            extra.append("GENDER: " + ", ".join(item["gender"]))
        if item.get("family_ids"):
            extra.append("family_id: " + ", ".join(item["family_ids"]))
        extra.append(f"Vendas: {item['vendas']}")
        extra.append(
            f"Mudaram family_id: {item.get('quantidade_que_mudaram_family_id') or 0}/{item['n']}"
        )
        extra.append(
            f"PUTs: {item.get('quantidade_puts') or 0} "
            f"({item.get('quantidade_puts_ok') or 0} ok, {item.get('quantidade_puts_erro') or 0} erro)"
        )
        extra.append(f"Dá para juntar?: {item.get('da_para_juntar') or '-'}")
        linhas.append(" · ".join(extra))
        if item.get("fluxos_family_id"):
            linhas.append("Fluxos neste grupo:")
            for fluxo in item["fluxos_family_id"]:
                linhas.append(
                    f"  {fluxo['quantidade']}: {fluxo['family_id_antes']} → {fluxo['family_id_depois']}"
                )
        if item.get("mlbs_closed"):
            linhas.append("Closed: " + ", ".join(item["mlbs_closed"]))
        linhas.append("")
        linhas.append("DETALHE POR MLB")
        for mlb in item.get("detalhes") or []:
            linhas.extend(_bloco_mlb(mlb))
            linhas.append("")

    linhas.extend(["", "ÍNDICE — alterações por MLB (todos os grupos)", ""])
    linhas.append("MLB\tfamily_id mudou\tPUTs\tok\terro\tcampos\tfamily_id antes\tfamily_id depois")
    for item in detalhes:
        linhas.append(
            f"{item['mlb']}\t"
            f"{'SIM' if item.get('family_id_mudou') else 'NÃO'}\t"
            f"{item.get('total_puts') or 0}\t"
            f"{item.get('puts_ok') or 0}\t"
            f"{item.get('puts_erro') or 0}\t"
            f"{item.get('campos_enviados') or 0}\t"
            f"{_campo(item.get('family_id_antes'))}\t"
            f"{_campo(item.get('family_id_depois')) if item.get('revalidacao_ok') else '-'}"
        )
    linhas.append("")
    return "\n".join(linhas)


def gravar_saidas(relatorio: dict[str, Any], pasta: Path) -> dict[str, Path]:
    pasta.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = pasta / f"relatorio_{stamp}.json"
    csv_path = pasta / f"relatorio_{stamp}.csv"
    listagem_path = pasta / f"mlbs_por_family_name_{stamp}.txt"
    json_path.write_text(json.dumps(relatorio, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    linhas = achatar_relatorio(relatorio)
    if linhas:
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(linhas[0].keys()))
            writer.writeheader()
            writer.writerows(linhas)
    listagem_path.write_text(
        texto_listagem_family_name(relatorio, gerado_em=relatorio.get("gerado_em")),
        encoding="utf-8",
    )
    return {"json": json_path, "csv": csv_path, "mlbs_por_family_name": listagem_path}
