"""The Shopify OAuth authorization-code flow."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx

SCOPES = "read_products,read_inventory,write_app_proxy"
_SHOP_DOMAIN = re.compile(r"^[a-z0-9][a-z0-9-]*\.myshopify\.com$")
_TIMEOUT_SECONDS = 15


@dataclass(frozen=True)
class AccessGrant:
    access_token: str
    scope: str
    refresh_token: str | None = None
    expires_in: int | None = None

    def expires_at(self) -> datetime | None:
        if self.expires_in is None:
            return None
        return datetime.now(UTC) + timedelta(seconds=self.expires_in)


def valid_shop_domain(shop: str) -> bool:
    return _SHOP_DOMAIN.fullmatch(shop) is not None


def install_url(shop: str, client_id: str, redirect_uri: str, state: str) -> str:
    query = urlencode(
        {"client_id": client_id, "scope": SCOPES, "redirect_uri": redirect_uri, "state": state}
    )
    return f"https://{shop}/admin/oauth/authorize?{query}"


async def _request_token(shop: str, form: dict[str, str]) -> AccessGrant:
    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        response = await client.post(f"https://{shop}/admin/oauth/access_token", data=form)
    response.raise_for_status()
    body = response.json()
    return AccessGrant(
        access_token=body["access_token"],
        scope=body.get("scope", ""),
        refresh_token=body.get("refresh_token"),
        expires_in=body.get("expires_in"),
    )


async def exchange_code(shop: str, code: str, client_id: str, client_secret: str) -> AccessGrant:
    """Swap an install code for an expiring token, which Shopify requires of public apps."""
    return await _request_token(
        shop,
        {"client_id": client_id, "client_secret": client_secret, "code": code, "expiring": "1"},
    )


async def refresh_access_token(
    shop: str, refresh_token: str, client_id: str, client_secret: str
) -> AccessGrant:
    return await _request_token(
        shop,
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
    )
