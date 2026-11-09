"""A small client for the Shopify Admin GraphQL API."""

import asyncio
from typing import Any

import httpx

_TIMEOUT_SECONDS = 30
_MAX_ATTEMPTS = 6
_THROTTLE_WAIT_SECONDS = 2


class ShopifyGraphQLError(RuntimeError):
    """Shopify rejected a query."""


class AdminClient:
    def __init__(self, shop_domain: str, token: str, api_version: str) -> None:
        self._url = f"https://{shop_domain}/admin/api/{api_version}/graphql.json"
        self._headers = {"X-Shopify-Access-Token": token}

    async def query(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                body = await self._send(query, variables)
            except httpx.TransportError:
                if attempt == _MAX_ATTEMPTS:
                    raise
                await asyncio.sleep(attempt * _THROTTLE_WAIT_SECONDS)
                continue
            errors = body.get("errors")
            if not errors:
                data: dict[str, Any] = body["data"]
                return data
            if not _is_throttled(errors) or attempt == _MAX_ATTEMPTS:
                raise ShopifyGraphQLError(str(errors))
            await asyncio.sleep(attempt * _THROTTLE_WAIT_SECONDS)
        raise AssertionError("unreachable")

    async def _send(self, query: str, variables: dict[str, Any] | None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(
                self._url,
                headers=self._headers,
                json={"query": query, "variables": variables or {}},
            )
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result


def _is_throttled(errors: list[dict[str, Any]]) -> bool:
    return any(error.get("extensions", {}).get("code") == "THROTTLED" for error in errors)
