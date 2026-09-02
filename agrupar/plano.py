from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from agrupar.atributos import Attr, chave_attr, id_attr, nome_attr, payload_attr
from agrupar.config import GroupingUnit
from agrupar.genero import GENEROS_VALIDOS
from agrupar.modelos import ProdutoMeli, valor_parent
from agrupar.textos import chave_quase_familia, normalizar_texto, timestamp

CATEGORIA_ESPERADA = "MLB23332"
PARENT_PK_EDITAVEIS = (
    "BRAND",
    "LINE",
    "MODEL",
    "VERSION",
    "GENDER",
    "ALPHANUMERIC_MODEL",
)
PARENT_PK_READ_ONLY = ("AGE_GROUP",)
CHILD_PK = ("COLOR", "FABRIC_DESIGN", "WIDTH_TYPE", "SIZE_GRID_ROW_ID", "SIZE")
CHILD_PK_CRITICOS = ("COLOR", "SIZE")
STATUS_NAO_MODIFICAVEL = frozenset({"closed"})
GENEROS = {
    "Masculino": {"value_id": "339666", "value_name": "Masculino"},
    "Feminino": {"value_id": "339665", "value_name": "Feminino"},
    "Unissex": {"value_id": "110461", "value_name": "Sem gênero"},
}


@dataclass
class PutPlanejado:
    request_type: str
    mlb: str
    url: str
    body: dict[str, Any]
    genero_alvo: str
    user_product_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Diagnostico:
    request_type: str
    payload: dict[str, Any]


@dataclass
class PlanoCluster:
    genero_alvo: str
    cluster_id: str
    produtos: list[ProdutoMeli]
    family_name_referencia: str | None
    parent_pk_referencia: dict[str, dict[str, str | None]]
    puts_parent_pk: list[PutPlanejado]
    puts_family_name: list[PutPlanejado]
    diagnosticos: list[Diagnostico]
    bloqueios_estruturais: list[str]
    puts_familia: list[PutPlanejado] = field(default_factory=list)
    quase_familias: list[dict[str, Any]] = field(default_factory=list)


def chave_cluster(produto: ProdutoMeli, grouping_unit: GroupingUnit) -> str:
    if grouping_unit == "gender":
        return "lote_genero"
    brand = normalizar_texto(valor_parent(produto, "BRAND")) or "sem_brand"
    line = normalizar_texto(valor_parent(produto, "LINE")) or "sem_line"
    model = normalizar_texto(valor_parent(produto, "MODEL")) or "sem_model"
    return f"{brand}|{line}|{model}"


def montar_planos(
    produtos: list[ProdutoMeli],
    grouping_unit: GroupingUnit,
    tentar_family_name_com_vendas: bool,
    genero_forcado: str | None = None,
    family_name_forcado: str | None = None,
) -> list[PlanoCluster]:
    if genero_forcado:
        if genero_forcado not in GENEROS_VALIDOS:
            raise ValueError(f"Gênero inválido: {genero_forcado}")
        for produto in produtos:
            if produto.origem is None:
                continue
            produto.origem.genero_grupo = genero_forcado
            produto.origem.genero_origem = "forcado"

    por_genero: dict[str, list[ProdutoMeli]] = defaultdict(list)
    for produto in produtos:
        genero = produto.origem.genero_grupo if produto.origem else "NaoIdentificado"
        por_genero[genero].append(produto)

    planos: list[PlanoCluster] = []
    for genero, membros in por_genero.items():
        if genero not in GENEROS_VALIDOS:
            planos.append(_plano_nao_identificado(membros))
            continue
        clusters: dict[str, list[ProdutoMeli]] = defaultdict(list)
        for produto in membros:
            clusters[chave_cluster(produto, grouping_unit)].append(produto)
        for cluster_id, cluster in clusters.items():
            planos.append(
                _montar_cluster(
                    cluster,
                    genero,
                    cluster_id,
                    tentar_family_name_com_vendas,
                    family_name_forcado=family_name_forcado,
                )
            )
    return planos


