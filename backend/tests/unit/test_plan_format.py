from decimal import Decimal

from pydantic import BaseModel, TypeAdapter

from shopchat.agents.router import RouterDecision, make_router
from shopchat.agents.state import Intent
from shopchat.agents.understand import make_understand
from shopchat.search.types import Requirements, SearchPlan
from tests.agent_helpers import state


class _Invalid:
    """Fails the way a model reply with the wrong shape does."""

    calls = 0

    async def generate(self, system, user, schema: type[BaseModel], tier, images=()):
        _Invalid.calls += 1
        return TypeAdapter(schema).validate_python({"not": "valid"})


def test_null_parts_of_a_plan_are_tolerated() -> None:
    plan = SearchPlan.model_validate(
        {"firm": None, "soft_preferences": None, "search_phrases": "tee"}
    )
    assert plan.search_phrases == ["tee"] and plan.soft_preferences == [] and plan.firm.facts == {}


def test_list_fact_values_are_dropped() -> None:
    requirements = Requirements.model_validate({"facts": {"kind": ["a", "b"], "fit": "slim"}})
    assert requirements.facts == {"fit": "slim"}


def test_wordy_price_is_dropped() -> None:
    assert Requirements.model_validate({"max_price": "under 20"}).max_price is None


def test_numeric_price_is_kept() -> None:
    assert Requirements.model_validate({"max_price": "20"}).max_price == Decimal("20")


async def test_malformed_plan_falls_back_to_searching_the_message() -> None:
    plan = (await make_understand(_Invalid())(state(message="beach day")))["plan"]
    assert plan.search_phrases == ["beach day"]


async def test_malformed_routing_falls_back_to_search() -> None:
    result = await make_router(_Invalid())(state())
    assert result["intent"] is Intent.PRODUCT_SEARCH
    assert isinstance(RouterDecision(intent=result["intent"]), RouterDecision)
