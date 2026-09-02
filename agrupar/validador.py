from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from agrupar.atributos import chave_attr, nome_attr
from agrupar.config import Settings, missing_runtime_info
from agrupar.irmaos import expandir_irmaos
from agrupar.logs import OnLog, emitir
from agrupar.meli import MeliClient
from agrupar.modelos import ProdutoMeli
from agrupar.origem import resolver_origem
from agrupar.plano import (
    CATEGORIA_ESPERADA,
    CHILD_PK,
    GENEROS,
    PARENT_PK_EDITAVEIS,
    PARENT_PK_READ_ONLY,
    STATUS_NAO_MODIFICAVEL,
)
from agrupar.textos import chave_quase_familia, normalizar_texto

PARENT_PK_TODOS = PARENT_PK_EDITAVEIS + PARENT_PK_READ_ONLY

_ORDEM_VEREDICTO = {
    "agrupavel_gender": 0,
    "agrupavel_parent_pk": 1,
    "hash_igual_family_id_diferente": 2,
    "possivel_se_alterar_parent_e_family_name": 3,
    "possivel_se_alterar_family_name": 4,
    "bloqueado_closed": 5,
    "bloqueado_child_pk": 6,
    "bloqueado_age_group": 7,
    "nao_agrupavel": 8,
}


def validar_agrupamento(
    produtos: list[ProdutoMeli],
    genero_alvo: str | None = None,
    family_name_alvo: str | None = None,
) -> dict[str, Any]:
    snaps = [_snapshot(produto) for produto in produtos]
    avisos: list[str] = []
    categorias = sorted(
        {
            snap["category_id"]
            for snap in snaps
            if snap["category_id"] and snap["category_id"] != CATEGORIA_ESPERADA
        }
    )
    if categorias:
        avisos.append(f"Categoria fora de {CATEGORIA_ESPERADA}: {', '.join(categorias)}.")

    familias_atuais = _blocos_familia(snaps)
    ja_agrupados: list[dict[str, Any]] = []
    oportunidades: list[dict[str, Any]] = []
    isolados: list[dict[str, Any]] = []
    veredicto_por_mlb: dict[str, str] = {}
    opp_por_mlb: dict[str, str] = {}

    por_produto: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for snap in snaps:
        por_produto[_chave_produto(snap)].append(snap)

    opp_seq = 0
    ja_seq = 0
    for membros in por_produto.values():
        membros.sort(key=lambda item: item["mlb"])
        if len(membros) == 1:
            isolado = membros[0]
            isolados.append(
                {
                    "mlb": isolado["mlb"],
                    "family_id": isolado["family_id"] or None,
                    "family_name": isolado["family_name"],
                    "brand": isolado["parent_nome"].get("BRAND") or "",
                    "model": isolado["parent_nome"].get("MODEL") or "",
                    "motivo": "Não há outro anúncio no lote com a mesma marca+modelo+seller.",
                }
            )
            veredicto_por_mlb[isolado["mlb"]] = "isolado"
            continue

        family_keys = {item["family_id_key"] for item in membros}
        if len(family_keys) == 1:
            ja_seq += 1
            bloco = _montar_ja_agrupados(f"ja-{ja_seq}", membros)
            ja_agrupados.append(bloco)
            for item in membros:
                veredicto_por_mlb[item["mlb"]] = "ja_agrupado"
                opp_por_mlb[item["mlb"]] = bloco["id"]
            continue

        opp_seq += 1
        oportunidade = _classificar_cluster(
            f"opp-{opp_seq}",
            membros,
            genero_alvo=genero_alvo,
            family_name_alvo=family_name_alvo,
        )
        oportunidades.append(oportunidade)
        for item in membros:
            veredicto_por_mlb[item["mlb"]] = oportunidade["veredicto"]
            opp_por_mlb[item["mlb"]] = oportunidade["id"]

    oportunidades.sort(key=lambda item: (_ORDEM_VEREDICTO.get(item["veredicto"], 99), -item["n"]))
    ja_agrupados.sort(key=lambda item: -item["n"])
    isolados.sort(key=lambda item: item["mlb"])

    itens = [_item_tabela(snap, veredicto_por_mlb, opp_por_mlb) for snap in snaps]
    itens.sort(key=lambda item: item["mlb"])

    contagens = {
        "mlbs_ok": len(snaps),
        "familias": len(familias_atuais),
        "ja_agrupados": sum(item["n"] for item in ja_agrupados),
        "agrupaveis_api": _contar_veredictos(
            oportunidades, {"agrupavel_gender", "agrupavel_parent_pk", "hash_igual_family_id_diferente"}
        ),
        "dependem_parametro": _contar_veredictos(
            oportunidades,
            {"possivel_se_alterar_family_name", "possivel_se_alterar_parent_e_family_name"},
        ),
        "bloqueados": _contar_veredictos(
            oportunidades,
            {"bloqueado_closed", "bloqueado_child_pk", "bloqueado_age_group", "nao_agrupavel"},
        ),
        "isolados": len(isolados),
        "oportunidades": len(oportunidades),
    }
    payload = {
        "ok": True,
        "genero_alvo": genero_alvo,
        "family_name_alvo": family_name_alvo,
        "avisos": avisos,
        "contagens": contagens,
        "familias_atuais": familias_atuais,
        "ja_agrupados": ja_agrupados,
        "oportunidades": oportunidades,
        "isolados": isolados,
        "itens": itens,
    }
    payload["texto"] = texto_validacao(payload)
    return payload