def _plano_nao_identificado(produtos: list[ProdutoMeli]) -> PlanoCluster:
    return PlanoCluster(
        genero_alvo="NaoIdentificado",
        cluster_id="nao_identificado",
        produtos=produtos,
        family_name_referencia=None,
        parent_pk_referencia={},
        puts_parent_pk=[],
        puts_family_name=[],
        diagnosticos=[
            Diagnostico(
                request_type="genero_nao_identificado",
                payload={
                    "executar_put": False,
                    "mlbs": [p.mlb for p in produtos],
                    "motivo": (
                        "Título/transmissão sem Masculino, Feminino ou Unissex. "
                        "Nenhum PUT foi gerado."
                    ),
                },
            )
        ],
        bloqueios_estruturais=["genero nao identificado"],
    )


def _montar_cluster(
    produtos: list[ProdutoMeli],
    genero_alvo: str,
    cluster_id: str,
    tentar_family_name_com_vendas: bool,
    family_name_forcado: str | None = None,
) -> PlanoCluster:
    diagnosticos: list[Diagnostico] = []
    categorias = sorted({p.category_id for p in produtos if p.category_id})
    invalidas = [c for c in categorias if c != CATEGORIA_ESPERADA]
    if invalidas:
        return PlanoCluster(
            genero_alvo=genero_alvo,
            cluster_id=cluster_id,
            produtos=produtos,
            family_name_referencia=None,
            parent_pk_referencia={},
            puts_parent_pk=[],
            puts_family_name=[],
            diagnosticos=[
                Diagnostico(
                    request_type="category_mismatch",
                    payload={
                        "executar_put": False,
                        "mlbs": [p.mlb for p in produtos],
                        "categorias": categorias,
                        "categoria_esperada": CATEGORIA_ESPERADA,
                        "motivo": "Fluxo configurado para PARENT_PK da categoria MLB23332.",
                    },
                )
            ],
            bloqueios_estruturais=["categoria divergente"],
        )

    if family_name_forcado and family_name_forcado.strip():
        family_name_referencia = family_name_forcado.strip()
        chave = normalizar_texto(family_name_referencia)
        produtos_familia_ref = [
            p for p in produtos if normalizar_texto(p.family_name) == chave
        ] or produtos
        diagnosticos.append(
            Diagnostico(
                request_type="family_name_forcado",
                payload={
                    "executar_put": False,
                    "family_name_referencia": family_name_referencia,
                    "mlbs_ja_com_este_nome": [p.mlb for p in produtos_familia_ref]
                    if produtos_familia_ref is not produtos
                    else [],
                    "motivo": "family_name de referência forçado na linha de comando.",
                },
            )
        )
    else:
        family_name_referencia, produtos_familia_ref = _escolher_family_name(produtos, genero_alvo)
    parent_refs = {
        attr_id: _escolher_referencia_parent(attr_id, produtos_familia_ref, produtos, genero_alvo)
        for attr_id in PARENT_PK_EDITAVEIS
    }
    parent_refs = {k: v for k, v in parent_refs.items() if v is not None}

    puts_parent: list[PutPlanejado] = []
    mlbs_com_put: set[str] = set()
    for produto in produtos:
        if not produto.family_name or not produto.user_product_id:
            diagnosticos.append(
                Diagnostico(
                    request_type="legacy_ignorado",
                    payload={
                        "executar_put": False,
                        "mlb": produto.mlb,
                        "motivo": "Item sem family_name/user_product_id. Fluxo não altera legacy.",
                    },
                )
            )
            continue
        if produto.status in STATUS_NAO_MODIFICAVEL:
            diagnosticos.append(
                Diagnostico(
                    request_type="item_closed",
                    payload={
                        "executar_put": False,
                        "mlb": produto.mlb,
                        "status": produto.status,
                        "motivo": (
                            "Item closed: a API recusa alteração de atributos "
                            "(item.attributes.not_modifiable)."
                        ),
                    },
                )
            )
            continue
        attributes_put: list[dict[str, str]] = []
        divergencias: list[dict[str, Any]] = []
        for attr_id in PARENT_PK_EDITAVEIS:
            referencia = parent_refs.get(attr_id)
            if referencia is None:
                continue
            atual = produto.attributes.get(attr_id)
            if _attr_igual(attr_id, atual, referencia, genero_alvo):
                continue
            payload = (
                {"id": "GENDER", "value_id": GENEROS[genero_alvo]["value_id"]}
                if attr_id == "GENDER"
                else payload_attr(attr_id, referencia)
            )
            if not payload:
                continue
            attributes_put.append(payload)
            divergencias.append(
                {
                    "id": attr_id,
                    "atual": (
                        {"value_id": id_attr(atual), "value_name": nome_attr(atual)}
                        if atual
                        else None
                    ),
                    "referencia": {
                        "value_id": (
                            GENEROS[genero_alvo]["value_id"]
                            if attr_id == "GENDER"
                            else id_attr(referencia)
                        ),
                        "value_name": (
                            GENEROS[genero_alvo]["value_name"]
                            if attr_id == "GENDER"
                            else nome_attr(referencia)
                        ),
                    },
                    "payload": payload,
                }
            )
        if attributes_put:
            mlbs_com_put.add(produto.mlb)
            puts_parent.append(
                PutPlanejado(
                    request_type="parent_pk",
                    mlb=produto.mlb,
                    url=f"https://api.mercadolibre.com/items/{produto.mlb}",
                    body={"attributes": attributes_put},
                    genero_alvo=genero_alvo,
                    user_product_id=produto.user_product_id,
                    extra={
                        "family_id_atual": produto.family_id,
                        "family_name_atual": produto.family_name,
                        "parent_pk_divergentes": divergencias,
                    },
                )
            )
        else:
            diagnosticos.append(
                Diagnostico(
                    request_type="parent_pk_ok",
                    payload={
                        "executar_put": False,
                        "mlb": produto.mlb,
                        "user_product_id": produto.user_product_id,
                        "family_id_atual": produto.family_id,
                        "family_name_atual": produto.family_name,
                        "motivo": "PARENT_PK editáveis já iguais à referência.",
                    },
                )
            )

    puts_family = _puts_family_name(
        produtos,
        genero_alvo,
        family_name_referencia,
        tentar_family_name_com_vendas,
        diagnosticos,
    )
    puts_familia = _puts_familia_hash_livre(
        produtos,
        genero_alvo,
        family_name_referencia,
        diagnosticos,
    )
    quase = montar_quase_familias(produtos)

    child_pk = _diagnostico_child_pk(produtos, diagnosticos)
    domain_ids = sorted({p.domain_id for p in produtos if p.domain_id})
    seller_ids = sorted({p.seller_id for p in produtos if p.seller_id})
    conditions = sorted({p.condition for p in produtos if p.condition})
    bloqueios = [
        *(["domain_id divergente"] if len(domain_ids) > 1 else []),
        *(["seller_id divergente"] if len(seller_ids) > 1 else []),
        *(["condition divergente"] if len(conditions) > 1 else []),
        *[
            f"CHILD_PK crítico ausente: {attr_id}"
            for attr_id in CHILD_PK_CRITICOS
            if child_pk[attr_id]["mlbs_faltantes"]
        ],
    ]
    parent_resumo = {
        attr_id: (
            {
                "value_id": (
                    GENEROS[genero_alvo]["value_id"]
                    if attr_id == "GENDER"
                    else id_attr(ref)
                ),
                "value_name": (
                    GENEROS[genero_alvo]["value_name"]
                    if attr_id == "GENDER"
                    else nome_attr(ref)
                ),
            }
            if (ref := parent_refs.get(attr_id))
            else None
        )
        for attr_id in PARENT_PK_EDITAVEIS
    }
    diagnosticos.insert(
        0,
        Diagnostico(
            request_type="resumo_referencia",
            payload={
                "executar_put": False,
                "genero_alvo": genero_alvo,
                "cluster_id": cluster_id,
                "total_mlbs_analisados": len(produtos),
                "category_id": categorias[0] if categorias else None,
                "family_name_referencia": family_name_referencia,
                "parent_pk_referencia": parent_resumo,
                "child_pk_diagnostico": child_pk,
                "domain_ids_encontrados": domain_ids,
                "seller_ids_encontrados": seller_ids,
                "conditions_encontradas": conditions,
                "bloqueios_estruturais": bloqueios,
                "mlbs_com_parent_put": sorted(mlbs_com_put),
                "quase_familias": quase,
            },
        ),
    )
    return PlanoCluster(
        genero_alvo=genero_alvo,
        cluster_id=cluster_id,
        produtos=produtos,
        family_name_referencia=family_name_referencia,
        parent_pk_referencia={k: v for k, v in parent_resumo.items() if v},
        puts_parent_pk=puts_parent,
        puts_family_name=puts_family,
        diagnosticos=diagnosticos,
        bloqueios_estruturais=bloqueios,
        puts_familia=puts_familia,
        quase_familias=quase,
    )


