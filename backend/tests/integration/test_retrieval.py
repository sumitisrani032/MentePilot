from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select

from shopchat.catalog.indexer import index_products
from shopchat.catalog.profile import CatalogProfile, FacetSummary
from shopchat.catalog.types import Fact, Provenance
from shopchat.db.models import Product
from shopchat.db.session import session_for_shop
from shopchat.search.hybrid import product_detail_chunks, retrieve
from shopchat.search.types import Candidate, Requirements, SearchPlan
from tests.conftest import TwoShops
from tests.factories import normalized
from tests.fakes import FakeEmbedder


def _stated(value: object) -> dict[str, Fact]:
    return {"waterproof": Fact(value=value, provenance=Provenance.STATED)}  # type: ignore[arg-type]


PROFILE = CatalogProfile(
    categories=[],
    facets={"waterproof": FacetSummary(stated_count=2, value_type="bool", top_values=[])},
    price_min=Decimal(1),
    price_max=Decimal(100),
    currency="USD",
    summary="",
    vocabulary=[],
    has_skincare=False,
)


def _plan(**firm: object) -> SearchPlan:
    return SearchPlan(firm=Requirements(**firm), search_phrases=["product"])  # type: ignore[arg-type]


def _titles(candidates: list[Candidate]) -> set[str]:
    return {candidate.title for candidate in candidates}


@pytest.fixture
async def seeded(two_shops: TwoShops) -> UUID:
    products = [
        normalized("wp", title="waterproof-product", facts=_stated(True), price="15.00"),
        normalized("nwp", title="not-waterproof-product", facts=_stated(False), price="50.00"),
        normalized(
            "inf",
            title="inferred-product",
            facts={"waterproof": Fact(value=True, provenance=Provenance.INFERRED)},
            price="30.00",
        ),
        normalized("sold", title="sold-out-product", available=False),
        normalized("draft", title="draft-product", status="draft"),
    ]
    await index_products(two_shops.a, products, FakeEmbedder())
    await index_products(
        two_shops.b, [normalized("other", title="other-shop-product")], FakeEmbedder()
    )
    return two_shops.a


async def test_retrieval_never_returns_another_shop(seeded: UUID) -> None:
    assert "other-shop-product" not in _titles(
        await retrieve(seeded, _plan(), PROFILE, FakeEmbedder())
    )


async def test_negated_fact_fails_firm_requirement(seeded: UUID) -> None:
    found = await retrieve(seeded, _plan(facts={"waterproof": True}), PROFILE, FakeEmbedder())
    assert "not-waterproof-product" not in _titles(found)
    assert "waterproof-product" in _titles(found)


async def test_inferred_fact_cannot_satisfy_firm_requirement(seeded: UUID) -> None:
    found = await retrieve(seeded, _plan(facts={"waterproof": True}), PROFILE, FakeEmbedder())
    assert "inferred-product" not in _titles(found)


async def test_all_sold_out_product_is_excluded(seeded: UUID) -> None:
    assert "sold-out-product" not in _titles(
        await retrieve(seeded, _plan(), PROFILE, FakeEmbedder())
    )


async def test_draft_product_is_excluded(seeded: UUID) -> None:
    assert "draft-product" not in _titles(await retrieve(seeded, _plan(), PROFILE, FakeEmbedder()))


async def test_price_range_filters(seeded: UUID) -> None:
    found = await retrieve(seeded, _plan(max_price=Decimal("20")), PROFILE, FakeEmbedder())
    assert _titles(found) == {"waterproof-product"}


async def test_numeric_fact_is_a_real_minimum(two_shops: TwoShops) -> None:
    def spf(source_id: str, value: float):
        fact = Fact(value=value, provenance=Provenance.STATED)
        return normalized(source_id, title=source_id, facts={"spf": fact})

    await index_products(two_shops.a, [spf("low", 15.0), spf("high", 50.0)], FakeEmbedder())
    profile = PROFILE.model_copy(
        update={"facets": {"spf": FacetSummary(stated_count=2, value_type="number", top_values=[])}}
    )

    found = await retrieve(two_shops.a, _plan(facts={"spf": 30.0}), profile, FakeEmbedder())

    assert _titles(found) == {"high"}


async def test_no_search_phrases_returns_nothing(seeded: UUID) -> None:
    plan = SearchPlan(search_phrases=[])
    assert await retrieve(seeded, plan, PROFILE, FakeEmbedder()) == []


async def test_punctuation_only_phrase_does_not_fail(seeded: UUID) -> None:
    plan = SearchPlan(search_phrases=["?!"])
    assert isinstance(await retrieve(seeded, plan, PROFILE, FakeEmbedder()), list)


async def test_detail_chunks_are_limited_to_the_product(two_shops: TwoShops) -> None:
    await index_products(
        two_shops.a,
        [
            normalized("a", raw={"How to use": "apply-a " * 20}),
            normalized("b", raw={"How to use": "apply-b " * 20}),
        ],
        FakeEmbedder(),
    )
    async with session_for_shop(two_shops.a) as session:
        target = (
            await session.execute(select(Product.id).where(Product.source_id == "a"))
        ).scalar_one()

    chunks = await product_detail_chunks(two_shops.a, target, "how do I use it", FakeEmbedder())

    assert chunks and not any("apply-b" in chunk for chunk in chunks)
