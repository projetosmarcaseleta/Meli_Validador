from __future__ import annotations

import argparse
import asyncio
import json
import sys

from agrupar.config import Settings
from agrupar.pipeline import executar


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Normaliza PARENT_PK e family_name de anúncios MLB23332 "
            "para agrupar User Products no Mercado Livre."
        )
    )
    parser.add_argument(
        "mlbs",
        nargs="*",
        help="MLBs (MLB123...) e/ou SKUs. Se omitido, lê data/mlbs.txt.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Envia os PUTs. Sem esta flag o modo é dry-run (só gera o plano).",
    )
    parser.add_argument(
        "--family-name",
        default=None,
        help="Força o family_name de referência (único nome-alvo do lote).",
    )
    parser.add_argument(
        "--tentar-family-name-com-vendas",
        action="store_true",
        help="Tenta PUT de family_name mesmo quando o UP já teve venda.",
    )
    parser.add_argument(
        "--sem-irmaos",
        action="store_true",
        help="Não busca itens da mesma família/UP que estejam fora da lista.",
    )
    parser.add_argument(
        "--mesmo-genero-unico",
        action="store_true",
        help="Um único voto de MODEL/BRAND por gênero (não quebra por modelo).",
    )
    parser.add_argument(
        "--genero",
        choices=["Masculino", "Feminino", "Unissex"],
        default=None,
        help="Força GENDER (PARENT_PK) em todo o lote.",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Abre a interface local (token, MLBs e SKUs pela tela, com logs).",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host da interface. Padrão: 127.0.0.1",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Porta da interface. Padrão: 8765",
    )
    parser.add_argument(
        "--revalidacao",
        type=int,
        default=None,
        help="Segundos de espera após cada onda de PUT. Padrão: REVALIDACAO_SEGUNDOS.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.web:
        import uvicorn

        from agrupar.web import app

        print(f"Interface: http://{args.host}:{args.port}")
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
        return

    settings = Settings()
    if args.mesmo_genero_unico:
        settings.grouping_unit = "gender"
    if args.genero:
        settings.genero_forcado = args.genero
        settings.grouping_unit = "gender"
    if args.family_name:
        settings.family_name_forcado = args.family_name.strip()
        settings.grouping_unit = "gender"
    if args.tentar_family_name_com_vendas:
        settings.tentar_family_name_com_vendas = True
    if args.sem_irmaos:
        settings.expandir_irmaos = False
    if args.revalidacao is not None:
        settings.revalidacao_segundos = args.revalidacao

    resultado = asyncio.run(executar(settings, aplicar=args.apply, mlbs=args.mlbs or None))
    if not resultado.get("ok"):
        print(resultado.get("error", "Falha"), file=sys.stderr)
        for item in resultado.get("faltando", []):
            print(f"- {item}", file=sys.stderr)
        sys.exit(1)

    resumo = {
        "dry_run": resultado["dry_run"],
        "fonte_origem": resultado["fonte_origem"],
        "grouping_unit": settings.grouping_unit,
        "total_origem": resultado["total_origem"],
        "total_lote_inicial": resultado.get("total_lote_inicial"),
        "total_irmaos_adicionados": resultado.get("total_irmaos_adicionados"),
        "total_get_ok": resultado["total_get_ok"],
        "total_puts_parent_pk": resultado["total_puts_parent_pk"],
        "total_puts_family_name": resultado["total_puts_family_name"],
        "total_puts_familia": resultado.get("total_puts_familia"),
        "puts_ok": resultado.get("puts_ok"),
        "puts_erro": resultado.get("puts_erro"),
        "quase_familias": resultado.get("quase_familias"),
        "poll": resultado.get("poll"),
        "status_agrupamento": resultado["relatorio"]["status_agrupamento"],
        "resumo": resultado["relatorio"]["resumo"],
        "avisos": resultado["avisos"],
        "falhas_get": len(resultado["falhas_get"]),
        "arquivos": resultado["arquivos"],
    }
    print(json.dumps(resumo, ensure_ascii=False, indent=2))
    if resultado["avisos"]:
        print("\nAvisos:", file=sys.stderr)
        for aviso in resultado["avisos"]:
            print(f"- {aviso}", file=sys.stderr)


if __name__ == "__main__":
    main()
