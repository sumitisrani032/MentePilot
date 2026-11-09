"""Builders for test data."""

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from shopchat.catalog.types import Fact, NormalizedProduct, NormalizedVariant
from shopchat.db.models import Product

_COMPLETE_DESCRIPTION = (
    "A test product with a description that is comfortably long enough to count as complete."
)


def make_product(shop_id: UUID, source_id: str = "p-1", **overrides: Any) -> Product:
    values: dict[str, Any] = {
        "id": uuid4(),
        "shop_id": shop_id,
        "source_id": source_id,
        "handle": f"handle-{source_id}",
        "title": f"Product {source_id}",
        "description": "A product used in tests.",
        "vendor": "Test Vendor",
        "product_type": "Test Type",
        "category": "Test > Category",
        "tags": [],
        "status": "active",
        "image_urls": ["https://cdn.example.test/1.jpg"],
        "min_price": Decimal("10.00"),
        "max_price": Decimal("10.00"),
        "compare_at_price": None,
        "currency": "USD",
        "available": True,
        "facts": {},
        "content_hash": f"hash-{source_id}",
    }
    values.update(overrides)
    return Product(**values)


def normalized(
    source_id: str = "p-1",
    title: str = "Test Product",
    description: str = _COMPLETE_DESCRIPTION,
    raw: dict[str, str] | None = None,
    facts: dict[str, Fact] | None = None,
    price: str = "10.00",
    available: bool = True,
    **overrides: Any,
) -> NormalizedProduct:
    values: dict[str, Any] = {
        "source_id": source_id,
        "handle": source_id,
        "title": title,
        "description": description,
        "vendor": "Test Vendor",
        "product_type": "Test Type",
        "category": "Test > Category",
        "tags": [],
        "status": "active",
        "image_urls": [],
        "currency": "USD",
        "variants": [
            NormalizedVariant(
                source_id=f"{source_id}-v1",
                title="Default",
                options={},
                price=Decimal(price),
                available=available,
            )
        ],
        "raw_attributes": raw or {},
        "facts": facts or {},
    }
    values.update(overrides)
    return NormalizedProduct(**values)
