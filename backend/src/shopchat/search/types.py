"""The search plan produced by the agents and the candidates retrieval returns."""

from decimal import Decimal, InvalidOperation
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from shopchat.catalog.types import Fact


def _decimal_or_none(value: object) -> object:
    """Models sometimes send words like "under 20". An unusable limit is dropped."""
    try:
        return None if value is None else Decimal(str(value))
    except InvalidOperation:
        return None


class Requirements(BaseModel):
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    facts: dict[str, bool | float | str] = Field(default_factory=dict)
    in_stock: bool = True

    _prices = field_validator("min_price", "max_price", mode="before")(_decimal_or_none)

    @field_validator("facts", mode="before")
    @classmethod
    def _keep_single_values(cls, value: object) -> object:
        if not isinstance(value, dict):
            return {}
        return {k: v for k, v in value.items() if isinstance(v, bool | int | float | str)}

    @field_validator("in_stock", mode="before")
    @classmethod
    def _default_in_stock(cls, value: object) -> object:
        return True if value is None else value


def _as_list(value: object) -> object:
    if value is None:
        return []
    return [value] if isinstance(value, str) else value


class SearchPlan(BaseModel):
    firm: Requirements = Field(default_factory=Requirements)
    soft_preferences: list[str] = Field(default_factory=list)
    search_phrases: list[str]
    clarifying_question: str | None = None

    _lists = field_validator("soft_preferences", "search_phrases", mode="before")(_as_list)

    @field_validator("firm", mode="before")
    @classmethod
    def _default_firm(cls, value: object) -> object:
        return {} if value is None else value


class Candidate(BaseModel):
    product_id: UUID
    title: str
    vendor: str
    product_type: str
    facts: dict[str, Fact]
    best_chunk: str
    score: float
    min_price: Decimal = Decimal(0)
    cautions: list[str] = Field(default_factory=list)
    usage: list[str] = Field(default_factory=list)
