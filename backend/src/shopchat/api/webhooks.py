"""Receive Shopify webhooks. Requests are verified here and processed by the worker."""

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select

from shopchat.api.deps import get_queue, require_secret
from shopchat.config import Settings, get_settings
from shopchat.db.models import Shop
from shopchat.db.session import system_session
from shopchat.shopify.signatures import verify_webhook_hmac

router = APIRouter()

# Nothing about customers is stored, so these only need acknowledging.
_ACKNOWLEDGE_ONLY = frozenset({"customers/data_request", "customers/redact"})


def _job_for(topic: str, payload: dict[str, Any]) -> tuple[str, ...] | None:
    if topic in ("products/create", "products/update"):
        return ("upsert_product", payload["admin_graphql_api_id"])
    if topic == "products/delete":
        return ("delete_product", f"gid://shopify/Product/{payload['id']}")
    if topic == "inventory_levels/update":
        return ("update_inventory", f"gid://shopify/InventoryItem/{payload['inventory_item_id']}")
    if topic == "bulk_operations/finish":
        return ("finish_bulk", payload["admin_graphql_api_id"])
    if topic == "app/uninstalled":
        return ("deactivate_shop",)
    if topic == "shop/redact":
        return ("redact_shop",)
    return None


async def _shop_id(domain: str) -> Any:
    async with system_session() as session:
        result = await session.execute(select(Shop.id).where(Shop.domain == domain))
        return result.scalar_one_or_none()


@router.post("/webhooks/shopify")
async def receive(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    queue: Annotated[Any, Depends(get_queue)],
    x_shopify_hmac_sha256: Annotated[str, Header()] = "",
    x_shopify_topic: Annotated[str, Header()] = "",
    x_shopify_shop_domain: Annotated[str, Header()] = "",
    x_shopify_webhook_id: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    body = await request.body()
    secret = require_secret(settings.shopify_api_secret, "SHOPIFY_API_SECRET")
    if not verify_webhook_hmac(body, x_shopify_hmac_sha256, secret):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid signature")
    if x_shopify_topic in _ACKNOWLEDGE_ONLY:
        return {"status": "ok"}

    job = _job_for(x_shopify_topic, json.loads(body))
    shop_id = await _shop_id(x_shopify_shop_domain)
    if job is not None and shop_id is not None:
        name, *arguments = job
        await queue.enqueue_job(name, str(shop_id), *arguments, _job_id=x_shopify_webhook_id)
    return {"status": "ok"}
