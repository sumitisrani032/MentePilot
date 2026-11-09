"""Source-independent product shapes used by the whole catalog pipeline."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field

FactValue = bool | float | str | list[str]


class Provenance(StrEnum):
    STATED = "stated"
    INFERRED = "inferred"


class Fact(BaseModel):
    value: FactValue
    provenance: Provenance
    caveat: str | None = None


class NormalizedVariant(BaseModel):
    source_id: str
    inventory_item_id: str | None = None
    title: str
    options: dict[str, str]
    price: Decimal
    compare_at_price: Decimal | None = None
    available: bool


class NormalizedProduct(BaseModel):
    source_id: str
    handle: str
    title: str
    description: str
    vendor: str
    product_type: str
    category: str
    tags: list[str]
    status: str
    image_urls: list[str]
    currency: str
    source_updated_at: datetime | None = None
    variants: list[NormalizedVariant]
    raw_attributes: dict[str, str]
    facts: dict[str, Fact] = Field(default_factory=dict)
