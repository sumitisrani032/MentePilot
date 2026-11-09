"""The state passed between graph nodes."""

from collections.abc import Awaitable, Sequence
from enum import StrEnum
from typing import Any, Protocol, TypedDict
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError, field_validator

from shopchat.catalog.profile import CatalogProfile
from shopchat.search.types import Candidate, SearchPlan


class Intent(StrEnum):
    PRODUCT_SEARCH = "product_search"
    FOLLOW_UP = "follow_up"
    PRODUCT_DETAIL = "product_detail"
    SKIN_ANALYSIS = "skin_analysis"
    SMALL_TALK = "small_talk"
    OUT_OF_SCOPE = "out_of_scope"
    UNCLEAR = "unclear"
    NON_ENGLISH = "non_english"


class Turn(BaseModel):
    role: str
    text: str
    product_ids: list[UUID] = Field(default_factory=list)


def invalid_fields(error: ValidationError) -> list[str]:
    """Where a model's answer was malformed. Values are left out: they could echo customers."""
    return [f"{'.'.join(map(str, e['loc']))}:{e['type']}" for e in error.errors()]


def _text_or_empty(value: object) -> object:
    return "" if value is None else value


def _as_lines(value: object) -> object:
    """Models sometimes send null, or one string where a list was asked for."""
    if value is None:
        return []
    return [value] if isinstance(value, str) else value


def _is_uuid(value: object) -> bool:
    try:
        UUID(str(value))
    except ValueError:
        return False
    return True


class Pick(BaseModel):
    product_id: UUID
    reason: str = ""

    _reason = field_validator("reason", mode="before")(_text_or_empty)


class Section(BaseModel):
    """A themed group of products in a reply."""

    heading: str
    detail: str = ""
    picks: list[Pick]
    how_to_use: list[str] = Field(default_factory=list)
    tips: list[str] = Field(default_factory=list)

    _detail = field_validator("detail", mode="before")(_text_or_empty)
    _lines = field_validator("how_to_use", "tips", mode="before")(_as_lines)

    @field_validator("picks", mode="before")
    @classmethod
    def _drop_unusable_picks(cls, value: object) -> object:
        """One malformed product id must not cost the whole answer."""
        if not isinstance(value, list):
            return []
        return [
            item for item in value if not isinstance(item, dict) or _is_uuid(item.get("product_id"))
        ]


class Selection(BaseModel):
    intro: str
    sections: list[Section]
    clarifying_question: str | None = None
    follow_up_question: str | None = None
    quick_replies: list[str] = Field(default_factory=list)
    too_few: bool = False

    _quick_replies = field_validator("quick_replies", mode="before")(_as_lines)

    @field_validator("sections", mode="before")
    @classmethod
    def _keep_real_sections(cls, value: object) -> object:
        """Models occasionally add a stray item to the list, which must not cost the answer."""
        return (
            [item for item in value if isinstance(item, dict | Section)]
            if isinstance(value, list)
            else []
        )

    @property
    def picks(self) -> list[Pick]:
        return [pick for section in self.sections for pick in section.picks]


class ValidatedSelection(BaseModel):
    intro: str
    sections: list[Section]
    clarifying_question: str | None = None
    follow_up_question: str | None = None
    quick_replies: list[str] = Field(default_factory=list)

    @property
    def picks(self) -> list[Pick]:
        return [pick for section in self.sections for pick in section.picks]


class ChatState(TypedDict, total=False):
    shop_id: UUID
    message: str
    image_context: str | None
    history: list[Turn]
    profile: CatalogProfile
    intent: Intent
    focus_product_id: UUID | None
    plan: SearchPlan
    candidates: list[Candidate]
    selection: Selection
    validated: ValidatedSelection
    retries: int
    detail_chunks: list[str]
    answer: str | None


class Node(Protocol):
    def __call__(self, state: ChatState) -> Awaitable[dict[str, Any]]: ...


def history_text(history: Sequence[Turn]) -> str:
    lines = []
    for turn in history:
        shown = (
            f" [shown products: {', '.join(map(str, turn.product_ids))}]"
            if turn.product_ids
            else ""
        )
        lines.append(f"{turn.role}: {turn.text}{shown}")
    return "\n".join(lines)


def customer_block(state: ChatState) -> str:
    """Customer-controlled text, delimited so that models treat it as data."""
    block = f"<customer_message>\n{state['message']}\n</customer_message>"
    image_context = state.get("image_context")
    if image_context:
        block += f"\n<image_context>\n{image_context}\n</image_context>"
    return block
