import json
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import pytest
from arq import Retry
from pydantic import BaseModel
from sqlalchemy import func, select, text

from shopchat.catalog.enrich import InferredAttributes
from shopchat.catalog.profile import ProfileNarrative
from shopchat.catalog.shopify_source import (
    BULK_RESULT_QUERY,
    PRODUCT_QUERY,
    SHOP_CURRENCY_QUERY,
)
from shopchat.db.models import Product, Shop, SyncJob, Variant
from shopchat.db.session import session_for_shop, system_session
from shopchat.llm.ports import LLMBundle
from shopchat.shopify.crypto import encrypt_token
from shopchat.shopify.graphql import ShopifyGraphQLError
from shopchat.worker import tasks
from tests.conftest import TwoShops
from tests.fakes import fake_bundle

GID = "gid://shopify/Product/1"
INVENTORY_GID = "gid://shopify/InventoryItem/1"


class AnswerAnything:
    """Returns an empty answer of whichever type is requested."""

    calls = 0

    async def generate(self, system: str, user: str, schema: type[BaseModel], tier: Any, images=()):
        AnswerAnything.calls += 1
        if schema is InferredAttributes:
            return InferredAttributes(facts=[])
        return ProfileNarrative(summary="s", vocabulary=[], has_skincare=False)


def _node(updated: str = "2026-10-02T00:00:00Z", title: str = "New", available: bool = True):
    return {
        "id": GID,
        "publishedAt": "2026-10-01T00:00:00Z",
        "handle": "item",
        "title": title,
        "descriptionHtml": "<p>Text</p>",
        "vendor": "Acme",
        "productType": "Shirt",
        "status": "ACTIVE",
        "tags": [],
        "updatedAt": updated,
        "category": None,
        "media": {"edges": []},
        "variants": {
            "edges": [
                {
                    "node": {
                        "id": "gid://shopify/ProductVariant/1",
                        "title": "Default",
                        "price": "10.00",
                        "compareAtPrice": None,
                        "availableForSale": available,
                        "selectedOptions": [],
                        "inventoryItem": {"id": INVENTORY_GID},
                    }
                }
            ]
        },
        "metafields": {"edges": []},
    }


@dataclass
class FakeAdmin:
    product: dict[str, Any] | None = None
    bulk_status: str = "COMPLETED"
    bulk_url: str | None = "https://files.example.test/export"
    queries: list[str] = field(default_factory=list)
    bulk_denied: bool = False

    async def query(self, query: str, variables: dict | None = None) -> dict[str, Any]:
        self.queries.append(query)
        if query == PRODUCT_QUERY:
            return {"shop": {"currencyCode": "USD"}, "product": self.product}
        if query == SHOP_CURRENCY_QUERY:
            return {"shop": {"currencyCode": "USD"}}
        if "products(first: 250" in query:
            return {
                "products": {
                    "nodes": [{"id": GID}],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                }
            }
        if "bulkOperationRunQuery" in query and self.bulk_denied:
            raise ShopifyGraphQLError("ACCESS_DENIED for bulkOperationRunQuery")
        if query == BULK_RESULT_QUERY:
            return {"node": {"status": self.bulk_status, "url": self.bulk_url}}
        return {"bulkOperationRunQuery": {"bulkOperation": {"id": "b1"}, "userErrors": []}}


@pytest.fixture
async def worker(two_shops: TwoShops) -> dict[str, Any]:
    async with system_session() as session:
        shop = await session.get(Shop, two_shops.a)
        assert shop is not None
        shop.access_token_encrypted = encrypt_token("token")
    admin = FakeAdmin()
    bundle = fake_bundle()
    bundle = LLMBundle(
        structured=AnswerAnything(),
        streamer=bundle.streamer,
        embedder=bundle.embedder,
        stt=bundle.stt,
        tts=bundle.tts,
    )

    async def download(url: str) -> list[str]:
        return admin.lines  # type: ignore[attr-defined]

    admin.lines = []  # type: ignore[attr-defined]
    return {
        "bundle": bundle,
        "client_for": lambda domain, token: admin,
        "download": download,
        "job_try": 1,
        "admin": admin,
        "shop": two_shops.a,
    }


async def _title(shop: UUID) -> str | None:
    async with session_for_shop(shop) as session:
        return (await session.execute(select(Product.title))).scalar_one_or_none()


async def _count(shop: UUID) -> int:
    async with session_for_shop(shop) as session:
        return (await session.execute(select(func.count()).select_from(Product))).scalar_one()


async def _upsert(worker: dict[str, Any], node: dict[str, Any]) -> None:
    worker["admin"].product = node
    await tasks.upsert_product(worker, str(worker["shop"]), GID)


