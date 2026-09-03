"""Diagnóstico: como o auditor resolve SKU -> MLB Catálogo/Tradicional."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "ml_exporter"
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv(ROOT.parent / ".env")
load_dotenv(ROOT.parent.parent / ".env")

from config import (
    ANYMARKET_DB_HOST,
    ANYMARKET_DB_NAME,
    ANYMARKET_DB_PASSWORD,
    ANYMARKET_DB_PORT,
    ANYMARKET_DB_SSLMODE,
    ANYMARKET_DB_USER,
)
from exporter import _resolve_skus_from_anymarket_db, process_skus_for_catalog_audit
from api import search_items_by_seller_sku, validate_token, get_products_batch

TEST_SKU = "238601800"
TEST_MLB = "MLB7520875292"


def q_db_by_sku(sku: str):
    import psycopg2
    from psycopg2 import sql as psql

    with psycopg2.connect(
        host=ANYMARKET_DB_HOST,
        port=ANYMARKET_DB_PORT,
        dbname=ANYMARKET_DB_NAME,
        user=ANYMARKET_DB_USER.strip("'\""),
        password=ANYMARKET_DB_PASSWORD.strip("'\"'"),
        sslmode=ANYMARKET_DB_SSLMODE,
        connect_timeout=15,
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT sm.sku_in_marketplace, sm.id_in_marketplace, sm.is_catalog, sm.status_in_marketplace
                FROM anymarket_prd.sku_marketplace sm
                WHERE sm.market_place = 'MERCADO_LIVRE'
                  AND sm.sku_in_marketplace = %s
                ORDER BY sm.is_catalog DESC
                """,
                (sku,),
            )
            by_sku = cur.fetchall()

            cur.execute(
                """
                SELECT sm.sku_in_marketplace, sm.id_in_marketplace, sm.is_catalog, sm.status_in_marketplace
                FROM anymarket_prd.sku_marketplace sm
                WHERE sm.market_place = 'MERCADO_LIVRE'
                  AND sm.id_in_marketplace = %s
                ORDER BY sm.is_catalog DESC
                """,
                (TEST_MLB,),
            )
            by_mlb = cur.fetchall()
    return by_sku, by_mlb


def main():
    token = os.environ.get("MELI_ACCESS_TOKEN", "").strip()
    print("=== CONFIG ===")
    print(f"DB_HOST set: {bool(ANYMARKET_DB_HOST)}")
    print(f"DB_USER set: {bool(ANYMARKET_DB_USER)}")
    print(f"MELI token set: {bool(token)}")

    print("\n=== DB: sku_in_marketplace = 238601800 ===")
    try:
        by_sku, by_mlb = q_db_by_sku(TEST_SKU)
        print(f"rows by SKU: {len(by_sku)}")
        for r in by_sku:
            print(" ", r)
        print(f"\nrows by MLB {TEST_MLB}: {len(by_mlb)}")
        for r in by_mlb:
            print(" ", r)
    except Exception as exc:
        print(f"DB ERROR: {type(exc).__name__}: {exc}")

    print("\n=== _resolve_skus_from_anymarket_db(['238601800']) ===")
    m = _resolve_skus_from_anymarket_db([TEST_SKU])
    print(json.dumps(m, indent=2, ensure_ascii=False))

    print("\n=== _resolve_skus_from_anymarket_db(['MLB7520875292']) — input errado (MLB como SKU) ===")
    m2 = _resolve_skus_from_anymarket_db([TEST_MLB])
    print(json.dumps(m2, indent=2, ensure_ascii=False))

    if token:
        user = validate_token(token)
        print(f"\n=== ML API user: {user.get('nickname')} id={user.get('id')} ===")
        mlbs = search_items_by_seller_sku(user.get("id"), TEST_SKU, token)
        print(f"search_items_by_seller_sku('{TEST_SKU}'): {mlbs}")
        batch = get_products_batch([TEST_MLB], token)
        if batch:
            p = batch.get(TEST_MLB, {})
            print(f"get_products_batch('{TEST_MLB}'): title={p.get('title','?')[:60]} catalog_listing={p.get('catalog_listing')}")
        else:
            print(f"get_products_batch('{TEST_MLB}'): empty")

        print("\n=== process_skus_for_catalog_audit(['238601800']) ===")
        audit = process_skus_for_catalog_audit([TEST_SKU], token)
        print(json.dumps({"summary": audit["summary"], "errors": audit["errors"], "first_item": audit["items"][0] if audit["items"] else None}, indent=2, ensure_ascii=False)[:3000])
    else:
        print("\n(skip ML API — MELI_ACCESS_TOKEN not in env)")


if __name__ == "__main__":
    main()