def _escolher_family_name(
    produtos: list[ProdutoMeli],
    genero_alvo: str,
) -> tuple[str | None, list[ProdutoMeli]]:
    grupos: dict[str, dict[str, Any]] = {}
    for produto in produtos:
        nome = _nome_familia_candidato(produto, genero_alvo)
        if not nome:
            continue
        chave = normalizar_texto(nome)
        if chave not in grupos:
            grupos[chave] = {"nome": nome, "produtos": []}
        grupos[chave]["produtos"].append(produto)

    if not grupos:
        return None, produtos

    def chave_ordem(grupo: dict[str, Any]) -> tuple:
        membros: list[ProdutoMeli] = grupo["produtos"]
        ativos = sum(1 for p in membros if p.status == "active")
        vendas = sum(p.sold_quantity for p in membros)
        recente = max((timestamp(p.last_updated) for p in membros), default=0)
        return (-len(membros), len(grupo["nome"]), -ativos, -vendas, -recente)

    melhor = sorted(grupos.values(), key=chave_ordem)[0]
    return melhor["nome"], melhor["produtos"]


def _escolher_referencia_parent(
    attr_id: str,
    produtos_familia: list[ProdutoMeli],
    todos: list[ProdutoMeli],
    genero_alvo: str,
) -> Attr | None:
    if attr_id == "GENDER":
        ref = GENEROS[genero_alvo]
        return Attr(
            id="GENDER",
            name="Gênero",
            value_id=ref["value_id"],
            value_name=ref["value_name"],
            value_type="list",
        )

    def escolher(produtos: list[ProdutoMeli]) -> Attr | None:
        grupos: dict[str, list[tuple[ProdutoMeli, Attr]]] = defaultdict(list)
        for produto in produtos:
            attr = produto.attributes.get(attr_id)
            chave = chave_attr(attr)
            if not chave or attr is None:
                continue
            grupos[chave].append((produto, attr))
        if not grupos:
            return None

        def ordem(pares: list[tuple[ProdutoMeli, Attr]]) -> tuple:
            ativos = sum(1 for p, _ in pares if p.status == "active")
            vendas = sum(p.sold_quantity for p, _ in pares)
            recente = max((timestamp(p.last_updated) for p, _ in pares), default=0)
            return (-len(pares), -ativos, -vendas, -recente)

        vencedor = sorted(grupos.values(), key=ordem)[0]
        return vencedor[0][1]

    return escolher(produtos_familia) or escolher(todos)