async def test_upsert_creates_the_product(worker) -> None:
    await _upsert(worker, _node())
    assert await _title(worker["shop"]) == "New"


async def test_duplicate_webhook_has_one_effect(worker) -> None:
    await _upsert(worker, _node())
    await _upsert(worker, _node())
    assert await _count(worker["shop"]) == 1


async def test_older_updated_at_never_overwrites(worker) -> None:
    await _upsert(worker, _node("2026-10-05T00:00:00Z", title="Newest"))
    await _upsert(worker, _node("2026-10-01T00:00:00Z", title="Older"))
    assert await _title(worker["shop"]) == "Newest"


async def test_webhook_during_first_import_is_kept(worker) -> None:
    await _upsert(worker, _node("2026-10-09T00:00:00Z", title="From webhook"))
    await tasks.sync_shop(worker, str(worker["shop"]))
    record = {k: v for k, v in _node("2026-10-01T00:00:00Z", title="From export").items()}
    for key in ("media", "variants", "metafields"):
        record.pop(key)
    worker["admin"].lines = [json.dumps(record)]

    await tasks.finish_bulk(worker, str(worker["shop"]), "b1")

    assert await _title(worker["shop"]) == "From webhook"


async def test_full_sync_removes_products_deleted_from_shopify(worker, owner_conn) -> None:
    await _upsert(worker, _node("2026-01-01T00:00:00Z"))
    await tasks.sync_shop(worker, str(worker["shop"]))
    other = {
        k: v
        for k, v in _node("2026-10-01T00:00:00Z", title="Still here").items()
        if k not in ("media", "variants", "metafields")
    }
    other["id"] = "gid://shopify/Product/2"
    worker["admin"].lines = [json.dumps(other)]

    await tasks.finish_bulk(worker, str(worker["shop"]), "b1")

    assert await _title(worker["shop"]) == "Still here"


async def test_denied_bulk_export_imports_page_by_page(worker) -> None:
    worker["admin"].bulk_denied = True
    worker["admin"].product = _node(title="Paged")

    await tasks.sync_shop(worker, str(worker["shop"]))

    assert await _title(worker["shop"]) == "Paged"
    async with session_for_shop(worker["shop"]) as session:
        job = (await session.execute(select(SyncJob))).scalar_one()
    assert (job.status, job.processed) == ("completed", 1)


async def test_product_gone_from_shopify_is_deleted_on_upsert(worker) -> None:
    await _upsert(worker, _node())
    await _upsert(worker, None)  # type: ignore[arg-type]
    assert await _count(worker["shop"]) == 0


async def test_delete_removes_the_product(worker) -> None:
    await _upsert(worker, _node())
    await tasks.delete_product(worker, str(worker["shop"]), GID)
    assert await _count(worker["shop"]) == 0


async def test_inventory_update_changes_availability(worker) -> None:
    await _upsert(worker, _node(available=True))
    worker["admin"].product = _node(available=False)
    calls_before = AnswerAnything.calls

    await tasks.update_inventory(worker, str(worker["shop"]), INVENTORY_GID)

    async with session_for_shop(worker["shop"]) as session:
        available = (await session.execute(select(Product.available))).scalar_one()
        variant = (await session.execute(select(Variant.available))).scalar_one()
    assert (available, variant) == (False, False) and AnswerAnything.calls == calls_before


async def test_failed_export_is_shown_after_final_retry(worker) -> None:
    worker["admin"].bulk_status = "FAILED"
    worker["job_try"] = tasks.MAX_TRIES

    await tasks.finish_bulk(worker, str(worker["shop"]), "b1")

    async with session_for_shop(worker["shop"]) as session:
        job = (await session.execute(select(SyncJob))).scalar_one()
    assert job.status == "failed" and "FAILED" in job.error


async def test_early_failure_retries(worker) -> None:
    worker["admin"].bulk_status = "FAILED"

    with pytest.raises(Retry):
        await tasks.finish_bulk(worker, str(worker["shop"]), "b1")


async def test_uninstall_marks_inactive(worker) -> None:
    await tasks.deactivate_shop(worker, str(worker["shop"]))
    async with system_session() as session:
        shop = await session.get(Shop, worker["shop"])
    assert shop is not None and shop.status == "inactive" and shop.access_token_encrypted is None


async def test_shop_redact_deletes_all_store_data(worker, owner_conn) -> None:
    await _upsert(worker, _node())

    await tasks.redact_shop(worker, str(worker["shop"]))

    for table in ("shops", "products", "variants", "product_chunks"):
        column = "id" if table == "shops" else "shop_id"
        count = (
            await owner_conn.execute(
                text(f"SELECT count(*) FROM {table} WHERE {column} = :id"),
                {"id": worker["shop"]},
            )
        ).scalar_one()
        assert count == 0, table
