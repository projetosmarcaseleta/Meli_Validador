from __future__ import annotations

import asyncio
import time
from typing import Any

from agrupar.config import Settings, missing_runtime_info
from agrupar.genero import detectar_genero
from agrupar.irmaos import expandir_irmaos
from agrupar.logs import OnLog, detalhe_put, emitir
from agrupar.meli import MeliClient, MeliError
from agrupar.modelos import AnuncioOrigem, ProdutoMeli
from agrupar.origem import resolver_origem
from agrupar.plano import PutPlanejado, montar_planos
from agrupar.relatorio import gravar_saidas, montar_relatorio

Result = dict[str, Any]


async def _executar_puts(
    client: MeliClient,
    puts: list[PutPlanejado],
    dry_run: bool,
    on_log: OnLog = None,
) -> list[dict[str, Any]]:
    if dry_run:
        registros = []
        for put in puts:
            registro = {
                "request_type": put.request_type,
                "mlb": put.mlb,
                "url": put.url,
                "body": put.body,
                "dry_run": True,
                "status": "planejado",
            }
            emitir(on_log, "info", detalhe_put(registro), mlb=put.mlb)
            registros.append(registro)
        return registros

    async def enviar(put: PutPlanejado) -> dict[str, Any]:
        registro = {
            "request_type": put.request_type,
            "mlb": put.mlb,
            "url": put.url,
            "body": put.body,
            "dry_run": False,
        }
        if put.extra.get("family_id") is not None:
            registro["family_id"] = put.extra["family_id"]
        try:
            if put.request_type == "family":
                family_id = str(put.extra.get("family_id") or "")
                resposta = await client.put_family(family_id, put.body)
            else:
                resposta = await client.put_item(put.mlb, put.body)
            registro["status"] = "ok"
            registro["resposta"] = resposta
        except MeliError as exc:
            registro["status"] = "erro"
            registro["status_code"] = exc.status_code
            registro["erro"] = str(exc)
            registro["resposta"] = exc.body
        nivel = "ok" if registro["status"] == "ok" else "error"
        emitir(
            on_log,
            nivel,
            detalhe_put(registro),
            mlb=put.mlb,
            status_code=registro.get("status_code"),
        )
        return registro

    return list(await asyncio.gather(*(enviar(put) for put in puts)))


def _aplicar_genero(
    produtos: list[ProdutoMeli],
    origens: list[AnuncioOrigem],
    genero_forcado: str | None,
) -> None:
    origem_por_mlb = {o.mlb: o for o in origens}
    for produto in produtos:
        origem = produto.origem or origem_por_mlb.get(produto.mlb)
        if origem is None:
            continue
        if genero_forcado:
            origem.genero_grupo = genero_forcado
            origem.genero_origem = "forcado"
        else:
            origem.genero_grupo = detectar_genero(
                origem.nome_transmissao,
                produto.title,
                produto.family_name,
            )
            origem.genero_origem = "title_family_name_meli"
        produto.origem = origem


async def _aguardar_recalculo(
    client: MeliClient,
    produtos: list[ProdutoMeli],
    timeout_s: int,
    intervalo_s: int,
    on_log: OnLog = None,
) -> tuple[list[ProdutoMeli], list[dict[str, Any]], dict[str, Any]]:
    origens = [p.origem for p in produtos if p.origem]
    antes = {p.mlb: p.family_id for p in produtos}
    iniciado = time.monotonic()
    tentativas = 0
    produtos_depois: list[ProdutoMeli] = []
    falhas: list[dict[str, Any]] = []
    mudou = False

    emitir(
        on_log,
        "info",
        f"Aguardando recálculo de family_id (timeout {timeout_s}s).",
    )
    if timeout_s > 0:
        await asyncio.sleep(min(intervalo_s, timeout_s))

    while True:
        tentativas += 1
        produtos_depois, falhas = await client.get_itens(origens)
        mudou = any(
            str(p.family_id or "") != str(antes.get(p.mlb) or "") for p in produtos_depois
        )
        elapsed = time.monotonic() - iniciado
        emitir(
            on_log,
            "ok" if mudou else "info",
            (
                f"Poll {tentativas}: family_id mudou em pelo menos um item."
                if mudou
                else f"Poll {tentativas}: family_id ainda igual ({elapsed:.0f}s)."
            ),
        )
        if mudou or timeout_s <= 0 or elapsed >= timeout_s:
            break
        restante = timeout_s - elapsed
        await asyncio.sleep(min(intervalo_s, restante))

    return (
        produtos_depois,
        falhas,
        {
            "tentativas": tentativas,
            "timeout_segundos": timeout_s,
            "intervalo_segundos": intervalo_s,
            "segundos_decorridos": round(time.monotonic() - iniciado, 2),
            "family_id_mudou": mudou,
        },
    )


