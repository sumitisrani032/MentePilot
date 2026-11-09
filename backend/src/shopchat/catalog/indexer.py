"""Write products and their embeddings to the store's RAG index."""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from itertools import batched
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from shopchat.catalog.chunks import build_chunks
from shopchat.catalog.types import NormalizedProduct
from shopchat.db.models import Product, ProductChunk, Variant
from shopchat.db.session import session_for_shop
from shopchat.llm.ports import Embedder

_BATCH_SIZE = 100


@dataclass(frozen=True)
class IndexResult:
    indexed: int
    skipped: int


def content_hash(product: NormalizedProduct) -> str:
    """Hash of the source data. Facts are excluded so unchanged products skip the LLM."""
    payload = product.model_dump_json(exclude={"facts", "source_updated_at"})
    return hashlib.sha256(payload.encode()).hexdigest()


async def select_changed(
    shop_id: UUID, products: Sequence[NormalizedProduct]
) -> list[NormalizedProduct]:
    async with session_for_shop(shop_id) as session:
        rows = await session.execute(select(Product.source_id, Product.content_hash))
        existing = {source_id: digest for source_id, digest in rows}
    return [p for p in products if existing.get(p.source_id) != content_hash(p)]


async def save_new_records(shop_id: UUID, products: Sequence[NormalizedProduct]) -> None:
    """Store products we have never seen, before any paid step can fail.

    The blank hash marks a record as not yet indexed. Existing products are left alone so a
    failed update cannot remove them from search.
    """
    async with session_for_shop(shop_id) as session:
        known = set((await session.execute(select(Product.source_id))).scalars())
        for product in products:
            if product.source_id in known:
                continue
            values = {**_product_values(product), "content_hash": ""}
            row = Product(id=uuid4(), shop_id=shop_id, source_id=product.source_id, **values)
            session.add(row)
            await session.flush()
            session.add_all(_variant_rows(shop_id, row.id, product))


async def index_products(
    shop_id: UUID, products: Sequence[NormalizedProduct], embedder: Embedder
) -> IndexResult:
    changed = await select_changed(shop_id, products)
    for batch in batched(changed, _BATCH_SIZE):
        await _index_batch(shop_id, batch, embedder)
    return IndexResult(indexed=len(changed), skipped=len(products) - len(changed))


async def _index_batch(
    shop_id: UUID, products: Sequence[NormalizedProduct], embedder: Embedder
) -> None:
    drafts = [(product, draft) for product in products for draft in build_chunks(product)]
    # Embedding happens before the transaction opens, so no connection waits on the network.
    vectors = await embedder.embed([draft.text for _, draft in drafts])
    async with session_for_shop(shop_id) as session:
        ids = {p.source_id: await _upsert_product(session, shop_id, p) for p in products}
        session.add_all(
            ProductChunk(
                id=uuid4(),
                shop_id=shop_id,
                product_id=ids[product.source_id],
                kind=draft.kind,
                text=draft.text,
                embedding=vector,
            )
            for (product, draft), vector in zip(drafts, vectors, strict=True)
            if ids[product.source_id] is not None
        )


async def _upsert_product(
    session: AsyncSession, shop_id: UUID, product: NormalizedProduct
) -> UUID | None:
    values = {**_product_values(product), "indexed_at": datetime.now(UTC)}
    insert_values = insert(Product).values(
        id=uuid4(), shop_id=shop_id, source_id=product.source_id, **values
    )
    upsert = insert_values.on_conflict_do_update(
        index_elements=[Product.shop_id, Product.source_id],
        set_=values,
        # A webhook can land while an export is still being processed.
        where=or_(
            Product.source_updated_at.is_(None),
            insert_values.excluded.source_updated_at.is_(None),
            Product.source_updated_at <= insert_values.excluded.source_updated_at,
        ),
    ).returning(Product.id)
    product_id = (await session.execute(upsert)).scalar_one_or_none()
    if product_id is None:
        return None

    await session.execute(delete(ProductChunk).where(ProductChunk.product_id == product_id))
    await session.execute(delete(Variant).where(Variant.product_id == product_id))
    session.add_all(_variant_rows(shop_id, product_id, product))
    await session.flush()
    return product_id


def _variant_rows(shop_id: UUID, product_id: UUID, product: NormalizedProduct) -> list[Variant]:
    return [
        Variant(
            id=uuid4(),
            shop_id=shop_id,
            product_id=product_id,
            source_id=variant.source_id,
            inventory_item_id=variant.inventory_item_id,
            title=variant.title,
            options=variant.options,
            price=variant.price,
            compare_at_price=variant.compare_at_price,
            available=variant.available,
        )
        for variant in product.variants
    ]


def _product_values(product: NormalizedProduct) -> dict[str, Any]:
    prices = [variant.price for variant in product.variants] or [Decimal(0)]
    compare_at = [v.compare_at_price for v in product.variants if v.compare_at_price is not None]
    return {
        "handle": product.handle,
        "title": product.title,
        "description": product.description,
        "vendor": product.vendor,
        "product_type": product.product_type,
        "category": product.category,
        "tags": product.tags,
        "status": product.status,
        "image_urls": product.image_urls,
        "min_price": min(prices),
        "max_price": max(prices),
        "compare_at_price": min(compare_at, default=None),
        "currency": product.currency,
        "available": any(variant.available for variant in product.variants),
        "facts": {key: fact.model_dump(mode="json") for key, fact in product.facts.items()},
        "content_hash": content_hash(product),
        "source_updated_at": product.source_updated_at,
    }