async def executar_validacao(
    settings: Settings,
    mlbs: list[str],
    on_log: OnLog = None,
) -> dict[str, Any]:
    faltando = missing_runtime_info(settings)
    if faltando:
        emitir(on_log, "error", "Informações obrigatórias ausentes.", faltando=faltando)
        return {"ok": False, "error": "Informações obrigatórias ausentes.", "faltando": faltando}

    resolucao = await resolver_origem(settings, mlbs, on_log)
    if not resolucao.get("ok"):
        emitir(on_log, "error", resolucao.get("error") or "Nenhum MLB ou SKU para validar.")
        return {
            "ok": False,
            "error": resolucao.get("error") or "Nenhum MLB ou SKU para validar.",
            "faltando": resolucao.get("faltando") or [],
        }
    origens = resolucao["origens"]

    emitir(on_log, "info", f"Validador (somente GET): {len(origens)} MLB(s). Nenhum PUT será enviado.")
    genero_alvo = settings.genero_forcado.strip() or None
    family_name_alvo = settings.family_name_forcado.strip() or None
    if genero_alvo:
        emitir(on_log, "info", f"Cenário hipotético de GENDER: {genero_alvo}.")
    if family_name_alvo:
        emitir(on_log, "info", f'Cenário hipotético de family_name: "{family_name_alvo}".')

    client = MeliClient(settings)
    emitir(on_log, "info", f"GET /items de {len(origens)} anúncio(s)...")
    try:
        produtos, falhas_get = await client.get_itens(origens)
    finally:
        await client.aclose()
    emitir(
        on_log,
        "ok" if produtos else "error",
        f"GET concluído: {len(produtos)} ok, {len(falhas_get)} falha(s).",
    )
    for falha in falhas_get:
        emitir(
            on_log,
            "error",
            f"GET {falha.get('mlb')}: {falha.get('erro')}"
            + (f" HTTP {falha.get('status_code')}" if falha.get("status_code") else ""),
            mlb=falha.get("mlb"),
            status_code=falha.get("status_code"),
        )

    if not produtos:
        is_token_invalido = any(
            falha.get("status_code") == 401 for falha in falhas_get
        )
        error = (
            "Token do Mercado Livre inválido ou expirado. "
            "Cole um novo Access Token e valide novamente."
            if is_token_invalido
            else "Nenhum anúncio pôde ser lido na API do Mercado Livre."
        )
        emitir(on_log, "error", error)
        return {
            "ok": False,
            "error": error,
            "faltando": [],
            "falhas_get": falhas_get,
        }

    if settings.expandir_irmaos:
        emitir(on_log, "info", "Buscando anúncios irmãos da mesma família/UP...")
        client = MeliClient(settings)
        try:
            origens_irmaos, avisos_irmaos = await expandir_irmaos(client, produtos)
            for aviso in avisos_irmaos:
                emitir(on_log, "info", aviso)
            if origens_irmaos:
                extras, falhas_irmaos = await client.get_itens(origens_irmaos)
                falhas_get.extend(falhas_irmaos)
                produtos.extend(extras)
                produtos.sort(key=lambda item: item.mlb)
                emitir(on_log, "info", f"{len(extras)} irmão(s) incluído(s) na validação.")
        finally:
            await client.aclose()
    else:
        emitir(on_log, "info", "Expansão de irmãos desligada — valida só os MLBs colados.")

    resultado = validar_agrupamento(produtos, genero_alvo=genero_alvo, family_name_alvo=family_name_alvo)
    avisos_sku = list(resolucao.get("avisos") or [])
    if avisos_sku:
        resultado["avisos"] = avisos_sku + list(resultado.get("avisos") or [])
        resultado["texto"] = texto_validacao(resultado)
    resultado["falhas_get"] = falhas_get
    if falhas_get:
        resultado.setdefault("avisos", []).append(
            f"{len(falhas_get)} MLB(s) não puderam ser lidos na API."
        )
    if not produtos and falhas_get:
        resultado["avisos"].insert(0, "Nenhum anúncio foi lido; o validador não tem o que classificar.")
    n_opp = resultado["contagens"]["oportunidades"]
    n_ja = resultado["contagens"]["ja_agrupados"]
    emitir(
        on_log,
        "ok",
        (
            f"Validação: {resultado['contagens']['mlbs_ok']} MLB(s), "
            f"{resultado['contagens']['familias']} família(s), "
            f"{n_ja} já agrupado(s), {n_opp} oportunidade(s) de junção."
        ),
    )
    return resultado


