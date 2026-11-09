from shopchat.catalog.profile import FacetSummary
from shopchat.search.filters import named_features
from tests.agent_helpers import profile


def _store(**facets: FacetSummary) -> object:
    return profile(facets=facets)


_YES_NO = FacetSummary(stated_count=3, value_type="bool", top_values=["True"])


def test_a_named_feature_becomes_required() -> None:
    assert named_features("waterproof makeup for a pool party", _store(waterproof=_YES_NO)) == {
        "waterproof": True
    }


def test_separated_spelling_still_names_the_feature() -> None:
    assert named_features("a water-proof mascara", _store(waterproof=_YES_NO)) == {
        "waterproof": True
    }
    assert named_features("water proof mascara", _store(waterproof=_YES_NO)) == {"waterproof": True}


def test_multi_word_facet_keys_match_in_any_separator() -> None:
    assert named_features("Cruelty free lipstick", _store(cruelty_free=_YES_NO)) == {
        "cruelty_free": True
    }


def test_declined_features_are_not_required() -> None:
    store = _store(waterproof=_YES_NO)
    assert named_features("it doesn't need to be waterproof", store) == {}
    assert named_features("not waterproof please", store) == {}
    assert named_features("a non-waterproof mascara", store) == {}
    assert named_features("anything without waterproof claims", store) == {}


def test_part_of_a_longer_word_does_not_count() -> None:
    assert named_features("a veganish snack", _store(vegan=_YES_NO)) == {}


def test_only_yes_no_facets_the_store_states_are_required() -> None:
    unstated = FacetSummary(stated_count=0, value_type="bool", top_values=[])
    number = FacetSummary(stated_count=3, value_type="number", top_values=["30"])
    text = FacetSummary(stated_count=3, value_type="text", top_values=["linen"])
    store = _store(waterproof=unstated, spf=number, linen=text)
    assert named_features("waterproof linen with spf", store) == {}


def test_a_store_that_only_states_false_cannot_satisfy_the_feature() -> None:
    only_false = FacetSummary(stated_count=3, value_type="bool", top_values=["False"])
    assert named_features("waterproof boots", _store(waterproof=only_false)) == {}


def test_free_text_typed_as_yes_no_is_never_required() -> None:
    mislabelled = FacetSummary(stated_count=3, value_type="bool", top_values=["True", "Unscented"])
    assert named_features("a perfume with a nice scent", _store(scent=mislabelled)) == {}
