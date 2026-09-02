from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

OnLog = Callable[[dict[str, Any]], None] | None


def emitir(on_log: OnLog, level: str, message: str, **extra: Any) -> None:
    if on_log is None:
        return
    evento: dict[str, Any] = {
        "type": "log",
        "level": level,
        "message": message,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    for chave, valor in extra.items():
        if valor is not None:
            evento[chave] = valor
    on_log(evento)


def detalhe_body(body: object) -> str:
    if not isinstance(body, dict):
        return ""
    partes: list[str] = []
    family_name = body.get("family_name")
    if family_name:
        partes.append(f'family_name="{family_name}"')
    for attr in body.get("attributes") or []:
        if not isinstance(attr, dict):
            continue
        attr_id = attr.get("id") or "?"
        valor = attr.get("value_name") or attr.get("value_id") or ""
        partes.append(f"{attr_id}={valor}")
    return " · ".join(partes)


def detalhe_erro_api(resposta: object) -> str:
    if not isinstance(resposta, dict):
        return str(resposta or "")
    erro = resposta.get("error") or ""
    mensagem = resposta.get("message") or ""
    cause = resposta.get("cause")
    partes = [parte for parte in (erro, mensagem) if parte]
    texto = " · ".join(dict.fromkeys(partes))
    if cause is not None and str(cause) not in texto:
        texto = f"{texto} (cause {cause})" if texto else f"cause {cause}"
    return texto


def detalhe_put(registro: dict[str, Any]) -> str:
    tipo = registro.get("request_type") or "put"
    mlb = registro.get("mlb") or ""
    status = registro.get("status") or "?"
    corpo = detalhe_body(registro.get("body"))
    prefixo = f"{tipo} {mlb}".strip()
    if status == "planejado":
        return f"[plano] {prefixo}" + (f" · {corpo}" if corpo else "")
    if status == "ok":
        return f"[ok] {prefixo}" + (f" · {corpo}" if corpo else "")
    codigo = registro.get("status_code")
    api = detalhe_erro_api(registro.get("resposta"))
    http = f"HTTP {codigo}" if codigo else "erro"
    return f"[erro] {prefixo} · {http}" + (f" · {api}" if api else "") + (
        f" · {corpo}" if corpo else ""
    )


def arquivos_para_tela(arquivos: dict[str, Any] | None) -> list[dict[str, str]]:
    rotulos = {
        "json": "JSON",
        "csv": "CSV",
        "mlbs_por_family_name": "TXT",
    }
    saida: list[dict[str, str]] = []
    for tipo, caminho in (arquivos or {}).items():
        nome = Path(str(caminho)).name
        if not nome:
            continue
        saida.append(
            {
                "tipo": str(tipo),
                "rotulo": rotulos.get(str(tipo), str(tipo)),
                "nome": nome,
                "url": f"/api/relatorios/{nome}",
            }
        )
    return saida


def resumo_para_tela(resultado: dict[str, Any]) -> dict[str, Any]:
    from agrupar.relatorio import texto_listagem_family_name

    relatorio = resultado.get("relatorio") or {}
    listagem = []
    for bloco in relatorio.get("listagem_family_name") or []:
        listagem.append(
            {
                "n": bloco.get("n"),
                "family_name": bloco.get("family_name"),
                "vendas": bloco.get("vendas"),
                "closed": bloco.get("closed"),
                "family_ids": bloco.get("family_ids"),
                "gender": bloco.get("gender"),
                "da_para_juntar": bloco.get("da_para_juntar"),
                "quantidade_puts": bloco.get("quantidade_puts"),
                "quantidade_puts_ok": bloco.get("quantidade_puts_ok"),
                "quantidade_puts_erro": bloco.get("quantidade_puts_erro"),
                "quantidade_que_mudaram_family_id": bloco.get(
                    "quantidade_que_mudaram_family_id"
                ),
                "fluxos_family_id": bloco.get("fluxos_family_id") or [],
                "mlbs": bloco.get("mlbs"),
            }
        )
    puts_erro: list[dict[str, Any]] = []
    for put in relatorio.get("puts") or []:
        if put.get("status") != "erro":
            continue
        puts_erro.append(
            {
                "mlb": put.get("mlb"),
                "request_type": put.get("request_type"),
                "status_code": put.get("status_code"),
                "mensagem_api": detalhe_erro_api(put.get("resposta")),
                "body": detalhe_body(put.get("body")),
            }
        )
    detalhe_mlbs = []
    for item in relatorio.get("detalhe_mlbs") or []:
        detalhe_mlbs.append(
            {
                "mlb": item.get("mlb"),
                "status_depois": item.get("status_depois"),
                "sold_quantity": item.get("sold_quantity"),
                "gender_antes": item.get("gender_antes"),
                "gender_depois": item.get("gender_depois"),
                "gender_mudou": item.get("gender_mudou"),
                "color": item.get("color"),
                "size": item.get("size"),
                "family_id_antes": item.get("family_id_antes"),
                "family_id_depois": item.get("family_id_depois"),
                "family_id_mudou": item.get("family_id_mudou"),
                "family_name_antes": item.get("family_name_antes"),
                "family_name_depois": item.get("family_name_depois"),
                "family_name_mudou": item.get("family_name_mudou"),
                "parent_pk": item.get("parent_pk") or {},
                "child_pk": item.get("child_pk") or {},
                "puts": item.get("puts") or [],
                "puts_ok": item.get("puts_ok"),
                "puts_erro": item.get("puts_erro"),
                "puts_planejado": item.get("puts_planejado"),
            }
        )
    resultado_rel = relatorio.get("resultado") or {}
    texto = ""
    if relatorio:
        texto = texto_listagem_family_name(
            relatorio, gerado_em=relatorio.get("gerado_em")
        )
    return {
        "ok": resultado.get("ok"),
        "error": resultado.get("error"),
        "faltando": resultado.get("faltando") or [],
        "dry_run": resultado.get("dry_run"),
        "gerado_em": relatorio.get("gerado_em"),
        "total_origem": resultado.get("total_origem"),
        "total_lote_inicial": resultado.get("total_lote_inicial"),
        "total_irmaos_adicionados": resultado.get("total_irmaos_adicionados"),
        "total_get_ok": resultado.get("total_get_ok"),
        "total_puts_parent_pk": resultado.get("total_puts_parent_pk"),
        "total_puts_family_name": resultado.get("total_puts_family_name"),
        "total_puts_familia": resultado.get("total_puts_familia"),
        "puts_ok": resultado.get("puts_ok"),
        "puts_erro": resultado.get("puts_erro"),
        "puts_planejado": resultado_rel.get("puts_planejado"),
        "quase_familias": resultado.get("quase_familias"),
        "poll": resultado.get("poll"),
        "avisos": resultado.get("avisos") or [],
        "falhas_get": resultado.get("falhas_get") or [],
        "status_agrupamento": relatorio.get("status_agrupamento"),
        "resumo": relatorio.get("resumo"),
        "familias_antes": (relatorio.get("antes") or {}).get("total_familias"),
        "familias_depois": (relatorio.get("depois") or {}).get("total_familias"),
        "reducao_familias": resultado_rel.get("reducao_familias"),
        "mudaram_family_id": resultado_rel.get("total_produtos_que_mudaram_de_familia"),
        "fluxos_family_id": resultado_rel.get("fluxos_family_id") or [],
        "listagem_family_name": listagem,
        "puts_erro_detalhe": puts_erro,
        "detalhe_mlbs": detalhe_mlbs,
        "texto": texto,
        "arquivos": arquivos_para_tela(resultado.get("arquivos")),
    }