async def executar(
    settings: Settings,
    aplicar: bool | None = None,
    mlbs: list[str] | None = None,
    on_log: OnLog = None,
) -> Result:
    faltando = missing_runtime_info(settings)
    if faltando:
        emitir(on_log, "error", "Informações obrigatórias ausentes.", faltando=faltando)
        return {"ok": False, "error": "Informações obrigatórias ausentes.", "faltando": faltando}

    dry_run = settings.dry_run if aplicar is None else not aplicar
    resolucao = await resolver_origem(settings, mlbs, on_log)
    if not resolucao.get("ok"):
        emitir(on_log, "error", resolucao.get("error") or "Nenhum MLB ou SKU para processar.")
        return {
            "ok": False,
            "error": resolucao.get("error") or "Nenhum MLB ou SKU para processar.",
            "faltando": resolucao.get("faltando") or [],
        }
    origens = resolucao["origens"]

    modo = "simulação (dry-run)" if dry_run else "APPLY — vai enviar PUT"
    emitir(on_log, "warn" if not dry_run else "info", f"Início: {len(origens)} MLB(s) · {modo}.")

    genero_forcado = settings.genero_forcado.strip() or None
    avisos: list[str] = list(resolucao.get("avisos") or [])
    if genero_forcado:
        aviso_genero = f"Gênero forçado para {genero_forcado} em todos os itens do lote."
    else:
        aviso_genero = "Gênero é lido do title e do family_name do item no Mercado Livre."
    avisos.append(aviso_genero)
    emitir(on_log, "info", aviso_genero)
    if settings.family_name_forcado.strip():
        emitir(
            on_log,
            "info",
            f'family_name forçado: "{settings.family_name_forcado.strip()}".',
        )

    client = MeliClient(settings)
    try:
        emitir(on_log, "info", f"GET /items de {len(origens)} anúncio(s)...")
        produtos, falhas_get = await client.get_itens(origens)
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
        total_lote = len(produtos)
        total_irmaos = 0
        if settings.expandir_irmaos:
            emitir(on_log, "info", "Buscando anúncios irmãos da mesma família/UP...")
            origens_irmaos, avisos_irmaos = await expandir_irmaos(client, produtos)
            avisos.extend(avisos_irmaos)
            for aviso in avisos_irmaos:
                emitir(on_log, "info", aviso)
            if origens_irmaos:
                extras, falhas_irmaos = await client.get_itens(origens_irmaos)
                falhas_get.extend(falhas_irmaos)
                produtos.extend(extras)
                produtos.sort(key=lambda item: item.mlb)
                total_irmaos = len(extras)
                origens.extend(origens_irmaos)
                avisos.append(
                    f"{total_irmaos} anúncio(s) irmão(s) da mesma família/UP incluído(s) no lote."
                )
                emitir(on_log, "info", avisos[-1])
        else:
            emitir(on_log, "info", "Expansão de irmãos desligada.")

        _aplicar_genero(produtos, origens, genero_forcado)

        planos = montar_planos(
            produtos,
            settings.grouping_unit,
            settings.tentar_family_name_com_vendas,
            genero_forcado=genero_forcado,
            family_name_forcado=settings.family_name_forcado.strip() or None,
        )
        puts_parent = [put for plano in planos for put in plano.puts_parent_pk]
        puts_family = [put for plano in planos for put in plano.puts_family_name]
        puts_familia = [put for plano in planos for put in plano.puts_familia]
        for plano in planos:
            if plano.family_name_referencia:
                emitir(
                    on_log,
                    "info",
                    f'family_name de referência: "{plano.family_name_referencia}".',
                )
        emitir(
            on_log,
            "info",
            (
                f"Plano: {len(puts_parent)} PUT PARENT_PK, "
                f"{len(puts_family)} PUT family_name (/items), "
                f"{len(puts_familia)} PUT família."
            ),
        )

        if puts_parent:
            emitir(on_log, "info", "Executando PUTs de PARENT_PK...")
        resultados_put = await _executar_puts(client, puts_parent, dry_run, on_log)
        if puts_family:
            emitir(on_log, "info", "Executando PUTs de family_name em /items...")
        resultados_put.extend(await _executar_puts(client, puts_family, dry_run, on_log))
        if puts_familia:
            emitir(on_log, "info", "Executando PUTs de /user-products-families...")
        resultados_put.extend(await _executar_puts(client, puts_familia, dry_run, on_log))

        produtos_depois = None
        poll: dict[str, Any] | None = None
        puts_ok = [item for item in resultados_put if item.get("status") == "ok"]
        if not dry_run and puts_ok:
            produtos_depois, falhas_depois, poll = await _aguardar_recalculo(
                client,
                produtos,
                settings.revalidacao_segundos,
                settings.revalidacao_intervalo_segundos,
                on_log,
            )
            if falhas_depois:
                avisos.append(f"{len(falhas_depois)} GET(s) falharam na revalidação.")
                falhas_get.extend(falhas_depois)
                emitir(on_log, "warn", avisos[-1])
            if poll and not poll.get("family_id_mudou"):
                avisos.append(
                    "family_id não mudou no prazo de poll. "
                    "Itens com venda/closed continuam em famílias distintas."
                )
                emitir(on_log, "warn", avisos[-1])
        elif not dry_run:
            avisos.append("Nenhum PUT aceito; revalidação de family_id ignorada.")
            emitir(on_log, "warn", avisos[-1])

        relatorio = montar_relatorio(
            produtos,
            produtos_depois,
            planos,
            resultados_put,
            dry_run,
            poll=poll,
        )
        caminhos = gravar_saidas(relatorio, settings.reports_dir)
        puts_ok_n = sum(1 for item in resultados_put if item.get("status") == "ok")
        puts_erro = sum(1 for item in resultados_put if item.get("status") == "erro")
        quase = relatorio.get("quase_familias") or []
        emitir(
            on_log,
            "ok" if puts_erro == 0 else "warn",
            (
                f"Fim: {relatorio.get('status_agrupamento')} · "
                f"{relatorio.get('resumo')} · "
                f"PUTs ok={puts_ok_n} erro={puts_erro}."
            ),
        )
        return {
            "ok": True,
            "dry_run": dry_run,
            "fonte_origem": resolucao.get("fonte_origem") or "lista_mlbs",
            "total_origem": len(origens),
            "total_lote_inicial": total_lote,
            "total_irmaos_adicionados": total_irmaos,
            "total_get_ok": len(produtos),
            "total_puts_parent_pk": len(puts_parent),
            "total_puts_family_name": len(puts_family),
            "total_puts_familia": len(puts_familia),
            "puts_ok": puts_ok_n,
            "puts_erro": puts_erro,
            "quase_familias": len(quase),
            "poll": poll,
            "falhas_get": falhas_get,
            "avisos": avisos,
            "arquivos": {k: str(v) for k, v in caminhos.items()},
            "relatorio": relatorio,
        }
    finally:
        await client.aclose()
