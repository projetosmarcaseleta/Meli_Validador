from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from fpdf import FPDF
from fpdf.enums import WrapMode
from fpdf.fonts import FontFace

ROTULO_VIA = {
    "api": "API · PUT PARENT_PK",
    "api_parcial": "API parcial (closed fica de fora)",
    "api_com_risco_409": "API arriscada · 409 se o hash já existe",
    "seller_center": "Seller Center · API não funde o nome",
    "recalculo": "Aguardar recálculo",
    "ja_ok": "Já agrupados",
    "nao": "Não agrupável pela API",
}

ROTULO_VEREDICTO = {
    "ja_agrupados": "Já agrupados",
    "ja_agrupado": "Já agrupado",
    "agrupavel_gender": "Agrupável alinhando GENDER",
    "agrupavel_parent_pk": "Agrupável alinhando PARENT_PK",
    "hash_igual_family_id_diferente": "Hash igual · family_id ainda diferente",
    "possivel_se_alterar_family_name": "Possível se alterar family_name",
    "possivel_se_alterar_parent_e_family_name": "Possível se alterar PARENT_PK e family_name",
    "bloqueado_closed": "Bloqueado · anúncio closed",
    "bloqueado_child_pk": "Bloqueado · CHILD_PK inconsistente",
    "bloqueado_age_group": "Bloqueado · AGE_GROUP",
    "nao_agrupavel": "Não agrupável",
    "isolado": "Isolado no lote",
}

_COR_VIA = {
    "ja_ok": (16, 128, 72),
    "api": (201, 162, 39),
    "api_parcial": (201, 162, 39),
    "recalculo": (201, 162, 39),
    "api_com_risco_409": (194, 102, 32),
    "seller_center": (194, 102, 32),
}

_SUBST = str.maketrans(
    {
        "\u2014": "-",
        "\u2013": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2026": "...",
        "\u00a0": " ",
        "\u2192": "->",
    }
)


def rotulo_via(via: str | None) -> str:
    if not via:
        return "-"
    return ROTULO_VIA.get(via, via)


def rotulo_veredicto(veredicto: str | None) -> str:
    if not veredicto:
        return "-"
    return ROTULO_VEREDICTO.get(veredicto, veredicto)


def nome_pdf_validacao(agora: datetime | None = None) -> str:
    momento = agora or datetime.now()
    return f"validacao-agrupamento-{momento.strftime('%Y%m%d_%H%M%S')}.pdf"


def montar_pdf_validacao(resultado: dict[str, Any]) -> bytes:
    pdf = _PdfValidacao()
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.renderizar(resultado)
    buffer = BytesIO()
    pdf.output(buffer)
    return buffer.getvalue()


def gravar_pdf_validacao(resultado: dict[str, Any], pasta: Path) -> tuple[str, bytes]:
    pdf_bytes = montar_pdf_validacao(resultado)
    nome = nome_pdf_validacao()
    destino = pasta / nome
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(pdf_bytes)
    return nome, pdf_bytes


def _txt(valor: object) -> str:
    texto = "" if valor is None else str(valor)
    texto = texto.translate(_SUBST)
    return texto.encode("latin-1", "replace").decode("latin-1")


def _quebravel(valor: object, cada: int = 12) -> str:
    """Evita token sem espaço mais largo que a coluna do PDF."""
    texto = _txt(valor)
    pedacos: list[str] = []
    for token in texto.split(" "):
        if len(token) <= cada:
            pedacos.append(token)
            continue
        pedacos.append(" ".join(token[i : i + cada] for i in range(0, len(token), cada)))
    return " ".join(pedacos)


def _formatar_pk(mapa: object) -> str:
    if not isinstance(mapa, dict) or not mapa:
        return "-"
    return " · ".join(f"{chave}={valor or '-'}" for chave, valor in mapa.items())