def texto_validacao(payload: dict[str, Any]) -> str:
    linhas = ["VALIDADOR DE AGRUPAMENTO (somente leitura)", ""]
    contagens = payload.get("contagens") or {}
    linhas.append(
        " · ".join(
            f"{chave}={valor}"
            for chave, valor in contagens.items()
        )
    )
    if payload.get("genero_alvo"):
        linhas.append(f"Cenário GENDER: {payload['genero_alvo']}")
    if payload.get("family_name_alvo"):
        linhas.append(f"Cenário family_name: {payload['family_name_alvo']}")
    for aviso in payload.get("avisos") or []:
        linhas.append(f"AVISO: {aviso}")
    linhas.append("")
    linhas.append("FAMÍLIAS ATUAIS")
    for bloco in payload.get("familias_atuais") or []:
        linhas.append(
            f"  {bloco['n']} · {bloco.get('family_name') or '—'} · "
            f"id={bloco.get('family_id') or '—'} · vendas={bloco.get('vendas') or 0}"
        )
    linhas.append("")
    linhas.append("JÁ AGRUPADOS")
    if not payload.get("ja_agrupados"):
        linhas.append("  (nenhum grupo com family_id compartilhado)")
    for bloco in payload.get("ja_agrupados") or []:
        linhas.append(f"  [{bloco['id']}] {bloco['titulo']}")
        linhas.append(f"    {bloco['motivo']}")
    linhas.append("")
    linhas.append("OPORTUNIDADES / POSSÍVEIS SE ALTERAR PARÂMETRO")
    if not payload.get("oportunidades"):
        linhas.append("  (nenhuma família distinta do mesmo produto no lote)")
    for bloco in payload.get("oportunidades") or []:
        linhas.append(f"  [{bloco['id']}] {bloco['veredicto']} · via={bloco['via']}")
        linhas.append(f"    {bloco['titulo']}")
        linhas.append(f"    {bloco['motivo']}")
        if bloco.get("parametros_a_alterar"):
            linhas.append(f"    Alterar: {', '.join(bloco['parametros_a_alterar'])}")
        for bloqueio in bloco.get("bloqueios") or []:
            linhas.append(f"    Bloqueio: {bloqueio}")
        if bloco.get("cenario_hipotetico"):
            linhas.append(f"    Cenário: {bloco['cenario_hipotetico']}")
    linhas.append("")
    linhas.append("ISOLADOS")
    if not payload.get("isolados"):
        linhas.append("  (nenhum)")
    for item in payload.get("isolados") or []:
        linhas.append(f"  {item['mlb']} · {item.get('brand')} {item.get('model')} · {item['motivo']}")
    linhas.append("")
    linhas.append("RAIO-X PARENT_PK / CHILD_PK")
    itens = payload.get("itens") or []
    if not itens:
        linhas.append("  (sem MLB)")
    for item in itens:
        linhas.append(f"  {item.get('mlb')}")
        linhas.append(f"    PARENT_PK {_formatar_pk(item.get('parent_pk'))}")
        linhas.append(f"    CHILD_PK {_formatar_pk(item.get('child_pk'))}")
    return "\n".join(linhas)


