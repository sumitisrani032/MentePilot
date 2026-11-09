import httpx
import pytest
import respx

from shopchat.shopify import graphql
from shopchat.shopify.graphql import AdminClient, ShopifyGraphQLError

URL = "https://a.myshopify.com/admin/api/2026-10/graphql.json"
THROTTLED = {"errors": [{"message": "Throttled", "extensions": {"code": "THROTTLED"}}]}


def _client() -> AdminClient:
    return AdminClient("a.myshopify.com", "token", "2026-10")


@respx.mock
async def test_throttled_query_waits_and_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_wait(_: float) -> None:
        return None

    monkeypatch.setattr(graphql.asyncio, "sleep", no_wait)
    respx.post(URL).mock(
        side_effect=[
            httpx.Response(200, json=THROTTLED),
            httpx.Response(200, json={"data": {"shop": {"id": "1"}}}),
        ]
    )

    assert await _client().query("{ shop { id } }") == {"shop": {"id": "1"}}


@respx.mock
async def test_network_error_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_wait(_: float) -> None:
        return None

    monkeypatch.setattr(graphql.asyncio, "sleep", no_wait)
    respx.post(URL).mock(
        side_effect=[
            httpx.ReadTimeout("slow"),
            httpx.Response(200, json={"data": {"shop": {"id": "1"}}}),
        ]
    )

    assert await _client().query("{ shop { id } }") == {"shop": {"id": "1"}}


@respx.mock
async def test_other_errors_are_not_retried() -> None:
    route = respx.post(URL).mock(
        return_value=httpx.Response(200, json={"errors": [{"message": "bad"}]})
    )

    with pytest.raises(ShopifyGraphQLError):
        await _client().query("{ shop { id } }")

    assert route.call_count == 1
