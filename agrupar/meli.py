from __future__ import annotations

import asyncio
from typing import Any

import httpx

from agrupar.config import Settings
from agrupar.modelos import AnuncioOrigem, ProdutoMeli

MELI_BASE = "https://api.mercadolibre.com"


class MeliError(Exception):
    def __init__(self, message: str, status_code: int | None = None, body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def _headers(settings: Settings) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.meli_access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


async def _request_com_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    json_body: dict | None = None,
    params: dict | None = None,
) -> httpx.Response:
    ultimo: httpx.Response | None = None
    for tentativa in range(4):
        response = await client.request(method, url, json=json_body, params=params)
        if response.status_code != 429 and response.status_code < 500:
            return response
        ultimo = response
        await asyncio.sleep(1.5 * (2 ** tentativa))
    assert ultimo is not None
    return ultimo


class MeliClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._semaforo = asyncio.Semaphore(settings.meli_concurrency)
        self._client = httpx.AsyncClient(
            base_url=MELI_BASE,
            headers=_headers(settings),
            timeout=30.0,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_item(self, mlb: str) -> dict[str, Any]:
        async with self._semaforo:
            response = await _request_com_retry(
                self._client,
                "GET",
                f"/items/{mlb}",
                params={"include_internal_attributes": "true"},
            )
        if response.status_code >= 400:
            raise MeliError(
                f"GET {mlb} falhou ({response.status_code})",
                status_code=response.status_code,
                body=_safe_json(response),
            )
        return response.json()

    async def put_item(self, mlb: str, body: dict[str, Any]) -> dict[str, Any]:
        async with self._semaforo:
            response = await _request_com_retry(
                self._client,
                "PUT",
                f"/items/{mlb}",
                json_body=body,
            )
        payload = _safe_json(response)
        if response.status_code >= 400:
            raise MeliError(
                f"PUT {mlb} falhou ({response.status_code})",
                status_code=response.status_code,
                body=payload,
            )
        return payload if isinstance(payload, dict) else {"raw": payload}

    async def put_family(self, family_id: str, body: dict[str, Any]) -> dict[str, Any]:
        async with self._semaforo:
            response = await _request_com_retry(
                self._client,
                "PUT",
                f"/user-products-families/{family_id}",
                json_body=body,
            )
        payload = _safe_json(response)
        if response.status_code >= 400:
            raise MeliError(
                f"PUT family {family_id} falhou ({response.status_code})",
                status_code=response.status_code,
                body=payload,
            )
        return payload if isinstance(payload, dict) else {"raw": payload}

    async def get_family_user_products(self, family_id: str) -> dict[str, Any]:
        async with self._semaforo:
            response = await _request_com_retry(
                self._client,
                "GET",
                f"/user-products-families/{family_id}/user-products",
            )
        payload = _safe_json(response)
        if response.status_code >= 400:
            raise MeliError(
                f"GET family {family_id} user-products falhou ({response.status_code})",
                status_code=response.status_code,
                body=payload,
            )
        return payload if isinstance(payload, dict) else {}

    async def get_site_family(self, site_id: str, family_id: str) -> dict[str, Any]:
        async with self._semaforo:
            response = await _request_com_retry(
                self._client,
                "GET",
                f"/sites/{site_id}/user-products-families/{family_id}",
            )
        payload = _safe_json(response)
        if response.status_code >= 400:
            raise MeliError(
                f"GET sites/{site_id}/user-products-families/{family_id} "
                f"falhou ({response.status_code})",
                status_code=response.status_code,
                body=payload,
            )
        return payload if isinstance(payload, dict) else {}

    async def search_items_by_user_products(
        self,
        seller_id: str,
        user_product_ids: list[str],
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        params = {
            "user_product_id": ",".join(user_product_ids),
            "offset": offset,
            "limit": limit,
        }
        async with self._semaforo:
            response = await _request_com_retry(
                self._client,
                "GET",
                f"/users/{seller_id}/items/search",
                params=params,
            )
        payload = _safe_json(response)
        if response.status_code >= 400:
            raise MeliError(
                f"GET items/search seller={seller_id} falhou ({response.status_code})",
                status_code=response.status_code,
                body=payload,
            )
        return payload if isinstance(payload, dict) else {}

    async def get_itens(
        self,
        origens: list[AnuncioOrigem],
    ) -> tuple[list[ProdutoMeli], list[dict[str, Any]]]:
        produtos: list[ProdutoMeli] = []
        falhas: list[dict[str, Any]] = []

        async def buscar(origem: AnuncioOrigem) -> None:
            try:
                payload = await self.get_item(origem.mlb)
                produto = ProdutoMeli.from_api(payload, origem)
                if produto is None:
                    falhas.append({"mlb": origem.mlb, "erro": "resposta sem id MLB"})
                    return
                produtos.append(produto)
            except MeliError as exc:
                falhas.append(
                    {
                        "mlb": origem.mlb,
                        "erro": str(exc),
                        "status_code": exc.status_code,
                        "body": exc.body,
                    }
                )

        await asyncio.gather(*(buscar(origem) for origem in origens))
        produtos.sort(key=lambda item: item.mlb)
        return produtos, falhas


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text
