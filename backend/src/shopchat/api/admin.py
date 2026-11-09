"""The merchant's page inside Shopify admin, and the API behind it."""

import html
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit

import httpx
import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import func, select

from shopchat.api.deps import get_queue, require_secret
from shopchat.catalog.repository import load_profile
from shopchat.chat.features import effective_features
from shopchat.config import Settings, get_settings
from shopchat.db.models import Product, ProductChunk, Shop, SyncJob, UsageEvent
from shopchat.db.session import session_for_shop, system_session
from shopchat.shopify.graphql import AdminClient
from shopchat.shopify.oauth import SCOPES, valid_shop_domain
from shopchat.shopify.signatures import verify_oauth_hmac
from shopchat.shopify.tokens import current_access_token

router = APIRouter()

_ADMIN_DIR = Path(__file__).resolve().parents[4] / "frontend" / "admin"


class FeatureChoices(BaseModel):
    image: bool | None = None
    skin_analysis: bool | None = None
    voice: bool | None = None


async def _shop_by_domain(domain: str) -> Shop | None:
    async with system_session() as session:
        result = await session.execute(select(Shop).where(Shop.domain == domain))
        return result.scalar_one_or_none()


async def admin_shop(
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str, Header()] = "",
) -> Shop:
    """Authenticate the merchant with the App Bridge session token."""
    secret = require_secret(settings.shopify_api_secret, "SHOPIFY_API_SECRET")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        claims = jwt.decode(token, secret, algorithms=["HS256"], audience=settings.shopify_api_key)
    except jwt.PyJWTError as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session") from error
    domain = urlsplit(str(claims.get("dest", ""))).netloc
    shop = await _shop_by_domain(domain) if valid_shop_domain(domain) else None
    if shop is None or shop.status != "active":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown store")
    return shop


def _top_level_redirect(url: str, api_key: str) -> HTMLResponse:
    """OAuth cannot run inside the admin iframe, so the whole window has to move."""
    return HTMLResponse(
        f'<meta name="shopify-api-key" content="{html.escape(api_key)}">'
        '<script src="https://cdn.shopify.com/shopifycloud/app-bridge.js"></script>'
        f"<script>open({json.dumps(url)}, '_top')</script>"
    )


async def _token_works(shop: Shop, settings: Settings) -> bool:
    """Only a clear refusal from Shopify counts. A network problem must not force a reinstall."""
    try:
        domain, token = await current_access_token(shop.id)
        await AdminClient(domain, token, settings.shopify_api_version).query("{ shop { id } }")
    except httpx.HTTPStatusError as error:
        return error.response.status_code not in (401, 403)
    except httpx.HTTPError:
        return True
    return True


async def _needs_install(known: Shop | None, query: Mapping[str, str], settings: Settings) -> bool:
    """Decide whether this store must go through OAuth.

    The uninstall webhook can be missed, so a store marked active may hold a dead token. Only
    a load signed by Shopify is checked, so strangers cannot trigger calls to Shopify.
    """
    if known is None or known.status != "active":
        return True
    secret = require_secret(settings.shopify_api_secret, "SHOPIFY_API_SECRET")
    if "hmac" not in query or not verify_oauth_hmac(query, secret):
        return False
    if set(SCOPES.split(",")) - set(known.scopes.split(",")):
        return True  # A permission added since install still needs the merchant's approval.
    return known.refresh_token_encrypted is None or not await _token_works(known, settings)


@router.get("/admin", response_model=None)
async def page(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    shop: str = "",
    embedded: str = "",
) -> HTMLResponse | RedirectResponse:
    if shop and not valid_shop_domain(shop):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid shop domain")
    if shop and await _needs_install(
        await _shop_by_domain(shop), dict(request.query_params), settings
    ):
        install = f"{settings.app_url}/auth/install?shop={shop}"
        if embedded == "1":
            return _top_level_redirect(install, settings.shopify_api_key or "")
        return RedirectResponse(f"/auth/install?shop={shop}")
    template = (_ADMIN_DIR / "index.html").read_text()
    body = template.replace("__SHOPIFY_API_KEY__", html.escape(settings.shopify_api_key or ""))
    ancestors = f"https://{shop} https://admin.shopify.com" if shop else "https://admin.shopify.com"
    return HTMLResponse(body, headers={"Content-Security-Policy": f"frame-ancestors {ancestors};"})


@router.get("/admin/admin.js")
async def script() -> Response:
    return Response((_ADMIN_DIR / "admin.js").read_text(), media_type="text/javascript")


@router.get("/admin/api/status")
async def get_status(
    shop: Annotated[Shop, Depends(admin_shop)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    async with session_for_shop(shop.id) as session:
        products = (await session.execute(select(func.count()).select_from(Product))).scalar_one()
        indexed = (
            await session.execute(select(func.count(ProductChunk.product_id.distinct())))
        ).scalar_one()
        job = (
            await session.execute(select(SyncJob).order_by(SyncJob.created_at.desc()).limit(1))
        ).scalar_one_or_none()
        usage_rows = await session.execute(
            select(UsageEvent.kind, func.sum(UsageEvent.quantity)).group_by(UsageEvent.kind)
        )
        usage = {kind: int(total) for kind, total in usage_rows}
    return {
        "shop": shop.domain,
        "products": products,
        "indexed": indexed,
        "sync": {"status": job.status, "error": job.error} if job else None,
        "usage": usage,
        "features": effective_features(settings, shop.features, await load_profile(shop.id)),
        "voice_available": settings.voice_enabled,
    }


@router.patch("/admin/api/settings")
async def update_settings(
    choices: FeatureChoices, shop: Annotated[Shop, Depends(admin_shop)]
) -> dict[str, bool]:
    updates = choices.model_dump(exclude_none=True)
    async with system_session() as session:
        stored = await session.get(Shop, shop.id)
        assert stored is not None  # authenticated moments ago
        stored.features = {**stored.features, **updates}
        return dict(stored.features)


@router.post("/admin/api/resync", status_code=status.HTTP_202_ACCEPTED)
async def resync(
    shop: Annotated[Shop, Depends(admin_shop)], queue: Annotated[Any, Depends(get_queue)]
) -> dict[str, str]:
    await queue.enqueue_job("sync_shop", str(shop.id))
    return {"status": "queued"}
