"""Shared builders for agent tests."""

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from shopchat.agents.state import ChatState, Pick, Section
from shopchat.catalog.profile import CatalogProfile, FacetSummary
from shopchat.catalog.types import Fact
from shopchat.search.types import Candidate, Requirements, SearchPlan


def profile(**overrides: Any) -> CatalogProfile:
    values: dict[str, Any] = {
        "categories": ["Apparel"],
        "facets": {"fabric": FacetSummary(stated_count=3, value_type="text", top_values=["linen"])},
        "price_min": Decimal(1),
        "price_max": Decimal(100),
        "currency": "USD",
        "summary": "A store selling summer clothes.",
        "vocabulary": ["tee"],
        "has_skincare": False,
        "product_count": 10,
    }
    values.update(overrides)
    return CatalogProfile(**values)


def candidate(
    title: str = "Linen Shirt",
    product_id: UUID | None = None,
    facts: dict[str, Fact] | None = None,
    cautions: list[str] | None = None,
) -> Candidate:
    return Candidate(
        product_id=product_id or uuid4(),
        title=title,
        vendor="Acme",
        product_type="Shirt",
        facts=facts or {},
        best_chunk=f"{title} summary",
        score=1.0,
        cautions=cautions or [],
    )


def one_section(picks: list[Pick]) -> list[Section]:
    return [Section(heading="Top picks", detail="Good fits.", picks=picks)]


def plan(**overrides: Any) -> SearchPlan:
    values: dict[str, Any] = {
        "firm": Requirements(),
        "soft_preferences": [],
        "search_phrases": ["linen shirt"],
    }
    values.update(overrides)
    return SearchPlan(**values)


def state(**overrides: Any) -> ChatState:
    values: dict[str, Any] = {
        "shop_id": uuid4(),
        "message": "I'm going to the beach",
        "image_context": None,
        "history": [],
        "profile": profile(),
        "retries": 0,
    }
    values.update(overrides)
    return values  # type: ignore[return-value]
