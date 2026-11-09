"""ORM models. Every table except ``shops`` is isolated per store by row-level security."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    Computed,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIMENSIONS = 1536


class Base(DeclarativeBase):
    pass


class Shop(Base):
    __tablename__ = "shops"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    domain: Mapped[str] = mapped_column(Text, unique=True)
    access_token_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    refresh_token_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    access_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scopes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(Text, default="active")
    features: Mapped[dict[str, bool]] = mapped_column(JSONB, default=dict)
    installed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    uninstalled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def _shop_fk() -> Mapped[UUID]:
    return mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), index=True)


class CatalogProfileRow(Base):
    __tablename__ = "catalog_profiles"

    shop_id: Mapped[UUID] = mapped_column(
        ForeignKey("shops.id", ondelete="CASCADE"), primary_key=True
    )
    profile: Mapped[dict[str, Any]] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("shop_id", "source_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    shop_id: Mapped[UUID] = _shop_fk()
    source_id: Mapped[str] = mapped_column(Text)
    handle: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    vendor: Mapped[str] = mapped_column(Text, default="")
    product_type: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    status: Mapped[str] = mapped_column(Text)
    image_urls: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    min_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    max_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    compare_at_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(Text)
    available: Mapped[bool]
    facts: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    content_hash: Mapped[str] = mapped_column(Text)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Variant(Base):
    __tablename__ = "variants"
    __table_args__ = (UniqueConstraint("shop_id", "source_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    shop_id: Mapped[UUID] = _shop_fk()
    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[str] = mapped_column(Text)
    inventory_item_id: Mapped[str | None] = mapped_column(Text, index=True)
    title: Mapped[str] = mapped_column(Text, default="")
    options: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    compare_at_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    available: Mapped[bool]


class ProductChunk(Base):
    __tablename__ = "product_chunks"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    shop_id: Mapped[UUID] = _shop_fk()
    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    search_vector: Mapped[Any] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', text)", persisted=True)
    )


class SyncJob(Base):
    __tablename__ = "sync_jobs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    shop_id: Mapped[UUID] = _shop_fk()
    type: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    shop_id: Mapped[UUID] = _shop_fk()
    kind: Mapped[str] = mapped_column(Text)
    quantity: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
