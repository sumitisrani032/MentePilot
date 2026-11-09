from shopchat.agents.state import Turn
from shopchat.agents.understand import make_understand
from shopchat.catalog.profile import FacetSummary
from shopchat.search.types import Requirements
from tests.agent_helpers import plan, profile, state
from tests.fakes import FakeStructuredLLM


async def test_prompt_contains_store_profile_summary() -> None:
    llm = FakeStructuredLLM([plan()])
    await make_understand(llm)(state())
    assert "A store selling summer clothes." in llm.calls[0].user


async def test_prompt_contains_known_facets() -> None:
    llm = FakeStructuredLLM([plan()])
    await make_understand(llm)(state())
    assert "fabric" in llm.calls[0].user and "linen" in llm.calls[0].user


async def test_prompt_contains_history_for_follow_ups() -> None:
    llm = FakeStructuredLLM([plan()])
    await make_understand(llm)(state(history=[Turn(role="customer", text="red shirts")]))
    assert "red shirts" in llm.calls[0].user


async def test_only_yes_no_and_number_facets_are_firm() -> None:
    facets = {
        "fabric": FacetSummary(stated_count=3, value_type="text", top_values=["linen"]),
        "waterproof": FacetSummary(stated_count=3, value_type="bool", top_values=["True"]),
    }
    planned = plan(
        firm=Requirements(facts={"fabric": "linen", "waterproof": True, "made_up": True})
    )
    llm = FakeStructuredLLM([planned])

    result = (await make_understand(llm)(state(profile=profile(facets=facets))))["plan"]

    assert result.firm.facts == {"waterproof": True}
    assert any("fabric" in preference for preference in result.soft_preferences)
    assert any("made up" in preference for preference in result.soft_preferences)


async def test_a_named_feature_is_firm_even_when_the_model_leaves_it_out() -> None:
    facets = {"waterproof": FacetSummary(stated_count=3, value_type="bool", top_values=["True"])}
    llm = FakeStructuredLLM([plan(firm=Requirements())])

    result = await make_understand(llm)(
        state(profile=profile(facets=facets), message="waterproof makeup for a pool party")
    )

    assert result["plan"].firm.facts == {"waterproof": True}
