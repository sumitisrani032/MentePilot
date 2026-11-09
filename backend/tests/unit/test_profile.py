from decimal import Decimal

from shopchat.catalog.profile import ProfileNarrative, build_profile
from shopchat.catalog.types import Fact, Provenance
from tests.factories import normalized
from tests.fakes import FakeStructuredLLM


def _llm(has_skincare: bool = False) -> FakeStructuredLLM:
    return FakeStructuredLLM(
        [ProfileNarrative(summary="A store.", vocabulary=["tee"], has_skincare=has_skincare)]
    )


def _fact(value: object, provenance: Provenance = Provenance.STATED) -> Fact:
    return Fact(value=value, provenance=provenance)  # type: ignore[arg-type]


async def test_inferred_facts_do_not_count_as_stated() -> None:
    products = [
        normalized("a", facts={"x": _fact(True)}),
        normalized("b", facts={"x": _fact(True, Provenance.INFERRED)}),
    ]

    profile = await build_profile(products, _llm())

    assert profile.facets["x"].stated_count == 1


async def test_price_range_comes_from_variants() -> None:
    products = [normalized("a", price="5.50"), normalized("b", price="40.00")]

    profile = await build_profile(products, _llm())

    assert (profile.price_min, profile.price_max) == (Decimal("5.50"), Decimal("40.00"))


async def test_clothing_catalog_produces_clothing_facets() -> None:
    products = [normalized("a", category="Apparel > Shirts", facts={"fabric": _fact("linen")})]

    profile = await build_profile(products, _llm())

    assert profile.categories == ["Apparel > Shirts"]
    assert profile.facets["fabric"].top_values == ["linen"]
    assert profile.has_skincare is False


async def test_list_values_are_counted_individually() -> None:
    products = [normalized("a", facts={"climate": _fact(["hot", "humid"])})]

    profile = await build_profile(products, _llm())

    assert sorted(profile.facets["climate"].top_values) == ["hot", "humid"]
    assert profile.facets["climate"].value_type == "list"


async def test_product_count_is_recorded() -> None:
    assert (await build_profile([normalized("a"), normalized("b")], _llm())).product_count == 2


async def test_empty_catalog_makes_no_llm_call() -> None:
    llm = FakeStructuredLLM()

    profile = await build_profile([], llm)

    assert llm.calls == [] and profile.facets == {}
