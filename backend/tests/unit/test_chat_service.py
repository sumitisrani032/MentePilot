from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from shopchat.agents.answers import NO_MATCH_REPLY
from shopchat.agents.state import Pick, Section, ValidatedSelection
from shopchat.chat.service import (
    PREPARING_REPLY,
    TRY_AGAIN_REPLY,
    ChatRequest,
    ChatService,
    DoneEvent,
    ErrorEvent,
    SectionsEvent,
    TokenEvent,
)
from shopchat.chat.session_store import SessionStore
from shopchat.search.cards import ProductCard
from tests.agent_helpers import profile
from tests.unit.test_session_store import FakeRedis


@dataclass
class FakeGraph:
    result: dict[str, Any] = field(default_factory=dict)
    error: Exception | None = None
    calls: int = 0

    async def ainvoke(self, state: Any) -> dict[str, Any]:
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


def _card(product_id: UUID) -> ProductCard:
    return ProductCard(
        id=product_id,
        title="Linen Shirt",
        price=Decimal("20"),
        compare_at_price=None,
        currency="USD",
        image_url=None,
        url="https://x/products/a",
    )


_PROFILE = profile()


def _service(graph: FakeGraph, loaded: Any = _PROFILE, cards: bool = True):
    usage: list[tuple[UUID, str, int]] = []

    async def load_profile(_: UUID):
        return loaded

    async def load_cards(_: UUID, ids: Sequence[UUID], __: str):
        return [_card(i) for i in ids] if cards else []

    async def record(shop: UUID, kind: str, quantity: int) -> None:
        usage.append((shop, kind, quantity))

    service = ChatService(
        graph=graph,  # type: ignore[arg-type]
        sessions=SessionStore(FakeRedis()),
        load_profile=load_profile,
        load_cards=load_cards,
        record_usage=record,
    )
    return service, usage


def _request() -> ChatRequest:
    return ChatRequest(shop_id=uuid4(), shop_domain="x", session_id="s", message="beach")


async def _collect(service: ChatService, request: ChatRequest | None = None) -> list[Any]:
    return [event async for event in service.handle(request or _request())]


def _text(events: list[Any]) -> str:
    return "".join(e.text for e in events if isinstance(e, TokenEvent))


def _picked() -> dict[str, Any]:
    pick = Pick(product_id=uuid4(), reason="fits the beach")
    section = Section(heading="Sun care", detail="For the beach.", picks=[pick], tips=["Reapply"])
    return {"validated": ValidatedSelection(intro="Pack these two.", sections=[section])}


async def test_events_order_tokens_then_products_then_done() -> None:
    events = await _collect(_service(FakeGraph(_picked()))[0])

    kinds = [type(e) for e in events]
    assert kinds == [TokenEvent] * 3 + [SectionsEvent, DoneEvent]
    assert _text(events) == "Pack these two."


async def test_cards_carry_the_reason() -> None:
    events = await _collect(_service(FakeGraph(_picked()))[0])
    sections = next(e for e in events if isinstance(e, SectionsEvent)).sections
    assert sections[0].cards[0].reason == "fits the beach"


async def test_reply_offers_follow_up_and_standard_quick_replies() -> None:
    picked = _picked()
    picked["validated"].follow_up_question = "Want a sleeping mask?"
    picked["validated"].quick_replies = ["Find a matching moisturizer"]

    events = await _collect(_service(FakeGraph(picked))[0])

    reply = next(e for e in events if isinstance(e, SectionsEvent))
    assert reply.follow_up_question == "Want a sleeping mask?"
    assert reply.quick_replies == [
        "Find a matching moisturizer",
        "Show more options",
        "Show cheaper options",
    ]


async def test_sections_keep_heading_detail_and_tips() -> None:
    events = await _collect(_service(FakeGraph(_picked()))[0])
    section = next(e for e in events if isinstance(e, SectionsEvent)).sections[0]
    assert (section.heading, section.detail, section.tips) == (
        "Sun care",
        "For the beach.",
        ["Reapply"],
    )


async def test_missing_profile_gets_preparing_message() -> None:
    graph = FakeGraph()
    events = await _collect(_service(graph, loaded=None)[0])
    assert _text(events) == PREPARING_REPLY and graph.calls == 0


async def test_empty_catalog_gets_preparing_message() -> None:
    graph = FakeGraph()
    events = await _collect(_service(graph, loaded=profile(product_count=0))[0])
    assert _text(events) == PREPARING_REPLY and graph.calls == 0


async def test_store_without_categories_is_served() -> None:
    graph = FakeGraph({"answer": "Hi."})
    await _collect(_service(graph, loaded=profile(categories=[]))[0])
    assert graph.calls == 1


async def test_failure_before_retrieval_shows_try_again() -> None:
    events = await _collect(_service(FakeGraph(error=RuntimeError("down")))[0])
    assert events == [ErrorEvent(message=TRY_AGAIN_REPLY)]


async def test_all_products_gone_at_card_time_says_no_match() -> None:
    events = await _collect(_service(FakeGraph(_picked()), cards=False)[0])
    assert _text(events) == NO_MATCH_REPLY
    assert not any(isinstance(e, SectionsEvent) for e in events)


async def test_usage_is_recorded_and_nothing_is_blocked() -> None:
    service, usage = _service(FakeGraph({"answer": "Hi."}))
    request = _request()

    await _collect(service, request)

    assert usage == [(request.shop_id, "chat", 1)]


async def test_conversation_is_remembered_with_shown_products() -> None:
    service, _ = _service(FakeGraph(_picked()))
    request = _request()

    await _collect(service, request)

    turns = await service.sessions.load(request.shop_id, request.session_id)
    assert [t.role for t in turns] == ["customer", "assistant"]
    assert len(turns[1].product_ids) == 1
