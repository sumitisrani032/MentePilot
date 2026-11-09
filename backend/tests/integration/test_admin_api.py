import hashlib
import hmac
import os
import time
from urllib.parse import urlencode
from uuid import UUID

import httpx
import jwt
import pytest
import respx

from shopchat.catalog.indexer import save_new_records
from shopchat.db.models import Shop
from shopchat.db.session import system_session
from shopchat.shopify.crypto import encrypt_token
from shopchat.shopify.oauth import SCOPES
from tests.conftest import TwoShops
from tests.factories import normalized

API_KEY = os.environ["SHOPIFY_API_KEY"]
SECRET = os.environ["SHOPIFY_API_SECRET"]


def _headers(domain: str, secret: str = SECRET, audience: str = API_KEY) -> dict[str, str]:
    token = jwt.encode(
        {
            "dest": f"https://{domain}",
            "iss": f"https://{domain}/admin",
            "aud": audience,
            "exp": int(time.time()) + 60,
        },
        secret,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


async def test_missing_session_token_is_401(client) -> None:
    assert (await client.get("/admin/api/status")).status_code == 401


@pytest.mark.parametrize(
    ("secret", "audience"),
    [("wrong-secret-that-is-long-enough-for-hs256", API_KEY), (SECRET, "another-app")],
)
async def test_bad_session_token_is_401(
    client, two_shops: TwoShops, secret: str, audience: str
) -> None:
    response = await client.get(
        "/admin/api/status", headers=_headers(two_shops.domain_a, secret, audience)
    )
    assert response.status_code == 401


async def test_status_shows_only_own_shop(client, two_shops: TwoShops) -> None:
    response = await client.get("/admin/api/status", headers=_headers(two_shops.domain_a))
    assert response.status_code == 200 and response.json()["shop"] == two_shops.domain_a


async def test_status_separates_imported_from_searchable(client, two_shops: TwoShops) -> None:
    await save_new_records(two_shops.a, [normalized("a")])

    body = (await client.get("/admin/api/status", headers=_headers(two_shops.domain_a))).json()

    assert (body["products"], body["indexed"]) == (1, 0)


async def test_toggle_skin_analysis_takes_effect(client, two_shops: TwoShops) -> None:
    headers = _headers(two_shops.domain_a)

    await client.patch("/admin/api/settings", json={"skin_analysis": False}, headers=headers)

    status = await client.get("/admin/api/status", headers=headers)
    assert status.json()["features"]["skin_analysis"] is False


async def test_voice_cannot_activate_when_global_switch_is_off(client, two_shops: TwoShops) -> None:
    headers = _headers(two_shops.domain_a)

    await client.patch("/admin/api/settings", json={"voice": True}, headers=headers)

    status = await client.get("/admin/api/status", headers=headers)
    assert status.json()["features"]["voice"] is False


async def test_resync_queues_a_sync(client, two_shops: TwoShops, queue) -> None:
    response = await client.post("/admin/api/resync", headers=_headers(two_shops.domain_a))
    assert response.status_code == 202 and queue.jobs == [("sync_shop", str(two_shops.a))]


async def test_page_can_be_framed_only_by_shopify(client, two_shops: TwoShops) -> None:
    response = await client.get(f"/admin?shop={two_shops.domain_a}")
    policy = response.headers["content-security-policy"]
    assert two_shops.domain_a in policy and "admin.shopify.com" in policy


def _signed_load(shop: str) -> str:
    query = {"shop": shop, "timestamp": "1"}
    message = "&".join(sorted(f"{k}={v}" for k, v in query.items()))
    query["hmac"] = hmac.new(SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    return f"/admin?{urlencode(query)}"


async def _give_tokens(shop_id: UUID) -> None:
    async with system_session() as session:
        shop = await session.get(Shop, shop_id)
        assert shop is not None
        shop.access_token_encrypted = encrypt_token("access")
        shop.refresh_token_encrypted = encrypt_token("refresh")
        shop.scopes = SCOPES


async def test_signed_load_without_expiring_token_goes_to_install(
    client, two_shops: TwoShops
) -> None:
    response = await client.get(_signed_load(two_shops.domain_a))
    assert response.status_code == 307


@respx.mock
async def test_signed_load_with_a_dead_token_goes_to_install(client, two_shops: TwoShops) -> None:
    await _give_tokens(two_shops.a)
    respx.post(url__regex=r".*/graphql\.json").mock(return_value=httpx.Response(401))

    response = await client.get(_signed_load(two_shops.domain_a))

    assert response.status_code == 307


@respx.mock
async def test_signed_load_with_a_good_token_shows_the_page(client, two_shops: TwoShops) -> None:
    await _give_tokens(two_shops.a)
    respx.post(url__regex=r".*/graphql\.json").mock(
        return_value=httpx.Response(200, json={"data": {"shop": {"id": "1"}}})
    )

    response = await client.get(_signed_load(two_shops.domain_a))

    assert response.status_code == 200 and "Shop assistant" in response.text


@respx.mock
async def test_network_problem_does_not_force_a_reinstall(client, two_shops: TwoShops) -> None:
    await _give_tokens(two_shops.a)
    respx.post(url__regex=r".*/graphql\.json").mock(side_effect=httpx.ConnectError("down"))

    assert (await client.get(_signed_load(two_shops.domain_a))).status_code == 200


@respx.mock
async def test_signed_load_missing_a_new_scope_goes_to_install(client, two_shops: TwoShops) -> None:
    await _give_tokens(two_shops.a)
    async with system_session() as session:
        shop = await session.get(Shop, two_shops.a)
        assert shop is not None
        shop.scopes = "read_products"

    response = await client.get(_signed_load(two_shops.domain_a))

    assert response.status_code == 307


async def test_forged_signature_cannot_trigger_install(client, two_shops: TwoShops) -> None:
    response = await client.get(f"/admin?shop={two_shops.domain_a}&hmac=forged")
    assert response.status_code == 200


async def test_embedded_install_leaves_the_iframe(client) -> None:
    response = await client.get("/admin?shop=brand-new.myshopify.com&embedded=1")
    assert response.status_code == 200 and "_top" in response.text


async def test_unknown_store_is_sent_to_install(client) -> None:
    response = await client.get("/admin?shop=brand-new.myshopify.com")
    assert response.status_code == 307
    assert response.headers["location"] == "/auth/install?shop=brand-new.myshopify.com"