def _attr_igual(attr_id: str, atual: Attr | None, referencia: Attr, genero_alvo: str) -> bool:
    if attr_id == "GENDER":
        ref = GENEROS[genero_alvo]
        id_atual = id_attr(atual)
        nome_atual = normalizar_texto(nome_attr(atual))
        return id_atual == ref["value_id"] and (
            nome_atual == normalizar_texto(ref["value_name"])
            or (genero_alvo == "Unissex" and nome_atual == "sem genero")
        )
    if atual is None:
        return False
    id_ref = id_attr(referencia)
    if id_ref:
        return id_attr(atual) == id_ref
    return normalizar_texto(nome_attr(atual)) == normalizar_texto(nome_attr(referencia))


def _ajustar_genero_family_name(nome: str | None, genero_alvo: str) -> str | None:
    if not nome:
        return None
    texto = re.sub(r"\s+", " ", str(nome).strip())
    return re.sub(r"\b(?:Masculino|Feminino|Unissex|Unisex)\b", genero_alvo, texto, flags=re.I)


def _remover_tamanho_final(nome: str | None, produto: ProdutoMeli) -> str | None:
    if not nome:
        return nome
    size = nome_attr(produto.attributes.get("SIZE"))
    limpo = re.sub(r"\s+", " ", str(nome).strip())
    if not size:
        return limpo
    partes = [re.escape(p) for p in size.strip().split()]
    regex = re.compile(rf"\s+{' '.join(partes)}\s*$", re.I)
    return regex.sub("", limpo).strip()


def _nome_familia_candidato(produto: ProdutoMeli, genero_alvo: str) -> str | None:
    """Nome real da família (sem tamanho no final). Não reescreve gênero:

    com venda o Meli trava family_name; o alvo tem que ser o texto que já
    existe na família majoritária, senão o PUT não junta no picker grande.
    """
    if not produto.family_name:
        return None
    return _remover_tamanho_final(produto.family_name, produto)


