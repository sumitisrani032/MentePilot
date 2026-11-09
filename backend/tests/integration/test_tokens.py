from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import respx

from shopchat.db.models import Shop
from shopchat.db.session import system_session
from shopchat.shopify.crypto import decrypt_token, encrypt_token
from shopchat.shopify.tokens import current_access_token
from tests.conftest import TwoShops


async def _set_tokens(shop_id: UUID, expires_in_minutes: int | None) -> None:
    async with system_session() as session:
        shop = await session.get(Shop, shop_id)
        assert shop is not None
        shop.access_token_encrypted = encrypt_token("old-access")
        shop.refresh_token_encrypted = encrypt_token("old-refresh")
        shop.access_token_expires_at = (
            None
            if expires_in_minutes is None
            else datetime.now(UTC) + timedelta(minutes=expires_in_minutes)
        )


@respx.mock
async def test_fresh_token_is_used_without_a_refresh(two_shops: TwoShops) -> None:
    await _set_tokens(two_shops.a, 50)
    assert await current_access_token(two_shops.a) == (two_shops.domain_a, "old-access")
    assert respx.calls.call_count == 0


@respx.mock
async def test_token_without_expiry_is_used_as_is(two_shops: TwoShops) -> None:
    await _set_tokens(two_shops.a, None)
    assert (await current_access_token(two_shops.a))[1] == "old-access"


@respx.mock
async def test_nearly_expired_token_is_refreshed_and_stored(two_shops: TwoShops) -> None:
    await _set_tokens(two_shops.a, 2)
    route = respx.post(f"https://{two_shops.domain_a}/admin/oauth/access_token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_in": 3600,
                "scope": "read_products",
            },
        )
    )

    assert (await current_access_token(two_shops.a))[1] == "new-access"

    body = route.calls[0].request.content.decode()
    assert "grant_type=refresh_token" in body and "refresh_token=old-refresh" in body
    async with system_session() as session:
        shop = await session.get(Shop, two_shops.a)
    assert shop is not None
    assert decrypt_token(shop.refresh_token_encrypted) == "new-refresh"
    assert decrypt_token(shop.access_token_encrypted) == "new-access"
    assert shop.access_token_expires_at > datetime.now(UTC) + timedelta(minutes=50)