def _formatar_pk(mapa: object) -> str:
    if not isinstance(mapa, dict) or not mapa:
        return "—"
    return " · ".join(f"{chave}={valor or '—'}" for chave, valor in mapa.items())


def _snapshot(produto: ProdutoMeli) -> dict[str, Any]:
    parent = {attr_id: chave_attr(produto.attributes.get(attr_id)) or "" for attr_id in PARENT_PK_TODOS}
    parent_nome = {attr_id: nome_attr(produto.attributes.get(attr_id)) or "" for attr_id in PARENT_PK_TODOS}
    child_nome = {attr_id: nome_attr(produto.attributes.get(attr_id)) or "" for attr_id in CHILD_PK}
    family_id = "" if produto.family_id in (None, "") else str(produto.family_id)
    return {
        "mlb": produto.mlb,
        "status": produto.status or "",
        "sold_quantity": int(produto.sold_quantity or 0),
        "family_id": family_id,
        "family_id_key": family_id or f"SEM:{produto.mlb}",
        "family_name": produto.family_name or "",
        "seller_id": produto.seller_id or "",
        "domain_id": produto.domain_id or "",
        "condition": produto.condition or "",
        "category_id": produto.category_id or "",
        "parent": parent,
        "parent_nome": parent_nome,
        "child_nome": child_nome,
        "child_presence": [attr_id for attr_id in CHILD_PK if chave_attr(produto.attributes.get(attr_id))],
        "is_closed": (produto.status or "") in STATUS_NAO_MODIFICAVEL,
        "title": produto.title or "",
    }


def _chave_produto(snap: dict[str, Any]) -> str:
    brand = normalizar_texto(snap["parent_nome"].get("BRAND")) or "sem_brand"
    model = normalizar_texto(snap["parent_nome"].get("MODEL")) or "sem_model"
    return f"{snap['seller_id']}|{snap['domain_id']}|{brand}|{model}"


def _chave_hash(
    snap: dict[str, Any],
    *,
    family_name: str | None = None,
    parent_overrides: dict[str, str] | None = None,
) -> str:
    parent = dict(snap["parent"])
    if parent_overrides:
        parent.update(parent_overrides)
    nome = snap["family_name"] if family_name is None else family_name
    parent_part = ";".join(f"{attr_id}={parent.get(attr_id, '')}" for attr_id in PARENT_PK_TODOS)
    child = ",".join(snap["child_presence"])
    return "|".join(
        [
            normalizar_texto(nome),
            snap["domain_id"],
            snap["seller_id"],
            snap["condition"],
            parent_part,
            f"child:{child}",
        ]
    )