def _puts_family_name(
    produtos: list[ProdutoMeli],
    genero_alvo: str,
    family_name_referencia: str | None,
    tentar_com_vendas: bool,
    diagnosticos: list[Diagnostico],
) -> list[PutPlanejado]:
    if not family_name_referencia:
        return []
    ups: dict[str, list[ProdutoMeli]] = defaultdict(list)
    for produto in produtos:
        if not produto.user_product_id or not produto.family_name:
            continue
        ups[produto.user_product_id].append(produto)

    puts: list[PutPlanejado] = []
    for user_product_id, membros in ups.items():
        representante = sorted(
            membros,
            key=lambda p: (
                p.status != "active",
                -p.sold_quantity,
                -timestamp(p.last_updated),
            ),
        )[0]
        ativos = [p for p in membros if p.status == "active"]
        if representante.status in STATUS_NAO_MODIFICAVEL or not ativos:
            diagnosticos.append(
                Diagnostico(
                    request_type="family_name_bloqueado_status",
                    payload={
                        "executar_put": False,
                        "mlb": representante.mlb,
                        "user_product_id": user_product_id,
                        "status": representante.status,
                        "family_name_atual": representante.family_name,
                        "family_name_referencia": family_name_referencia,
                        "motivo": (
                            "family_name só é enviado em User Product com item active. "
                            "Closed/paused-only não entram."
                        ),
                    },
                )
            )
            continue
        representante = sorted(
            ativos,
            key=lambda p: (-p.sold_quantity, -timestamp(p.last_updated)),
        )[0]
        if normalizar_texto(representante.family_name) == normalizar_texto(family_name_referencia):
            continue
        vendas = sum(p.sold_quantity for p in membros)
        if not tentar_com_vendas and vendas > 0:
            diagnosticos.append(
                Diagnostico(
                    request_type="family_name_bloqueado_vendas",
                    payload={
                        "executar_put": False,
                        "mlb": representante.mlb,
                        "user_product_id": user_product_id,
                        "family_name_atual": representante.family_name,
                        "family_name_referencia": family_name_referencia,
                        "sold_quantity_conhecida_no_up": vendas,
                        "motivo": (
                            "family_name não enviado: há vendas neste User Product. "
                            "O Mercado Livre bloqueia a alteração."
                        ),
                    },
                )
            )
            continue
        puts.append(
            PutPlanejado(
                request_type="family_name",
                mlb=representante.mlb,
                url=f"https://api.mercadolibre.com/items/{representante.mlb}",
                body={"family_name": family_name_referencia},
                genero_alvo=genero_alvo,
                user_product_id=user_product_id,
                extra={
                    "family_id_atual": representante.family_id,
                    "family_name_atual": representante.family_name,
                    "family_name_referencia": family_name_referencia,
                },
            )
        )
    return puts


def _puts_familia_hash_livre(
    produtos: list[ProdutoMeli],
    genero_alvo: str,
    family_name_referencia: str | None,
    diagnosticos: list[Diagnostico],
) -> list[PutPlanejado]:
    """PUT /user-products-families só se o family_name alvo ainda não existir no lote."""
    if not family_name_referencia:
        return []
    chave_alvo = normalizar_texto(family_name_referencia)
    if not chave_alvo:
        return []

    por_familia: dict[str, list[ProdutoMeli]] = defaultdict(list)
    for produto in produtos:
        if produto.family_id in (None, "") or not produto.family_name:
            continue
        por_familia[str(produto.family_id)].append(produto)
    if len(por_familia) < 1:
        return []

    ocupantes = {
        fid
        for fid, membros in por_familia.items()
        if normalizar_texto(membros[0].family_name) == chave_alvo
    }

    candidatos: list[tuple[str, list[ProdutoMeli]]] = []
    for family_id, membros in por_familia.items():
        nome_atual = membros[0].family_name
        if normalizar_texto(nome_atual) == chave_alvo:
            continue
        if ocupantes:
            diagnosticos.append(
                Diagnostico(
                    request_type="family_hash_ocupado",
                    payload={
                        "executar_put": False,
                        "family_id": family_id,
                        "family_name_atual": nome_atual,
                        "family_name_referencia": family_name_referencia,
                        "familias_com_hash_alvo": sorted(ocupantes),
                        "motivo": (
                            "PUT na família pulado: já existe família com o nome-alvo. "
                            "A API devolve 409 e não funde."
                        ),
                    },
                )
            )
            continue
        if all(p.status in STATUS_NAO_MODIFICAVEL for p in membros):
            diagnosticos.append(
                Diagnostico(
                    request_type="familia_closed",
                    payload={
                        "executar_put": False,
                        "family_id": family_id,
                        "mlbs": [p.mlb for p in membros],
                        "motivo": "Família só com itens closed. Rename não move o picker.",
                    },
                )
            )
            continue
        candidatos.append((family_id, membros))

    if not candidatos or ocupantes:
        return []

    family_id, membros = sorted(
        candidatos,
        key=lambda par: (
            -sum(1 for p in par[1] if p.status == "active"),
            -len(par[1]),
        ),
    )[0]
    representante = next((p for p in membros if p.status == "active"), membros[0])
    diagnosticos.append(
        Diagnostico(
            request_type="family_rename_hash_livre",
            payload={
                "executar_put": True,
                "family_id": family_id,
                "mlb": representante.mlb,
                "family_name_atual": representante.family_name,
                "family_name_referencia": family_name_referencia,
                "motivo": (
                    "Nome-alvo ainda não existe neste lote. Um PUT na família "
                    "renomeia; não funde com outra família."
                ),
            },
        )
    )
    return [
        PutPlanejado(
            request_type="family",
            mlb=representante.mlb,
            url=f"https://api.mercadolibre.com/user-products-families/{family_id}",
            body={"family_name": family_name_referencia},
            genero_alvo=genero_alvo,
            user_product_id=representante.user_product_id,
            extra={
                "family_id": family_id,
                "family_id_atual": representante.family_id,
                "family_name_atual": representante.family_name,
                "family_name_referencia": family_name_referencia,
            },
        )
    ]


