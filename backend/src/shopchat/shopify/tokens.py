"""Keep each store's expiring Shopify access token usable."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from shopchat.config import get_settings
from shopchat.db.models import Shop
from shopchat.db.session import system_session
from shopchat.shopify.crypto import decrypt_token, encrypt_token
from shopchat.shopify.oauth import refresh_access_token

_REFRESH_MARGIN = timedelta(minutes=5)


async def current_access_token(shop_id: UUID) -> tuple[str, str]:
    """Return the store's domain and a usable token, refreshing it first if needed.

    The row stays locked during a refresh, so two jobs cannot both spend one refresh token.
    """
    statement = select(Shop).where(Shop.id == shop_id).with_for_update()
    async with system_session() as session:
        shop = (await session.execute(statement)).scalar_one_or_none()
        if shop is None or shop.access_token_encrypted is None:
            raise RuntimeError("store has no access token")
        token = decrypt_token(shop.access_token_encrypted)
        expires_at = shop.access_token_expires_at
        if (
            expires_at is None
            or shop.refresh_token_encrypted is None
            or datetime.now(UTC) < expires_at - _REFRESH_MARGIN
        ):
            return shop.domain, token

        settings = get_settings()
        if not settings.shopify_api_key or settings.shopify_api_secret is None:
            raise RuntimeError("Shopify app credentials are not set")
        grant = await refresh_access_token(
            shop.domain,
            decrypt_token(shop.refresh_token_encrypted),
            settings.shopify_api_key,
            settings.shopify_api_secret.get_secret_value(),
        )
        shop.access_token_encrypted = encrypt_token(grant.access_token)
        shop.refresh_token_encrypted = (
            encrypt_token(grant.refresh_token) if grant.refresh_token else None
        )
        shop.access_token_expires_at = grant.expires_at()
        return shop.domain, grant.access_token
