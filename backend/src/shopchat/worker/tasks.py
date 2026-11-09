"""Background jobs for catalog sync and store lifecycle."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from arq import Retry
from sqlalchemy import ARRAY, Text, all_, cast, delete, or_, select, update

from shopchat.catalog.pipeline import run_catalog_pipeline
from shopchat.catalog.shopify_source import (
    BULK_RESULT_QUERY,
    SHOP_CURRENCY_QUERY,
    BulkOperationsDenied,
    fetch_all_products,
    fetch_product,
    parse_bulk_jsonl,
    start_bulk_import,
)
from shopchat.catalog.types import NormalizedProduct
from shopchat.db.models import Product, Shop, SyncJob, Variant
from shopchat.db.session import session_for_shop, system_session
from shopchat.llm.openai_adapters import LLMCallsDisabledError
from shopchat.shopify.graphql import AdminClient
from shopchat.shopify.tokens import current_access_token

logger = logging.getLogger(__name__)

MAX_TRIES = 5
_RETRY_BASE_SECONDS = 30
_BULK_IMPORT = "bulk_import"

Ctx = dict[str, Any]


async def _admin_client(ctx: Ctx, shop_id: UUID) -> AdminClient:
    domain, token = await current_access_token(shop_id)
    client: AdminClient = ctx["client_for"](domain, token)
    return client


async def _record_failure(shop_id: UUID, kind: str, error: Exception) -> None:
    try:
        async with session_for_shop(shop_id) as session:
            session.add(
                SyncJob(id=uuid4(), shop_id=shop_id, type=kind, status="failed", error=str(error))
            )
    except Exception as nested:
        logger.error("could not record job failure: %s", type(nested).__name__)


async def _guarded(ctx: Ctx, shop_id: UUID, kind: str, work: Callable[[], Awaitable[None]]) -> None:
    """Retry passing failures with backoff, and surface lasting ones to the merchant."""
    try:
        await work()
    except asyncio.CancelledError:
        # arq cancels a job that hits its time limit, and does not retry it.
        await _record_failure(shop_id, kind, RuntimeError("the job ran out of time"))
        raise
    except LLMCallsDisabledError as error:
        await _record_failure(shop_id, kind, error)
    except Exception as error:
        attempt = int(ctx.get("job_try", 1))
        logger.warning("%s failed on attempt %d: %r", kind, attempt, error)
        if attempt < MAX_TRIES:
            raise Retry(defer=attempt * _RETRY_BASE_SECONDS) from error
        await _record_failure(shop_id, kind, error)


async def _without_stale(
    shop_id: UUID, products: Sequence[NormalizedProduct]
) -> list[NormalizedProduct]:
    """Keep only products at least as new as what is already stored."""
    async with session_for_shop(shop_id) as session:
        rows = await session.execute(select(Product.source_id, Product.source_updated_at))
        stored = {source_id: updated for source_id, updated in rows}

    def is_current(product: NormalizedProduct) -> bool:
        known = stored.get(product.source_id)
        return (
            known is None
            or product.source_updated_at is None
            or (product.source_updated_at >= known)
        )

    return [product for product in products if is_current(product)]


async def _start_job(shop_id: UUID) -> None:
    """Open a sync record, reusing one left running by an earlier attempt."""
    if await _latest_running_job(shop_id) is not None:
        return
    async with session_for_shop(shop_id) as session:
        session.add(SyncJob(id=uuid4(), shop_id=shop_id, type=_BULK_IMPORT, status="running"))


async def sync_shop(ctx: Ctx, shop_id: str) -> None:
    uid = UUID(shop_id)

    async def work() -> None:
        client = await _admin_client(ctx, uid)
        try:
            await start_bulk_import(client)
        except BulkOperationsDenied:
            logger.warning("bulk export denied for shop %s, importing page by page", uid)
            await _start_job(uid)
            await _index_export(ctx, uid, await fetch_all_products(client))
            return
        await _start_job(uid)

    await _guarded(ctx, uid, _BULK_IMPORT, work)


async def _latest_running_job(shop_id: UUID) -> SyncJob | None:
    statement = (
        select(SyncJob)
        .where(SyncJob.type == _BULK_IMPORT, SyncJob.status == "running")
        .order_by(SyncJob.created_at.desc())
        .limit(1)
    )
    async with session_for_shop(shop_id) as session:
        return (await session.execute(statement)).scalar_one_or_none()


async def _complete_job(shop_id: UUID, job: SyncJob | None, processed: int) -> None:
    if job is None:
        return
    async with session_for_shop(shop_id) as session:
        await session.execute(
            update(SyncJob)
            .where(SyncJob.id == job.id)
            .values(status="completed", processed=processed)
        )


async def _remove_missing(
    shop_id: UUID, exported: Sequence[NormalizedProduct], job: SyncJob | None
) -> None:
    """Delete products gone from Shopify, sparing any added after the export began."""
    if job is None:
        return
    source_ids = [product.source_id for product in exported]
    async with session_for_shop(shop_id) as session:
        await session.execute(
            delete(Product).where(
                Product.source_id != all_(cast(source_ids, ARRAY(Text))),
                or_(
                    Product.source_updated_at.is_(None),
                    Product.source_updated_at < job.created_at,
                ),
            )
        )


async def _index_export(ctx: Ctx, shop_id: UUID, exported: Sequence[NormalizedProduct]) -> None:
    job = await _latest_running_job(shop_id)
    current = await _without_stale(shop_id, exported)
    await run_catalog_pipeline(shop_id, current, ctx["bundle"])
    await _remove_missing(shop_id, exported, job)
    await _complete_job(shop_id, job, len(exported))


async def finish_bulk(ctx: Ctx, shop_id: str, bulk_id: str) -> None:
    uid = UUID(shop_id)

    async def work() -> None:
        client = await _admin_client(ctx, uid)
        result = (await client.query(BULK_RESULT_QUERY, {"id": bulk_id}))["node"]
        if result["status"] != "COMPLETED":
            raise RuntimeError(f"bulk export ended with {result['status']}")
        if not result.get("url"):  # Shopify gives no file for an empty catalog.
            await _complete_job(uid, await _latest_running_job(uid), 0)
            return
        currency = (await client.query(SHOP_CURRENCY_QUERY))["shop"]["currencyCode"]
        lines = await ctx["download"](result["url"])
        await _index_export(ctx, uid, parse_bulk_jsonl(lines, currency))

    await _guarded(ctx, uid, _BULK_IMPORT, work)


async def _delete_by_source(shop_id: UUID, source_id: str) -> None:
    async with session_for_shop(shop_id) as session:
        await session.execute(delete(Product).where(Product.source_id == source_id))


async def upsert_product(ctx: Ctx, shop_id: str, product_gid: str) -> None:
    uid = UUID(shop_id)

    async def work() -> None:
        # Webhook bodies have no metafields, so the current product is always fetched.
        product = await fetch_product(await _admin_client(ctx, uid), product_gid)
        if product is None:
            await _delete_by_source(uid, product_gid)
            return
        current = await _without_stale(uid, [product])
        await run_catalog_pipeline(uid, current, ctx["bundle"], refresh_profile=False)

    await _guarded(ctx, uid, "product_update", work)


async def delete_product(ctx: Ctx, shop_id: str, product_gid: str) -> None:
    await _delete_by_source(UUID(shop_id), product_gid)


async def update_inventory(ctx: Ctx, shop_id: str, inventory_item_gid: str) -> None:
    uid = UUID(shop_id)

    async def work() -> None:
        statement = (
            select(Product.source_id)
            .join(Variant, Variant.product_id == Product.id)
            .where(Variant.inventory_item_id == inventory_item_gid)
        )
        async with session_for_shop(uid) as session:
            source_id = (await session.execute(statement)).scalar_one_or_none()
        if source_id is None:
            return
        product = await fetch_product(await _admin_client(ctx, uid), source_id)
        if product is not None:
            await _apply_availability(uid, product)

    await _guarded(ctx, uid, "inventory_update", work)


async def _apply_availability(shop_id: UUID, product: NormalizedProduct) -> None:
    """Stock changes touch availability only, so they never cost an LLM call."""
    async with session_for_shop(shop_id) as session:
        for variant in product.variants:
            await session.execute(
                update(Variant)
                .where(Variant.source_id == variant.source_id)
                .values(available=variant.available)
            )
        await session.execute(
            update(Product)
            .where(Product.source_id == product.source_id)
            .values(available=any(variant.available for variant in product.variants))
        )


async def deactivate_shop(ctx: Ctx, shop_id: str) -> None:
    async with system_session() as session:
        await session.execute(
            update(Shop)
            .where(Shop.id == UUID(shop_id))
            .values(
                status="inactive", uninstalled_at=datetime.now(UTC), access_token_encrypted=None
            )
        )


async def redact_shop(ctx: Ctx, shop_id: str) -> None:
    """Delete the store. Every table cascades from it."""
    async with system_session() as session:
        await session.execute(delete(Shop).where(Shop.id == UUID(shop_id)))
