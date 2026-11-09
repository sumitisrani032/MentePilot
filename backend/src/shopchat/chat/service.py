"""Run one customer message through the agents and emit events for the client."""

import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError

from shopchat.agents.answers import NO_MATCH_REPLY
from shopchat.agents.graph import ChatGraph
from shopchat.agents.state import ChatState, Turn, ValidatedSelection, invalid_fields
from shopchat.catalog.profile import CatalogProfile
from shopchat.chat.session_store import SessionStore
from shopchat.search.cards import CardSection, ProductCard

logger = logging.getLogger(__name__)

PREPARING_REPLY = "This store's catalog is still being prepared. Please check back shortly."
TRY_AGAIN_REPLY = "Sorry, something went wrong on my side. Please try again in a moment."

_WORD_WITH_SPACE = re.compile(r"\S+\s*")
_STANDARD_QUICK_REPLIES = ("Show more options", "Show cheaper options")

LoadProfile = Callable[[UUID], Awaitable[CatalogProfile | None]]
LoadCards = Callable[[UUID, Sequence[UUID], str], Awaitable[list[ProductCard]]]
RecordUsage = Callable[[UUID, str, int], Awaitable[None]]


class ChatRequest(BaseModel):
    shop_id: UUID
    shop_domain: str
    session_id: str
    message: str
    image_context: str | None = None


class TokenEvent(BaseModel):
    text: str


class SectionsEvent(BaseModel):
    sections: list[CardSection]
    follow_up_question: str | None = None
    quick_replies: list[str] = Field(default_factory=list)


class DoneEvent(BaseModel):
    pass


class ErrorEvent(BaseModel):
    message: str


ChatEvent = TokenEvent | SectionsEvent | DoneEvent | ErrorEvent


@dataclass(frozen=True)
class _Outcome:
    text: str
    sections: list[CardSection]
    follow_up_question: str | None = None
    quick_replies: tuple[str, ...] = ()


def _tokens(text: str) -> list[TokenEvent]:
    return [TokenEvent(text=word) for word in _WORD_WITH_SPACE.findall(text)]


@dataclass(frozen=True)
class ChatService:
    graph: ChatGraph
    sessions: SessionStore
    load_profile: LoadProfile
    load_cards: LoadCards
    record_usage: RecordUsage

    async def handle(self, request: ChatRequest) -> AsyncIterator[ChatEvent]:
        try:
            profile = await self.load_profile(request.shop_id)
            if profile is None or profile.product_count == 0:
                for token in _tokens(PREPARING_REPLY):
                    yield token
                yield DoneEvent()
                return
            outcome = await self._run(request, profile)
        except ValidationError as error:
            logger.error("chat failed for shop %s at %s", request.shop_id, invalid_fields(error))
            yield ErrorEvent(message=TRY_AGAIN_REPLY)
            return
        except Exception as error:
            # Only the error type is logged: customer messages stay out of the logs.
            logger.error("chat failed for shop %s: %s", request.shop_id, type(error).__name__)
            yield ErrorEvent(message=TRY_AGAIN_REPLY)
            return

        for token in _tokens(outcome.text):
            yield token
        if outcome.sections:
            yield SectionsEvent(
                sections=outcome.sections,
                follow_up_question=outcome.follow_up_question,
                quick_replies=list(outcome.quick_replies),
            )
        yield DoneEvent()
        await self._remember(request, outcome)

    async def _run(self, request: ChatRequest, profile: CatalogProfile) -> _Outcome:
        history = await self.sessions.load(request.shop_id, request.session_id)
        state: ChatState = {
            "shop_id": request.shop_id,
            "message": request.message,
            "image_context": request.image_context,
            "history": history,
            "profile": profile,
            "retries": 0,
        }
        result = cast(dict[str, Any], await self.graph.ainvoke(state))
        answer = result.get("answer")
        if answer:
            return _Outcome(text=answer, sections=[])
        validated: ValidatedSelection = result["validated"]
        return await self._present(request, validated)

    async def _present(self, request: ChatRequest, validated: ValidatedSelection) -> _Outcome:
        ids = [pick.product_id for pick in validated.picks]
        cards = await self.load_cards(request.shop_id, ids, request.shop_domain)
        by_id = {card.id: card for card in cards}
        sections = [
            CardSection(
                heading=section.heading,
                detail=section.detail,
                cards=[
                    by_id[pick.product_id].model_copy(update={"reason": pick.reason})
                    for pick in section.picks
                    if pick.product_id in by_id
                ],
                how_to_use=section.how_to_use,
                tips=section.tips,
            )
            for section in validated.sections
        ]
        visible = [section for section in sections if section.cards]
        if not visible:
            return _Outcome(text=validated.clarifying_question or NO_MATCH_REPLY, sections=[])
        text = validated.intro
        if validated.clarifying_question:
            text = f"{text} {validated.clarifying_question}".strip()
        return _Outcome(
            text=text,
            sections=visible,
            follow_up_question=validated.follow_up_question,
            quick_replies=tuple(
                dict.fromkeys([*validated.quick_replies, *_STANDARD_QUICK_REPLIES])
            ),
        )

    async def _remember(self, request: ChatRequest, outcome: _Outcome) -> None:
        """Bookkeeping must never turn a delivered reply into an error."""
        try:
            user_turn = Turn(role="customer", text=request.message)
            await self.sessions.append(request.shop_id, request.session_id, user_turn)
            await self.sessions.append(
                request.shop_id,
                request.session_id,
                Turn(
                    role="assistant",
                    text=outcome.text,
                    product_ids=[c.id for section in outcome.sections for c in section.cards],
                ),
            )
            await self.record_usage(request.shop_id, "chat", 1)
        except Exception as error:
            logger.error("post-chat bookkeeping failed: %s", type(error).__name__)
