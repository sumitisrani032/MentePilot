import os
from urllib.parse import urlencode

import pytest
from sqlalchemy import text

from tests.conftest import TwoShops
from tests.fakes import FakeChatService
from tests.http_helpers import ORIGIN, signed_proxy_query, widget_headers

SECRET = os.environ["SHOPIFY_API_SECRET"]


def _form(message: str = "beach") -> dict[str, str]:
    return {"session_id": "s1", "message": message}


async def test_session_is_issued_for_a_signed_request(client, two_shops: TwoShops) -> None:
    query = signed_proxy_query({"shop": two_shops.domain_a, "origin": ORIGIN}, SECRET)

    response = await client.get(f"/proxy/session?{urlencode(query)}")

    assert response.status_code == 200 and response.json()["token"]
    assert response.json()["suggestions"]


async def test_session_can_be_created_with_post(client, two_shops: TwoShops) -> None:
    query = signed_proxy_query({"shop": two_shops.domain_a, "origin": ORIGIN}, SECRET)

    response = await client.post(f"/proxy/session?{urlencode(query)}")

    assert response.status_code == 200 and response.json()["token"]


async def test_unsigned_session_request_is_rejected(client, two_shops: TwoShops) -> None:
    response = await client.get(f"/proxy/session?shop={two_shops.domain_a}&origin={ORIGIN}")
    assert response.status_code == 401


async def test_inactive_shop_session_is_403(client, two_shops: TwoShops, owner_conn) -> None:
    await owner_conn.execute(
        text("UPDATE shops SET status = 'inactive' WHERE id = :id"), {"id": two_shops.a}
    )
    await owner_conn.commit()
    query = signed_proxy_query({"shop": two_shops.domain_a, "origin": ORIGIN}, SECRET)

    response = await client.get(f"/proxy/session?{urlencode(query)}")

    assert response.status_code == 403


async def test_chat_streams_events(client, two_shops: TwoShops) -> None:
    headers = widget_headers(two_shops.a, two_shops.domain_a)

    response = await client.post("/v1/chat", data=_form(), headers=headers)

    assert response.status_code == 200
    assert "event: token" in response.text and "event: done" in response.text


async def test_token_decides_the_store(
    client, two_shops: TwoShops, chat_service: FakeChatService
) -> None:
    headers = widget_headers(two_shops.b, two_shops.domain_b)

    await client.post("/v1/chat", data=_form(), headers=headers)

    assert chat_service.requests[0].shop_id == two_shops.b


async def test_missing_token_is_401(client, two_shops: TwoShops) -> None:
    response = await client.post("/v1/chat", data=_form(), headers={"Origin": ORIGIN})
    assert response.status_code == 401


@pytest.mark.parametrize("message", ["", "   ", "x" * 1001])
async def test_invalid_message_is_422_with_no_llm_call(
    client, two_shops: TwoShops, chat_service: FakeChatService, message: str
) -> None:
    headers = widget_headers(two_shops.a, two_shops.domain_a)

    response = await client.post("/v1/chat", data=_form(message), headers=headers)

    assert response.status_code == 422 and chat_service.requests == []


async def test_error_responses_are_readable_by_the_widget(client, two_shops: TwoShops) -> None:
    response = await client.post("/v1/chat", data=_form(), headers={"Origin": ORIGIN})
    assert response.status_code == 401
    assert response.headers["access-control-allow-origin"] == ORIGIN


async def test_huge_request_is_refused_before_parsing(client, two_shops: TwoShops) -> None:
    response = await client.post(
        "/v1/chat",
        content=b"0" * (11 * 1024 * 1024 + 1),
        headers={"Origin": ORIGIN, "Content-Type": "multipart/form-data; boundary=x"},
    )
    assert response.status_code == 413


def test_uploads_below_the_limit_stay_in_memory() -> None:
    from shopchat.api.app import MultiPartParser
    from shopchat.api.limits import MAX_WIDGET_BODY_BYTES

    assert MultiPartParser.spool_max_size == MAX_WIDGET_BODY_BYTES


async def test_cors_allows_only_the_shop_origin(client, two_shops: TwoShops) -> None:
    headers = widget_headers(two_shops.a, two_shops.domain_a)

    allowed = await client.post("/v1/chat", data=_form(), headers=headers)
    other = await client.post(
        "/v1/chat", data=_form(), headers={**headers, "Origin": "https://evil.example.test"}
    )

    assert allowed.headers["access-control-allow-origin"] == ORIGIN
    assert other.status_code == 403