def montar_quase_familias(produtos: list[ProdutoMeli]) -> list[dict[str, Any]]:
    grupos: dict[str, dict[str, list[ProdutoMeli]]] = defaultdict(lambda: defaultdict(list))
    for produto in produtos:
        chave = chave_quase_familia(produto.family_name)
        if not chave:
            continue
        family_id = str(produto.family_id) if produto.family_id not in (None, "") else f"SEM:{produto.mlb}"
        grupos[chave][family_id].append(produto)

    saida: list[dict[str, Any]] = []
    for chave, familias in grupos.items():
        if len(familias) < 2:
            continue
        blocos = []
        for family_id, membros in sorted(familias.items(), key=lambda kv: -len(kv[1])):
            vendas = sum(p.sold_quantity for p in membros)
            blocos.append(
                {
                    "family_id": None if family_id.startswith("SEM:") else family_id,
                    "family_name": next((p.family_name for p in membros if p.family_name), None),
                    "mlbs": sorted(p.mlb for p in membros),
                    "sold_quantity": vendas,
                    "status": sorted({p.status for p in membros if p.status}),
                    "bloqueado_vendas": vendas > 0,
                }
            )
        saida.append(
            {
                "chave": chave,
                "total_familias": len(familias),
                "total_produtos": sum(len(v) for v in familias.values()),
                "familias": blocos,
                "acao": (
                    "PARENT_PK alinhável; o family_name diverge só em gênero/Confortável. "
                    "Com venda, ajuste no seller center — a API não funde famílias."
                ),
            }
        )
    saida.sort(key=lambda item: (-item["total_produtos"], -item["total_familias"]))
    return saida


def _diagnostico_child_pk(
    produtos: list[ProdutoMeli],
    diagnosticos: list[Diagnostico],
) -> dict[str, Any]:
    saida: dict[str, Any] = {}
    for attr_id in CHILD_PK:
        presentes = [p.mlb for p in produtos if chave_attr(p.attributes.get(attr_id))]
        faltantes = [p.mlb for p in produtos if not chave_attr(p.attributes.get(attr_id))]
        critico = attr_id in CHILD_PK_CRITICOS
        saida[attr_id] = {
            "presentes": len(presentes),
            "total": len(produtos),
            "mlbs_faltantes": faltantes,
            "critico": critico,
        }
        if (presentes and faltantes) or (critico and not presentes):
            diagnosticos.append(
                Diagnostico(
                    request_type="child_pk_faltante",
                    payload={
                        "executar_put": False,
                        "child_pk": attr_id,
                        "critico": critico,
                        "mlbs_faltantes": faltantes,
                        "motivo": (
                            "CHILD_PK não é copiado. Presença inconsistente pode impedir o agrupamento."
                        ),
                    },
                )
            )
    return saida
