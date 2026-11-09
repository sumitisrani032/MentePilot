from decimal import Decimal

from shopchat.agents.select import FALLBACK_INTRO, Pick, Selection, make_select
from shopchat.catalog.types import Fact, Provenance
from shopchat.llm.ports import ModelTier
from tests.agent_helpers import candidate, one_section, plan, state
from tests.fakes import FakeStructuredLLM


def _ok(product_id) -> Selection:
    return Selection(
        intro="Try these.", sections=one_section([Pick(product_id=product_id, reason="fits")])
    )


async def test_only_top_30_candidates_are_sent() -> None:
    candidates = [candidate(f"item-{i:02d}") for i in range(35)]
    llm = FakeStructuredLLM([_ok(candidates[0].product_id)])

    await make_select(llm)(state(plan=plan(), candidates=candidates))

    assert "item-29" in llm.calls[0].user and "item-30" not in llm.calls[0].user


async def test_prompt_includes_caveats_and_cautions() -> None:
    fact = Fact(value=20.0, provenance=Provenance.STATED, caveat="wear more")
    item = candidate(facts={"spf": fact}, cautions=["Use at night only"])
    llm = FakeStructuredLLM([_ok(item.product_id)])

    await make_select(llm)(state(plan=plan(), candidates=[item]))

    assert "wear more" in llm.calls[0].user and "Use at night only" in llm.calls[0].user


async def test_prompt_includes_merchant_usage_text() -> None:
    item = candidate()
    item.usage = ["Apply a thin layer each morning"]
    llm = FakeStructuredLLM([_ok(item.product_id)])

    await make_select(llm)(state(plan=plan(), candidates=[item]))

    assert "Apply a thin layer each morning" in llm.calls[0].user


async def test_inferred_facts_are_labelled_in_prompt() -> None:
    item = candidate(facts={"use": Fact(value="beach", provenance=Provenance.INFERRED)})
    llm = FakeStructuredLLM([_ok(item.product_id)])

    await make_select(llm)(state(plan=plan(), candidates=[item]))

    assert "use=beach (likely)" in llm.calls[0].user


async def test_prompt_does_not_contain_prices() -> None:
    item = candidate()
    llm = FakeStructuredLLM([_ok(item.product_id)])

    await make_select(llm)(state(plan=plan(), candidates=[item]))

    assert '"price"' not in llm.calls[0].user


async def test_selection_uses_the_smart_tier() -> None:
    item = candidate()
    llm = FakeStructuredLLM([_ok(item.product_id)])

    await make_select(llm)(state(plan=plan(), candidates=[item]))

    assert llm.calls[0].tier is ModelTier.SMART


async def test_selection_failure_retries_once_then_shows_top_candidates() -> None:
    items = [candidate(f"item-{i}") for i in range(7)]
    llm = FakeStructuredLLM(fail_with=RuntimeError("provider down"))

    selection = (await make_select(llm)(state(plan=plan(), candidates=items)))["selection"]

    assert len(llm.calls) == 2
    assert selection.intro == FALLBACK_INTRO
    assert [pick.product_id for pick in selection.picks] == [i.product_id for i in items[:5]]


async def test_candidates_are_ranked_by_cost_without_showing_prices() -> None:
    cheap, dear = candidate("cheap"), candidate("dear")
    cheap.min_price, dear.min_price = Decimal("5"), Decimal("50")
    llm = FakeStructuredLLM([_ok(cheap.product_id)])

    await make_select(llm)(state(plan=plan(), candidates=[dear, cheap]))

    assert '"cost_rank": 1' in llm.calls[0].user and '"cost_rank": 2' in llm.calls[0].user
    assert "50" not in llm.calls[0].user.split("<candidates>")[1].split("cost_rank")[0]
