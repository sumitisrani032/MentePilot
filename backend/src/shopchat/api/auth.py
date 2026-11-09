"""App install routes."""

import hmac
import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert

from shopchat.api.deps import get_queue, require_secret
from shopchat.config import Settings, get_settings
from shopchat.db.models import Shop
from shopchat.db.session import system_session
from shopchat.shopify.crypto import encrypt_token
from shopchat.shopify.oauth import AccessGrant, exchange_code, install_url, valid_shop_domain
from shopchat.shopify.signatures import verify_oauth_hmac

router = APIRouter()

_STATE_COOKIE = "shopchat_oauth_state"
_STATE_SECONDS = 600


def _client_id(settings: Settings) -> str:
    if not settings.shopify_api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "SHOPIFY_API_KEY is not set")
    return settings.shopify_api_key


@router.get("/auth/install")
async def install(
    shop: str, settings: Annotated[Settings, Depends(get_settings)]
) -> RedirectResponse:
    if not valid_shop_domain(shop):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid shop domain")
    state = secrets.token_urlsafe(32)
    redirect_uri = f"{settings.app_url}/auth/callback"
    response = RedirectResponse(install_url(shop, _client_id(settings), redirect_uri, state))
    response.set_cookie(
        _STATE_COOKIE, state, max_age=_STATE_SECONDS, httponly=True, secure=True, samesite="lax"
    )
    return response


async def _save_shop(domain: str, grant: AccessGrant) -> Any:
    values = {
        "access_token_encrypted": encrypt_token(grant.access_token),
        "refresh_token_encrypted": (
            encrypt_token(grant.refresh_token) if grant.refresh_token else None
        ),
        "access_token_expires_at": grant.expires_at(),
        "scopes": grant.scope,
        "status": "active",
        "uninstalled_at": None,
    }
    statement = (
        insert(Shop)
        .values(domain=domain, features={}, id=func.gen_random_uuid(), **values)
        .on_conflict_do_update(index_elements=[Shop.domain], set_=values)
        .returning(Shop.id)
    )
    async with system_session() as session:
        return (await session.execute(statement)).scalar_one()


@router.get("/auth/callback")
async def callback(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    queue: Annotated[Any, Depends(get_queue)],
    oauth_state: Annotated[str, Cookie(alias=_STATE_COOKIE)] = "",
) -> RedirectResponse:
    query = dict(request.query_params)
    secret = require_secret(settings.shopify_api_secret, "SHOPIFY_API_SECRET")
    shop = query.get("shop", "")
    state = query.get("state", "")
    if not valid_shop_domain(shop) or not verify_oauth_hmac(query, secret):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid request")
    if not oauth_state or not hmac.compare_digest(oauth_state, state):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid state")

    grant = await exchange_code(shop, query["code"], _client_id(settings), secret)
    shop_id = await _save_shop(shop, grant)
    await queue.enqueue_job("sync_shop", str(shop_id))

    response = RedirectResponse(f"https://{shop}/admin/apps/{_client_id(settings)}")
    response.delete_cookie(_STATE_COOKIE)
    return response
