import hashlib
import hmac
import os
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

import httpx
import respx
from sqlalchemy import delete, select, update

from shopchat.db.models import Shop
from shopchat.db.session import system_session
from shopchat.shopify.crypto import decrypt_token

SECRET = os.environ["SHOPIFY_API_SECRET"]
STATE = "state-value"


def _domain() -> str:
    return f"new-{uuid4().hex[:8]}.myshopify.com"


def _callback_url(shop: str, state: str = STATE) -> str:
    query = {"code": "abc", "shop": shop, "state": state, "timestamp": "1"}
    message = "&".join(sorted(f"{k}={v}" for k, v in query.items()))
    query["hmac"] = hmac.new(SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    return f"/auth/callback?{urlencode(query)}"


def _cookie(state: str = STATE) -> dict[str, str]:
    return {"Cookie": f"shopchat_oauth_state={state}"}


def _mock_token(shop: str) -> None:
    respx.post(f"https://{shop}/admin/oauth/access_token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "shpat_secret",
                "refresh_token": "shprt_secret",
                "expires_in": 3600,
                "scope": "read_products",
            },
        )
    )


async def _stored(shop: str) -> Shop:
    async with system_session() as session:
        return (await session.execute(select(Shop).where(Shop.domain == shop))).scalar_one()


async def _cleanup(shop: str) -> None:
    async with system_session() as session:
        await session.execute(delete(Shop).where(Shop.domain == shop))


async def test_rejects_non_myshopify_domain(client) -> None:
    response = await client.get("/auth/install?shop=evil.example.com")
    assert response.status_code == 400


async def test_install_requests_only_the_needed_scopes(client) -> None:
    response = await client.get(f"/auth/install?shop={_domain()}")
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["scope"] == ["read_products,read_inventory,write_app_proxy"]


async def test_rejects_bad_hmac(client) -> None:
    url = _callback_url(_domain()).replace("code=abc", "code=tampered")
    assert (await client.get(url, headers=_cookie())).status_code == 401


async def test_rejects_bad_state(client) -> None:
    response = await client.get(_callback_url(_domain()), headers=_cookie("other"))
    assert response.status_code == 401


async def test_rejects_missing_state_cookie(client) -> None:
    assert (await client.get(_callback_url(_domain()))).status_code == 401


@respx.mock
async def test_stored_token_is_encrypted(client) -> None:
    shop = _domain()
    _mock_token(shop)

    await client.get(_callback_url(shop), headers=_cookie())

    stored = await _stored(shop)
    assert b"shpat_secret" not in stored.access_token_encrypted
    assert decrypt_token(stored.access_token_encrypted) == "shpat_secret"
    await _cleanup(shop)


@respx.mock
async def test_install_requests_an_expiring_token(client) -> None:
    shop = _domain()
    _mock_token(shop)

    await client.get(_callback_url(shop), headers=_cookie())

    assert "expiring=1" in respx.calls[0].request.content.decode()
    stored = await _stored(shop)
    assert decrypt_token(stored.refresh_token_encrypted) == "shprt_secret"
    assert stored.access_token_expires_at is not None
    await _cleanup(shop)


@respx.mock
async def test_install_starts_a_sync(client, queue) -> None:
    shop = _domain()
    _mock_token(shop)

    await client.get(_callback_url(shop), headers=_cookie())

    assert queue.jobs[0][0] == "sync_shop"
    await _cleanup(shop)


@respx.mock
async def test_reinstall_reactivates_shop(client) -> None:
    shop = _domain()
    _mock_token(shop)
    await client.get(_callback_url(shop), headers=_cookie())
    async with system_session() as session:
        await session.execute(update(Shop).where(Shop.domain == shop).values(status="inactive"))

    await client.get(_callback_url(shop), headers=_cookie())

    assert (await _stored(shop)).status == "active"
    await _cleanup(shop)
