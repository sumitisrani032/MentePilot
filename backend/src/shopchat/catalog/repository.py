"""Read and write catalog-level data for a store."""

from collections import defaultdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from shopchat.catalog.profile import CatalogProfile
from shopchat.catalog.types import Fact, NormalizedProduct, NormalizedVariant
from shopchat.db.models import CatalogProfileRow, Product, Variant
from shopchat.db.session import session_for_shop


async def load_products(shop_id: UUID) -> list[NormalizedProduct]:
    async with session_for_shop(shop_id) as session:
        products = (await session.execute(select(Product))).scalars().all()
        variants = (await session.execute(select(Variant))).scalars().all()
    by_product: dict[UUID, list[Variant]] = defaultdict(list)
    for variant in variants:
        by_product[variant.product_id].append(variant)
    return [_to_normalized(product, by_product[product.id]) for product in products]


def _to_normalized(product: Product, variants: list[Variant]) -> NormalizedProduct:
    return NormalizedProduct(
        source_id=product.source_id,
        handle=product.handle,
        title=product.title,
        description=product.description,
        vendor=product.vendor,
        product_type=product.product_type,
        category=product.category,
        tags=product.tags,
        status=product.status,
        image_urls=product.image_urls,
        currency=product.currency,
        source_updated_at=product.source_updated_at,
        variants=[
            NormalizedVariant(
                source_id=variant.source_id,
                inventory_item_id=variant.inventory_item_id,
                title=variant.title,
                options=variant.options,
                price=variant.price,
                compare_at_price=variant.compare_at_price,
                available=variant.available,
            )
            for variant in variants
        ],
        raw_attributes={},
        facts={key: Fact.model_validate(value) for key, value in product.facts.items()},
    )


async def save_profile(shop_id: UUID, profile: CatalogProfile) -> None:
    payload = profile.model_dump(mode="json")
    statement = insert(CatalogProfileRow).values(shop_id=shop_id, profile=payload)
    statement = statement.on_conflict_do_update(
        index_elements=[CatalogProfileRow.shop_id], set_={"profile": payload}
    )
    async with session_for_shop(shop_id) as session:
        await session.execute(statement)


async def load_profile(shop_id: UUID) -> CatalogProfile | None:
    async with session_for_shop(shop_id) as session:
        row = await session.get(CatalogProfileRow, shop_id)
    return CatalogProfile.model_validate(row.profile) if row else None
