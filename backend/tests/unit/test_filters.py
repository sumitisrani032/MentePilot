from decimal import Decimal

from shopchat.catalog.profile import CatalogProfile, FacetSummary
from shopchat.search.filters import effective_requirements
from shopchat.search.types import Requirements


def _profile(stated_count: int) -> CatalogProfile:
    return CatalogProfile(
        categories=[],
        facets={
            "waterproof": FacetSummary(
                stated_count=stated_count, value_type="bool", top_values=["True"]
            )
        },
        price_min=Decimal(1),
        price_max=Decimal(100),
        currency="USD",
        summary="",
        vocabulary=[],
        has_skincare=False,
    )


def test_attribute_with_no_stated_values_becomes_soft() -> None:
    firm, soft = effective_requirements(Requirements(facts={"waterproof": True}), _profile(0))
    assert firm.facts == {} and "waterproof" in soft[0]


def test_unknown_attribute_becomes_soft() -> None:
    firm, soft = effective_requirements(Requirements(facts={"sparkly": True}), _profile(5))
    assert firm.facts == {} and "sparkly" in soft[0]


def test_text_facet_is_never_firm() -> None:
    profile = _profile(5)
    profile.facets["waterproof"].value_type = "text"
    firm, soft = effective_requirements(Requirements(facts={"waterproof": "yes"}), profile)
    assert firm.facts == {} and soft


def test_false_never_excludes_products() -> None:
    firm, soft = effective_requirements(Requirements(facts={"waterproof": False}), _profile(5))
    assert firm.facts == {} and soft


def test_stated_attribute_stays_firm() -> None:
    firm, soft = effective_requirements(Requirements(facts={"waterproof": True}), _profile(5))
    assert firm.facts == {"waterproof": True} and soft == []


def test_price_is_always_firm() -> None:
    firm, _ = effective_requirements(Requirements(max_price=Decimal("20")), _profile(0))
    assert firm.max_price == Decimal("20")


def test_text_true_becomes_a_real_boolean() -> None:
    firm, _ = effective_requirements(Requirements(facts={"waterproof": "True"}), _profile(5))
    assert firm.facts == {"waterproof": True}


def test_value_of_the_wrong_type_becomes_soft() -> None:
    firm, soft = effective_requirements(Requirements(facts={"waterproof": "maybe"}), _profile(5))
    assert firm.facts == {} and soft
