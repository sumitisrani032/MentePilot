"""Product cards. Every customer-visible price, link and image comes from here."""

from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select

from shopchat.db.models import Product
from shopchat.db.session import session_for_shop

_MAX_DESCRIPTION_CHARS = 500


class ProductCard(BaseModel):
    id: UUID
    title: str
    vendor: str = ""
    price: Decimal
    compare_at_price: Decimal | None
    currency: str
    image_url: str | None
    url: str
    reason: str = ""
    description: str = ""


class CardSection(BaseModel):
    heading: str
    detail: str
    cards: list[ProductCard]
    how_to_use: list[str]
    tips: list[str]


async def load_cards(shop_id: UUID, ids: Sequence[UUID], shop_domain: str) -> list[ProductCard]:
    """Load cards in the given order. Products no longer for sale are dropped."""
    statement = select(Product).where(
        Product.id.in_(ids), Product.status == "active", Product.available.is_(True)
    )
    async with session_for_shop(shop_id) as session:
        products = {p.id: p for p in (await session.execute(statement)).scalars()}
    return [_card(products[i], shop_domain) for i in ids if i in products]


def _card(product: Product, shop_domain: str) -> ProductCard:
    compare_at = product.compare_at_price
    return ProductCard(
        id=product.id,
        title=product.title,
        vendor=product.vendor,
        description=product.description[:_MAX_DESCRIPTION_CHARS],
        price=product.min_price,
        compare_at_price=compare_at if compare_at and compare_at > product.min_price else None,
        currency=product.currency,
        image_url=product.image_urls[0] if product.image_urls else None,
        url=f"https://{shop_domain}/products/{product.handle}",
    )
