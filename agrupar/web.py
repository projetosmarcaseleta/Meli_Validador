from __future__ import annotations



import asyncio

import json

from pathlib import Path

from typing import Any, Awaitable, Callable



from fastapi import FastAPI, HTTPException

from fastapi.responses import FileResponse, StreamingResponse

from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel, Field



from agrupar.config import Settings

from agrupar.genero import GENEROS_VALIDOS

from agrupar.logs import emitir, resumo_para_tela

from agrupar.origem import parse_entrada

from agrupar.pipeline import executar

from agrupar.validador import executar_validacao

from agrupar.pdf_validador import gravar_pdf_validacao



STATIC_DIR = Path(__file__).resolve().parent / "static"



TrabalhoStream = Callable[[Callable[[dict[str, Any]], None]], Awaitable[dict[str, Any]]]





class ExecutarPedido(BaseModel):

    token: str = ""

    mlbs: str = ""

    aplicar: bool = False

    genero: str = ""

    family_name: str = ""

    expandir_irmaos: bool = True

    tentar_family_name_com_vendas: bool = False

    revalidacao_segundos: int = Field(default=45, ge=0, le=300)





def montar_execucao(pedido: ExecutarPedido) -> tuple[Settings, list[str], dict[str, str]]:

    entrada = parse_entrada(pedido.mlbs)
    mlbs = [pedido.mlbs] if not entrada.vazia else []

    notas: dict[str, str] = {}

    settings = Settings()

    token = pedido.token.strip()

    if token:

        settings.meli_access_token = token

        notas["token"] = "Token informado na tela (não é gravado em log)."

    elif settings.meli_access_token.strip():

        notas["token"] = "Token lido do ambiente local (.env). O valor não aparece nos logs."

    else:

        notas["token"] = "Nenhum token informado."



    genero = pedido.genero.strip()

    if genero and genero not in GENEROS_VALIDOS:

        raise ValueError(f"Gênero inválido: {genero}")

    if genero:

        settings.genero_forcado = genero

        settings.grouping_unit = "gender"

    if pedido.family_name.strip():

        settings.family_name_forcado = pedido.family_name.strip()

        settings.grouping_unit = "gender"

    settings.expandir_irmaos = pedido.expandir_irmaos

    settings.tentar_family_name_com_vendas = pedido.tentar_family_name_com_vendas

    settings.revalidacao_segundos = pedido.revalidacao_segundos

    return settings, mlbs, notas





def _ndjson(trava: asyncio.Lock, trabalho: TrabalhoStream) -> StreamingResponse:

    fila: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()



    def on_log(evento: dict[str, Any]) -> None:

        fila.put_nowait(evento)



    async def rodar() -> None:

        async with trava:

            try:

                resultado = await trabalho(on_log)

                fila.put_nowait({"type": "done", "resultado": resultado})

            except Exception as exc:

                emitir(on_log, "error", f"Falha inesperada: {exc}")

                fila.put_nowait(

                    {

                        "type": "done",

                        "resultado": {

                            "ok": False,

                            "error": str(exc),

                            "faltando": [],

                        },

                    }

                )

            finally:

                fila.put_nowait(None)



    async def gerar():

        tarefa = asyncio.create_task(rodar())

        try:

            while True:

                evento = await fila.get()

                if evento is None:

                    break

                yield json.dumps(evento, ensure_ascii=False) + "\n"

        finally:

            await tarefa



    return StreamingResponse(

        gerar(),

        media_type="application/x-ndjson",

        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},

    )





def criar_app() -> FastAPI:

    app = FastAPI(title="Agrupar anúncios Tubarão", docs_url=None, redoc_url=None)

    trava = asyncio.Lock()



    @app.get("/")

    async def index() -> FileResponse:

        return FileResponse(STATIC_DIR / "index.html")



    @app.get("/api/relatorios/{nome}")

    async def baixar_relatorio(nome: str) -> FileResponse:

        if Path(nome).name != nome or not nome:

            raise HTTPException(status_code=400, detail="Nome de arquivo inválido.")

        pasta = Settings().reports_dir.resolve()

        alvo = (pasta / nome).resolve()

        try:

            alvo.relative_to(pasta)

        except ValueError as exc:

            raise HTTPException(status_code=400, detail="Nome de arquivo inválido.") from exc

        if not alvo.is_file():

            raise HTTPException(status_code=404, detail="Relatório não encontrado.")

        return FileResponse(
            alvo,
            filename=nome,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{nome}"'},
        )



    @app.post("/api/executar")

    async def api_executar(pedido: ExecutarPedido) -> StreamingResponse:

        if trava.locked():

            raise HTTPException(status_code=409, detail="Já existe uma execução em andamento.")

        try:

            settings, mlbs, notas = montar_execucao(pedido)

        except ValueError as exc:

            raise HTTPException(status_code=400, detail=str(exc)) from exc



        async def trabalho(on_log: Callable[[dict[str, Any]], None]) -> dict[str, Any]:

            emitir(on_log, "info", notas["token"])

            resultado = await executar(

                settings,

                aplicar=pedido.aplicar,

                mlbs=mlbs,

                on_log=on_log,

            )

            resumo = resumo_para_tela(resultado)

            for arquivo in resumo.get("arquivos") or []:

                emitir(on_log, "ok", f"Relatório salvo: {arquivo['nome']}")

            return resumo



        return _ndjson(trava, trabalho)



    @app.post("/api/validar")

    async def api_validar(pedido: ExecutarPedido) -> StreamingResponse:

        if trava.locked():

            raise HTTPException(status_code=409, detail="Já existe uma execução em andamento.")

        try:

            settings, mlbs, notas = montar_execucao(pedido)

        except ValueError as exc:

            raise HTTPException(status_code=400, detail=str(exc)) from exc



        async def trabalho(on_log: Callable[[dict[str, Any]], None]) -> dict[str, Any]:

            emitir(on_log, "info", notas["token"])

            return await executar_validacao(settings, mlbs, on_log=on_log)



        return _ndjson(trava, trabalho)



    @app.post("/api/validar/pdf")

    async def api_validar_pdf(resultado: dict[str, Any]) -> dict[str, Any]:

        mlbs_lidos = (resultado.get("contagens") or {}).get("mlbs_ok", 0) if resultado else 0

        if not resultado or resultado.get("ok") is False or mlbs_lidos < 1:

            raise HTTPException(

                status_code=400,

                detail="Não há anúncios lidos para exportar. Valide com um token válido.",

            )

        pasta = Settings().reports_dir.resolve()

        try:

            nome, _ = await asyncio.to_thread(gravar_pdf_validacao, resultado, pasta)

        except Exception as exc:

            raise HTTPException(

                status_code=500,

                detail=f"Falha ao gerar PDF: {exc}",

            ) from exc

        return {

            "ok": True,

            "nome": nome,

            "url": f"/api/relatorios/{nome}",

        }



    if STATIC_DIR.exists():

        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    return app





app = criar_app()





def main() -> None:

    import uvicorn



    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")





if __name__ == "__main__":

    main()


