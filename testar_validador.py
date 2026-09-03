"""
testar_validador.py - Testa a auditoria de Catálogo vs Tradicional diretamente pelo terminal.

Uso:
  py testar_validador.py SEU_TOKEN MLB1 MLB2 ...
  py testar_validador.py SEU_TOKEN SKU1 SKU2 ...
"""

import sys
import json
import os
from dotenv import load_dotenv

load_dotenv()
import api
import exporter

def main():
    args = sys.argv[1:]
    token = ""
    itens = []

    if args:
        token = args[0]
        itens = args[1:]

    if not token:
        token = os.environ.get("MELI_ACCESS_TOKEN", "").strip()

    if not token:
        token = input("Cole o token do Mercado Livre (APP_USR-...): ").strip()

    if not itens:
        print("\nDigite os MLBs ou SKUs para testar (separados por espaço ou vírgula):")
        raw = input("> ").strip()
        itens = [x.strip() for x in raw.replace(",", " ").split() if x.strip()]

    if not itens:
        print("Nenhum item informado.")
        return

    print("\n1. Validando token do Mercado Livre...")
    user = api.validate_token(token)
    if not user or not user.get("id"):
        print("❌ Token inválido ou expirado!")
        return
    print(f"✅ Token válido! Usuário: {user.get('nickname')} (ID: {user.get('id')})")

    print(f"\n2. Executando auditoria de Catálogo vs Tradicional para {len(itens)} item(ns)...")
    res = exporter.process_skus_for_catalog_audit(itens, token)

    summary = res.get("summary", {})
    print("\n" + "=" * 60)
    print("📊 RESUMO DA AUDITORIA:")
    print(f"  Total de Itens:   {summary.get('total', 0)}")
    print(f"  OK (Sem Diverg.): {summary.get('ok', 0)}")
    print(f"  Divergentes:      {summary.get('divergent', 0)}")
    print(f"  Atenção:          {summary.get('attention', 0)}")
    print(f"  Erros:            {summary.get('errors', 0)}")
    print("=" * 60)

    items = res.get("items", [])
    for idx, item in enumerate(items, 1):
        print(f"\n[{idx}] SKU/MLB: {item.get('sku')}")
        print(f"    Status Geral:   {item.get('status_geral')}")
        print(f"    MLB Catálogo:   {item.get('cat_mlb') or 'NÃO ENCONTRADO'} (Status: {item.get('cat_status')})")
        print(f"    MLB Tradic.:    {item.get('trad_mlb') or 'NÃO ENCONTRADO'} (Status: {item.get('trad_status')})")
        
        divs = item.get("divergencias") or []
        if divs:
            print("    ⚠️ Divergências Detectadas:")
            for d in divs:
                print(f"       - {d}")
        else:
            print("    ✅ Nenhuma divergência detectada.")

if __name__ == "__main__":
    main()