class _PdfValidacao(FPDF):
    def __init__(self) -> None:
        super().__init__(format="A4", unit="mm")
        self.set_auto_page_break(auto=True, margin=16)
        self.set_margins(14, 16, 14)
        self.c_margin = 0.6

    def header(self) -> None:
        self.set_fill_color(11, 12, 15)
        self.rect(0, 0, 210, 12, "F")
        self.set_xy(14, 3.5)
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(232, 197, 71)
        self.cell(120, 5, _txt("MLB23332  ·  Validador de agrupamento  ·  somente GET"))
        self.set_font("Helvetica", "", 8)
        self.set_text_color(180, 180, 180)
        self.cell(0, 5, _txt("Agrupar anúncios"), align="R")
        self.set_y(16)
        self.set_text_color(30, 30, 30)

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 8, _txt(f"Página {self.page_no()}/{{nb}}"), align="C")

    def renderizar(self, resultado: dict[str, Any]) -> None:
        contagens = resultado.get("contagens") or {}
        status = (
            f"{contagens.get('oportunidades') or 0} oportunidade(s)  ·  "
            f"{contagens.get('ja_agrupados') or 0} já agrupado(s)"
        )
        cenario = " · ".join(
            parte
            for parte in (
                f"GENDER hipotético: {resultado['genero_alvo']}" if resultado.get("genero_alvo") else "",
                (
                    f"family_name hipotético: {resultado['family_name_alvo']}"
                    if resultado.get("family_name_alvo")
                    else ""
                ),
            )
            if parte
        )
        resumo = (
            f"{contagens.get('mlbs_ok') or 0} MLB(s) lidos, "
            f"{contagens.get('familias') or 0} família(s) atuais, "
            f"{contagens.get('isolados') or 0} isolado(s)."
        )
        if cenario:
            resumo = f"{resumo} {cenario}."

        self._titulo(status)
        self._paragrafo(resumo, size=10)
        self._stats(contagens)
        self._avisos(resultado)
        self._secao("Oportunidades de agrupamento")
        self._cards(
            resultado.get("oportunidades") or [],
            vazio="Nenhum produto no lote está partido em famílias distintas.",
        )
        self._secao("Já na mesma família")
        self._cards(
            resultado.get("ja_agrupados") or [],
            vazio="Nenhum grupo com family_id compartilhado neste lote.",
        )
        self._secao("Famílias atuais")
        self._tabela_familias(resultado.get("familias_atuais") or [])
        self._secao("Isolados no lote")
        self._isolados(resultado.get("isolados") or [])
        self._secao("Detalhe por MLB")
        self._tabela_mlbs(resultado.get("itens") or [])
        self._secao("Texto completo")
        self._pre(resultado.get("texto") or "(sem texto)")

    def _titulo(self, texto: str) -> None:
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(20, 20, 20)
        self.multi_cell(0, 8, _quebravel(texto, 40), wrapmode=WrapMode.CHAR)
        self.ln(1)

    def _paragrafo(self, texto: str, size: int = 10) -> None:
        self.set_font("Helvetica", "", size)
        self.set_text_color(60, 60, 60)
        self.multi_cell(0, 5, _quebravel(texto, 40), wrapmode=WrapMode.CHAR)
        self.ln(1)

    def _secao(self, titulo: str) -> None:
        self.ln(3)
        if self.get_y() > 260:
            self.add_page()
        self.set_font("Helvetica", "B", 12)
        self.set_text_color(20, 20, 20)
        self.cell(0, 7, _txt(titulo), new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(232, 197, 71)
        y = self.get_y()
        self.line(14, y, 196, y)
        self.ln(3)

    def _stats(self, contagens: dict[str, Any]) -> None:
        bloqueados = (contagens.get("bloqueados") or 0) + (contagens.get("isolados") or 0)
        itens = [
            ("Agrupáveis via API", contagens.get("agrupaveis_api")),
            ("Se alterar parâmetro", contagens.get("dependem_parametro")),
            ("Já agrupados", contagens.get("ja_agrupados")),
            ("Bloqueados / isolados", bloqueados),
        ]
        largura = 44.5
        altura = 16
        x0 = self.get_x()
        y0 = self.get_y()
        for i, (rotulo, valor) in enumerate(itens):
            x = x0 + i * (largura + 2)
            self.set_xy(x, y0)
            self.set_fill_color(245, 245, 247)
            self.set_draw_color(42, 46, 56)
            self.rect(x, y0, largura, altura, "DF")
            self.set_xy(x + 2, y0 + 2)
            self.set_font("Helvetica", "", 7)
            self.set_text_color(110, 110, 110)
            self.cell(largura - 4, 4, _txt(rotulo.upper()))
            self.set_xy(x + 2, y0 + 8)
            self.set_font("Helvetica", "B", 12)
            self.set_text_color(20, 20, 20)
            self.cell(largura - 4, 6, _txt(valor if valor is not None else "-"))
        self.set_y(y0 + altura + 4)

    def _avisos(self, resultado: dict[str, Any]) -> None:
        avisos = [str(item) for item in (resultado.get("avisos") or []) if item]
        for falha in resultado.get("falhas_get") or []:
            avisos.append(f"GET {falha.get('mlb') or '?'}: {falha.get('erro') or 'falha'}")
        if not avisos:
            return
        self.set_fill_color(255, 248, 230)
        self.set_draw_color(201, 162, 39)
        self.set_font("Helvetica", "", 9)
        self.set_text_color(120, 80, 10)
        self.multi_cell(0, 5, _quebravel(" ".join(avisos), 40), fill=True, border=1, wrapmode=WrapMode.CHAR)
        self.ln(3)

    def _cards(self, blocos: list[dict[str, Any]], vazio: str) -> None:
        if not blocos:
            self._paragrafo(vazio, size=9)
            return
        for bloco in blocos:
            self._card(bloco)

    def _card(self, bloco: dict[str, Any]) -> None:
        via = bloco.get("via") or ""
        cor = _COR_VIA.get(via, (180, 50, 50))
        params = ", ".join(bloco.get("parametros_a_alterar") or []) or "-"
        linhas = [
            rotulo_via(via).upper(),
            bloco.get("titulo") or "",
            rotulo_veredicto(bloco.get("veredicto")),
            bloco.get("motivo") or "",
            f"Parâmetros a alterar: {params}",
        ]
        if bloco.get("cenario_hipotetico"):
            linhas.append(str(bloco["cenario_hipotetico"]))
        for bloqueio in bloco.get("bloqueios") or []:
            linhas.append(f"- {bloqueio}")
        for fam in bloco.get("familias") or []:
            linhas.append(
                f"{fam.get('n') or 0}  ·  {fam.get('family_name') or '-'}  ·  "
                f"id={fam.get('family_id') or '-'}  ·  vendas={fam.get('vendas') or 0}"
            )
        for divergencia in bloco.get("divergencias") or []:
            valores = []
            for valor, mlbs in (divergencia.get("valores") or {}).items():
                valores.append(f"{valor} ({len(mlbs or [])})")
            linhas.append(f"{divergencia.get('campo')}: {' · '.join(valores)}")
        mlbs = bloco.get("mlbs") or []
        if mlbs:
            linhas.append(" ".join(str(mlb) for mlb in mlbs))

        texto = _quebravel("\n".join(str(linha) for linha in linhas if linha), cada=18)
        self.set_font("Helvetica", "", 8)
        largura_texto = max(self.epw - 8, 40)
        altura = (
            self.multi_cell(
                w=largura_texto,
                h=4.2,
                text=texto,
                dry_run=True,
                output="HEIGHT",
                wrapmode=WrapMode.CHAR,
            )
            + 4
        )
        if self.get_y() + altura > 275:
            self.add_page()
        x = self.l_margin
        y = self.get_y()
        self.set_fill_color(250, 250, 252)
        self.set_draw_color(42, 46, 56)
        self.rect(x, y, self.epw, altura, "DF")
        self.set_fill_color(*cor)
        self.rect(x, y, 2.2, altura, "F")
        self.set_xy(x + 5, y + 2)
        self.set_text_color(30, 30, 30)
        self.multi_cell(w=largura_texto, h=4.2, text=texto, wrapmode=WrapMode.CHAR)
        self.set_y(y + altura + 3)

    def _tabela_familias(self, familias: list[dict[str, Any]]) -> None:
        if not familias:
            self._paragrafo("Nenhuma família neste lote.", size=9)
            return
        cabecalho = ("Qtd", "family_name", "family_id", "Vendas", "Gênero", "LINE")
        linhas = [
            (
                str(bloco.get("n") or 0),
                _quebravel(bloco.get("family_name") or "", 18),
                _quebravel(bloco.get("family_id") or "-", 10),
                str(bloco.get("vendas") or 0),
                _quebravel(", ".join(bloco.get("gender") or []), 12),
                _quebravel(", ".join(bloco.get("line") or []), 12),
            )
            for bloco in familias
        ]
        self._tabela(cabecalho, linhas, (12, 58, 38, 16, 30, 28))

    def _tabela_mlbs(self, itens: list[dict[str, Any]]) -> None:
        if not itens:
            self._paragrafo("Sem MLB (GET falhou ou lote vazio).", size=9)
            return
        cabecalho = ("MLB", "Status", "Vendas", "GENDER", "LINE", "family_id", "family_name", "Veredicto")
        linhas = [
            (
                _quebravel(item.get("mlb") or "", 10),
                _quebravel(item.get("status") or "-", 8),
                str(item.get("vendas") or 0),
                _quebravel(item.get("gender") or "-", 10),
                _quebravel(item.get("line") or "-", 10),
                _quebravel(item.get("family_id") or "-", 8),
                _quebravel(item.get("family_name") or "-", 14),
                _quebravel(rotulo_veredicto(item.get("veredicto")), 12),
            )
            for item in itens
        ]
        self._tabela(cabecalho, linhas, (24, 18, 16, 22, 22, 28, 30, 22), size=6.5)
        self.ln(2)
        for item in itens:
            parent = _formatar_pk(item.get("parent_pk"))
            child = _formatar_pk(item.get("child_pk"))
            bloco = (
                f"{item.get('mlb') or '-'}\n"
                f"PARENT_PK {parent}\n"
                f"CHILD_PK {child}"
            )
            self._paragrafo(bloco, size=7)

    def _tabela(
        self,
        cabecalho: tuple[str, ...],
        linhas: list[tuple[str, ...]],
        larguras: tuple[int, ...],
        size: int = 8,
    ) -> None:
        self.set_font("Helvetica", "", size)
        estilo_cabeca = FontFace(emphasis="BOLD", color=(80, 80, 80), fill_color=(245, 245, 247))
        with self.table(
            col_widths=larguras,
            width=self.epw,
            text_align="LEFT",
            line_height=4.2,
            markdown=False,
            first_row_as_headings=True,
            headings_style=estilo_cabeca,
            wrapmode=WrapMode.CHAR,
            padding=0.8,
        ) as table:
            row = table.row()
            for titulo in cabecalho:
                row.cell(_quebravel(titulo, 8))
            for valores in linhas:
                row = table.row()
                for valor in valores:
                    row.cell(_quebravel(valor, 10))

    def _isolados(self, isolados: list[dict[str, Any]]) -> None:
        if not isolados:
            self._paragrafo("Nenhum isolado.", size=9)
            return
        self.set_font("Helvetica", "", 9)
        self.set_text_color(40, 40, 40)
        for item in isolados:
            linha = (
                f"{item.get('mlb')}  ·  {item.get('brand') or '?'} {item.get('model') or '?'}  ·  "
                f"{item.get('motivo') or ''}"
            )
            self.multi_cell(0, 5, _quebravel(linha, 24), wrapmode=WrapMode.CHAR)
        self.ln(1)

    def _pre(self, texto: str) -> None:
        self.set_fill_color(248, 248, 250)
        self.set_font("Courier", "", 7)
        self.set_text_color(40, 40, 40)
        self.multi_cell(0, 4, _quebravel(texto, 32), fill=True, border=1, wrapmode=WrapMode.CHAR)