def _blocos_familia(snaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grupos: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for snap in snaps:
        grupos[snap["family_id_key"]].append(snap)
    blocos = []
    for membros in grupos.values():
        blocos.append(_bloco_familia(membros))
    blocos.sort(key=lambda item: (-item["n"], item.get("family_name") or ""))
    return blocos


def _bloco_familia(membros: list[dict[str, Any]]) -> dict[str, Any]:
    nomes = [item["family_name"] for item in membros if item["family_name"]]
    return {
        "family_id": membros[0]["family_id"] or None,
        "family_name": Counter(nomes).most_common(1)[0][0] if nomes else "",
        "n": len(membros),
        "vendas": sum(item["sold_quantity"] for item in membros),
        "gender": sorted({item["parent_nome"].get("GENDER") or "—" for item in membros}),
        "line": sorted({item["parent_nome"].get("LINE") or "—" for item in membros}),
        "status": sorted({item["status"] for item in membros if item["status"]}),
        "mlbs": sorted(item["mlb"] for item in membros),
        "closed": sum(1 for item in membros if item["is_closed"]),
    }


def _montar_ja_agrupados(opp_id: str, membros: list[dict[str, Any]]) -> dict[str, Any]:
    produto = _produto_resumo(membros)
    bloco = _bloco_familia(membros)
    return {
        "id": opp_id,
        "veredicto": "ja_agrupados",
        "via": "ja_ok",
        "n": len(membros),
        "titulo": (
            f"{produto['brand']} {produto['model']} · {len(membros)} anúncios "
            f"já na família {bloco['family_id'] or '—'}"
        ),
        "motivo": "Já compartilham o mesmo family_id. Não precisam de PUT para se agrupar entre si.",
        "parametros_a_alterar": [],
        "parametros_ja_iguais": [attr_id for attr_id in PARENT_PK_EDITAVEIS],
        "bloqueios": [],
        "cenario_hipotetico": None,
        "familias": [bloco],
        "divergencias": _divergencias(membros),
        "mlbs": sorted(item["mlb"] for item in membros),
        "produto": produto,
    }


def _classificar_cluster(
    opp_id: str,
    membros: list[dict[str, Any]],
    genero_alvo: str | None,
    family_name_alvo: str | None,
) -> dict[str, Any]:
    parent_diff = [
        attr_id
        for attr_id in PARENT_PK_TODOS
        if len({item["parent"].get(attr_id, "") for item in membros}) > 1
    ]
    editaveis_diff = [attr_id for attr_id in parent_diff if attr_id in PARENT_PK_EDITAVEIS]
    read_only_diff = [attr_id for attr_id in parent_diff if attr_id in PARENT_PK_READ_ONLY]
    names = {item["family_name"] for item in membros}
    name_diff = len(names) > 1
    child_diff = len({tuple(item["child_presence"]) for item in membros}) > 1
    seller_diff = len({item["seller_id"] for item in membros}) > 1
    domain_diff = len({item["domain_id"] for item in membros}) > 1
    condition_diff = len({item["condition"] for item in membros}) > 1
    quase = len({chave_quase_familia(item["family_name"]) for item in membros if item["family_name"]}) <= 1
    hashes = {_chave_hash(item) for item in membros}
    vendas = sum(item["sold_quantity"] for item in membros)
    closed_count = sum(1 for item in membros if item["is_closed"])
    majority_parent = {
        attr_id: Counter(item["parent"].get(attr_id, "") for item in membros).most_common(1)[0][0]
        for attr_id in PARENT_PK_TODOS
    }
    precisam = [
        item
        for item in membros
        if any(item["parent"].get(attr_id) != majority_parent[attr_id] for attr_id in editaveis_diff)
    ]
    open_precisam = [item for item in precisam if not item["is_closed"]]
    closed_precisam = [item for item in precisam if item["is_closed"]]

    veredicto = "nao_agrupavel"
    via = "nao"
    parametros: list[str] = []
    bloqueios: list[str] = []
    motivo = ""

    if seller_diff or domain_diff:
        motivo = "Seller ou domínio diferentes — o hash da família no Mercado Livre não fecha."
    elif condition_diff:
        motivo = "condition diferente (novo vs usado). A API de agrupamento não une essas listagens."
    elif read_only_diff:
        veredicto = "bloqueado_age_group"
        parametros = read_only_diff + editaveis_diff
        motivo = (
            f"{', '.join(read_only_diff)} diverge e não é editável via API. "
            "Sem esse alinhamento o hash da família permanece distinto."
        )
    elif child_diff:
        veredicto = "bloqueado_child_pk"
        parametros = ["CHILD_PK"]
        motivo = (
            "A presença de CHILD_PK (cor/tamanho/grade) é inconsistente no lote. "
            "A API não copia CHILD_PK; anúncios com presença diferente não caem no mesmo hash."
        )
    elif len(hashes) == 1:
        veredicto = "hash_igual_family_id_diferente"
        via = "recalculo"
        motivo = (
            "family_name, PARENT_PK e presença de CHILD_PK já coincidem, mas o family_id ainda "
            "é outro. Em geral resolve no recálculo do Mercado Livre, sem PUT."
        )
    elif not name_diff and editaveis_diff:
        parametros = editaveis_diff
        veredicto = "agrupavel_gender" if editaveis_diff == ["GENDER"] else "agrupavel_parent_pk"
        via = "api"
        motivo = (
            f"Mesmo family_name; family_id distinto porque {', '.join(editaveis_diff)} diverge. "
            "Alinhar PARENT_PK no PUT /items move o family_id. Venda não bloqueia PARENT_PK."
        )
        if not open_precisam and closed_precisam:
            veredicto = "bloqueado_closed"
            via = "nao"
            bloqueios.append(
                f"{len(closed_precisam)} anúncio(s) closed precisariam mudar PARENT_PK e a API recusa."
            )
            motivo = "O único ajuste necessário é PARENT_PK, mas os anúncios que divergem estão closed."
        elif closed_precisam:
            via = "api_parcial"
            bloqueios.append(
                f"{len(closed_precisam)} anúncio(s) closed não aceitam PARENT_PK "
                f"({', '.join(item['mlb'] for item in closed_precisam)})."
            )
    elif name_diff:
        parametros = (["family_name"] if name_diff else []) + editaveis_diff
        if editaveis_diff:
            veredicto = "possivel_se_alterar_parent_e_family_name"
        else:
            veredicto = "possivel_se_alterar_family_name"
        if quase:
            motivo = (
                "Mesmo produto (marca+modelo); os family_name só diferem em gênero/Confortável "
                "(quase-família). Alinhar PARENT_PK sozinho não funde: o hash inclui o nome."
            )
        else:
            motivo = (
                "Mesmo produto (marca+modelo) com family_name distinto. "
                "Para cair no mesmo hash seria preciso o mesmo nome e o mesmo PARENT_PK."
            )
        if editaveis_diff:
            motivo += (
                f" PARENT_PK a alinhar via API: {', '.join(editaveis_diff)} (venda não bloqueia)."
            )
        motivo += (
            " A API não funde famílias: PUT family_name em /items retorna 374 (User Product); "
            "PUT /user-products-families com hash já existente retorna 409."
        )
        if vendas > 0:
            via = "seller_center"
            bloqueios.append(
                f"Há {vendas} venda(s) no lote: family_name não muda na API "
                "(BODY_INVALID_FIELDS / campo travado)."
            )
        else:
            via = "api_com_risco_409"
            bloqueios.append(
                "Mesmo sem venda, adotar um family_name cujo hash já existe no lote gera 409."
            )
        if closed_precisam and editaveis_diff:
            bloqueios.append(
                f"{len(closed_precisam)} anúncio(s) closed não aceitam mudança de PARENT_PK."
            )
        if closed_count and name_diff:
            bloqueios.append(
                f"{closed_count} anúncio(s) closed: atributos do item não são modificáveis."
            )
    else:
        motivo = "family_id distinto sem diferença visível nos campos usados no hash. Tratar como recálculo pendente."
        veredicto = "hash_igual_family_id_diferente"
        via = "recalculo"

    return {
        "id": opp_id,
        "veredicto": veredicto,
        "via": via,
        "n": len(membros),
        "titulo": _titulo_cluster(membros),
        "motivo": motivo,
        "parametros_a_alterar": parametros,
        "parametros_ja_iguais": [
            attr_id for attr_id in PARENT_PK_EDITAVEIS if attr_id not in editaveis_diff
        ],
        "bloqueios": bloqueios,
        "cenario_hipotetico": _cenario_hipotetico(membros, genero_alvo, family_name_alvo),
        "familias": _blocos_familia(membros),
        "divergencias": _divergencias(membros),
        "mlbs": sorted(item["mlb"] for item in membros),
        "produto": _produto_resumo(membros),
        "quase_familia": quase,
        "vendas": vendas,
    }


def _titulo_cluster(membros: list[dict[str, Any]]) -> str:
    produto = _produto_resumo(membros)
    n_fam = len({item["family_id_key"] for item in membros})
    return (
        f"{produto['brand'] or '?'} {produto['model'] or '?'} · "
        f"{len(membros)} MLB · {n_fam} famílias"
    )


def _produto_resumo(membros: list[dict[str, Any]]) -> dict[str, str]:
    primeiro = membros[0]
    return {
        "brand": primeiro["parent_nome"].get("BRAND") or "",
        "model": primeiro["parent_nome"].get("MODEL") or "",
        "seller_id": primeiro["seller_id"],
        "domain_id": primeiro["domain_id"],
        "chave": _chave_produto(primeiro),
    }


def _divergencias(snaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    campos: list[tuple[str, Any]] = [("family_name", lambda item: item["family_name"] or "—")]
    for attr_id in PARENT_PK_TODOS:
        campos.append((attr_id, lambda item, atual=attr_id: item["parent_nome"].get(atual) or "—"))
    campos.append(("CHILD_PK", lambda item: ",".join(item["child_presence"]) or "—"))
    campos.append(("status", lambda item: item["status"] or "—"))
    saida = []
    for nome, obter in campos:
        valores: dict[str, list[str]] = defaultdict(list)
        for item in snaps:
            valores[obter(item)].append(item["mlb"])
        if len(valores) < 2:
            continue
        saida.append({"campo": nome, "valores": dict(valores)})
    return saida


def _cenario_hipotetico(
    membros: list[dict[str, Any]],
    genero_alvo: str | None,
    family_name_alvo: str | None,
) -> str | None:
    if not genero_alvo and not family_name_alvo:
        return None
    overrides: dict[str, str] = {}
    if genero_alvo and genero_alvo in GENEROS:
        overrides["GENDER"] = f"ID:{GENEROS[genero_alvo]['value_id']}"
    hashes_gender: set[str] = set()
    hashes_full: set[str] = set()
    for item in membros:
        parent_ov = None if item["is_closed"] else (overrides or None)
        hashes_gender.add(_chave_hash(item, parent_overrides=parent_ov))
        hashes_full.add(
            _chave_hash(
                item,
                family_name=family_name_alvo if family_name_alvo else item["family_name"],
                parent_overrides=parent_ov,
            )
        )
    partes: list[str] = []
    if genero_alvo:
        if len(hashes_gender) == 1:
            partes.append(f"Alinhar GENDER para {genero_alvo} unificaria o hash.")
        else:
            extra = (
                " family_name ainda diverge."
                if len({item["family_name"] for item in membros}) > 1
                else " outro PARENT_PK ou CHILD_PK ainda diverge."
            )
            partes.append(f"Alinhar só GENDER para {genero_alvo} não unifica:{extra}")
    if family_name_alvo:
        if len(hashes_full) == 1:
            partes.append(
                f'Se o family_name pudesse virar "{family_name_alvo}" '
                "(e o GENDER do cenário, nos anúncios abertos), o hash unificaria. "
                "A API em geral responde 409 se o hash-alvo já existe."
            )
        else:
            partes.append(
                "Mesmo com o family_name forçado, outro PARENT_PK/CHILD_PK ainda manteria famílias distintas."
            )
    return " ".join(partes) if partes else None


def _item_tabela(
    snap: dict[str, Any],
    veredicto_por_mlb: dict[str, str],
    opp_por_mlb: dict[str, str],
) -> dict[str, Any]:
    parent_pk = {attr_id: snap["parent_nome"].get(attr_id) or "" for attr_id in PARENT_PK_TODOS}
    child_pk = {attr_id: snap["child_nome"].get(attr_id) or "" for attr_id in CHILD_PK}
    return {
        "mlb": snap["mlb"],
        "status": snap["status"],
        "vendas": snap["sold_quantity"],
        "family_id": snap["family_id"] or None,
        "family_name": snap["family_name"],
        "gender": snap["parent_nome"].get("GENDER") or "",
        "line": snap["parent_nome"].get("LINE") or "",
        "brand": snap["parent_nome"].get("BRAND") or "",
        "model": snap["parent_nome"].get("MODEL") or "",
        "alphanumeric_model": snap["parent_nome"].get("ALPHANUMERIC_MODEL") or "",
        "parent_pk": parent_pk,
        "child_pk": child_pk,
        "closed": snap["is_closed"],
        "veredicto": veredicto_por_mlb.get(snap["mlb"], "isolado"),
        "oportunidade_id": opp_por_mlb.get(snap["mlb"]),
    }


def _contar_veredictos(oportunidades: list[dict[str, Any]], tipos: set[str]) -> int:
    return sum(item["n"] for item in oportunidades if item["veredicto"] in tipos)
