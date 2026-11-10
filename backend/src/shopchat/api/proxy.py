"""Shopify App Proxy routes, which prove to the backend which store is calling."""

from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, status

from shopchat.agents.skin import SKIN_CONSENT_TEXT
from shopchat.api.deps import issue_widget_token, load_active_shop, require_secret
from shopchat.catalog.repository import load_profile
from shopchat.chat.features import effective_features
from shopchat.chat.suggestions import suggestions_for
from shopchat.config import Settings, get_settings
from shopchat.db.models import Shop
from shopchat.shopify.signatures import verify_proxy_signature

router = APIRouter()


def _valid_origin(origin: str) -> bool:
    parts = urlsplit(origin)
    return parts.scheme == "https" and bool(parts.netloc) and not parts.path


@router.api_route("/proxy/session", methods=["GET", "POST"])
async def create_session(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> dict[str, Any]:
    query = dict(request.query_params)
    secret = require_secret(settings.shopify_api_secret, "SHOPIFY_API_SECRET")
    if not verify_proxy_signature(query, secret):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid signature")
    origin = query.get("origin", "")
    if not _valid_origin(origin):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid origin")
    shop = await load_active_shop(query.get("shop", ""))
    if shop is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Store is not active")
    return await build_session(shop, origin, settings.app_url, settings)


async def build_session(
    shop: Shop, origin: str, api_base: str, settings: Settings
) -> dict[str, Any]:
    """What the widget needs to start: a token for this store and origin, and its options."""
    profile = await load_profile(shop.id)
    return {
        "token": issue_widget_token(shop.id, shop.domain, origin),
        "api_base": api_base,
        "skin_consent_text": SKIN_CONSENT_TEXT,
        "features": effective_features(settings, shop.features, profile),
        "suggestions": suggestions_for(profile),
    }
