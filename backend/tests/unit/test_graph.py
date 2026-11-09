from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from shopchat.agents.answers import (
    ENGLISH_ONLY_REPLY,
    NO_MATCH_REPLY,
    OUT_OF_SCOPE_REPLY,
    UNCLEAR_REPLY,
    UNKNOWN_DETAIL_REPLY,
    DetailAnswer,
)
from shopchat.agents.graph import build_graph
from shopchat.agents.router import RouterDecision
from shopchat.agents.select import Pick, Selection
from shopchat.agents.state import Intent, Turn
from shopchat.search.types import Candidate, Requirements, SearchPlan
from tests.agent_helpers import candidate, one_section, plan, state
from tests.fakes import FakeStreamer, FakeStructuredLLM, fake_bundle


@dataclass
class FakeRetrieve:
    results: list[list[Candidate]] = field(default_factory=list)
    plans: list[SearchPlan] = field(default_factory=list)

    async def __call__(self, shop_id: UUID, p: SearchPlan, profile: Any, embedder: Any):
        self.plans.append(p)
        return self.results.pop(0) if self.results else []


@dataclass
class FakeDetail:
    chunks: list[str] = field(default_factory=list)

    async def __call__(self, shop_id: UUID, product_id: UUID, query: str, embedder: Any):
        return self.chunks


async def _no_detail(*_: Any) -> list[str]:
    return []


def _router(intent: Intent, focus: UUID | None = None) -> RouterDecision:
    return RouterDecision(intent=intent, focus_product_id=focus)


def _two_picks(items: list[Candidate]) -> Selection:
    picks = [Pick(product_id=i.product_id, reason="fits") for i in items[:2]]
    return Selection(intro="Try these.", sections=one_section(picks))


async def test_small_talk_skips_retrieval() -> None:
    llm = FakeStructuredLLM([_router(Intent.SMALL_TALK)])
    retrieve = FakeRetrieve()
    graph = build_graph(fake_bundle(llm, FakeStreamer(["Hi!"])), retrieve, _no_detail)

    result = await graph.ainvoke(state(message="hello"))

    assert retrieve.plans == [] and result["answer"] == "Hi!"


async def test_unclear_message_asks_for_more_without_searching() -> None:
    llm = FakeStructuredLLM([_router(Intent.UNCLEAR)])
    retrieve = FakeRetrieve()
    graph = build_graph(fake_bundle(llm), retrieve, _no_detail)

    result = await graph.ainvoke(state(message="asdf"))

    assert result["answer"] == UNCLEAR_REPLY and retrieve.plans == []


async def test_off_topic_message_gets_a_helpful_reply() -> None:
    llm = FakeStructuredLLM([_router(Intent.OUT_OF_SCOPE)])
    graph = build_graph(fake_bundle(llm), FakeRetrieve(), _no_detail)

    result = await graph.ainvoke(state(message="who won the match"))

    assert result["answer"] == OUT_OF_SCOPE_REPLY


async def test_non_english_gets_english_only_reply() -> None:
    llm = FakeStructuredLLM([_router(Intent.NON_ENGLISH)])
    graph = build_graph(fake_bundle(llm), FakeRetrieve(), _no_detail)

    result = await graph.ainvoke(state(message="hola"))

    assert result["answer"] == ENGLISH_ONLY_REPLY


async def test_full_search_returns_validated_picks() -> None:
    items = [candidate("a"), candidate("b")]
    llm = FakeStructuredLLM([_router(Intent.PRODUCT_SEARCH), plan(), _two_picks(items)])
    graph = build_graph(fake_bundle(llm), FakeRetrieve([items]), _no_detail)

    result = await graph.ainvoke(state())

    assert [p.product_id for p in result["validated"].picks] == [i.product_id for i in items]


async def test_retry_happens_at_most_once() -> None:
    one = [candidate("a")]
    weak = Selection(intro="Hm.", sections=[], too_few=True)
    llm = FakeStructuredLLM([_router(Intent.PRODUCT_SEARCH), plan(), weak, weak])
    retrieve = FakeRetrieve([one, one, one])
    graph = build_graph(fake_bundle(llm), retrieve, _no_detail)

    await graph.ainvoke(state())

    assert len(retrieve.plans) == 2


async def test_no_results_retries_without_strict_fact_filters() -> None:
    planned = plan(firm=Requirements(facts={"waterproof": True}, max_price=Decimal("20")))
    items = [candidate("a"), candidate("b")]
    llm = FakeStructuredLLM([_router(Intent.PRODUCT_SEARCH), planned, _two_picks(items)])
    retrieve = FakeRetrieve([[], items])
    graph = build_graph(fake_bundle(llm), retrieve, _no_detail)

    await graph.ainvoke(state())

    assert retrieve.plans[1].firm.facts == {}
    assert retrieve.plans[1].firm.max_price == Decimal("20")


async def test_retry_drops_soft_preferences_and_adds_the_message() -> None:
    one = [candidate("a")]
    weak = Selection(intro="Hm.", sections=[], too_few=True)
    planned = plan(soft_preferences=["blue"])
    llm = FakeStructuredLLM([_router(Intent.PRODUCT_SEARCH), planned, weak, weak])
    retrieve = FakeRetrieve([one, one])
    graph = build_graph(fake_bundle(llm), retrieve, _no_detail)

    await graph.ainvoke(state(message="going sailing"))

    assert retrieve.plans[1].soft_preferences == []
    assert "going sailing" in retrieve.plans[1].search_phrases


async def test_no_rows_ends_with_clarifying_question() -> None:
    llm = FakeStructuredLLM([_router(Intent.PRODUCT_SEARCH), plan()])
    retrieve = FakeRetrieve([[], []])
    graph = build_graph(fake_bundle(llm), retrieve, _no_detail)

    result = await graph.ainvoke(state())

    assert result["answer"] == NO_MATCH_REPLY and len(retrieve.plans) == 2


async def test_vague_request_asks_a_question_without_searching() -> None:
    planned = plan(search_phrases=[], clarifying_question="For whom?")
    llm = FakeStructuredLLM([_router(Intent.PRODUCT_SEARCH), planned])
    retrieve = FakeRetrieve()
    graph = build_graph(fake_bundle(llm), retrieve, _no_detail)

    result = await graph.ainvoke(state())

    assert result["answer"] == "For whom?" and retrieve.plans == []


async def test_detail_answer_uses_only_retrieved_chunks() -> None:
    focus = uuid4()
    history = [Turn(role="assistant", text="this one", product_ids=[focus])]
    llm = FakeStructuredLLM(
        [_router(Intent.PRODUCT_DETAIL, focus), DetailAnswer(text="Apply at night.", found=True)]
    )
    graph = build_graph(fake_bundle(llm), FakeRetrieve(), FakeDetail(["Use: apply at night."]))

    result = await graph.ainvoke(state(message="how to use?", history=history))

    assert result["answer"] == "Apply at night."
    assert "Use: apply at night." in llm.calls[1].user


async def test_detail_with_no_information_says_so_without_guessing() -> None:
    focus = uuid4()
    history = [Turn(role="assistant", text="this one", product_ids=[focus])]
    llm = FakeStructuredLLM([_router(Intent.PRODUCT_DETAIL, focus)])
    graph = build_graph(fake_bundle(llm), FakeRetrieve(), FakeDetail([]))

    result = await graph.ainvoke(state(message="is it vegan?", history=history))

    assert result["answer"] == UNKNOWN_DETAIL_REPLY and len(llm.calls) == 1
