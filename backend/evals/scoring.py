"""Score chatbot picks against what the merchant's own catalog data says."""

import re
from collections.abc import Mapping, Sequence
from decimal import Decimal

from pydantic import BaseModel, Field

from shopchat.catalog.types import NormalizedProduct
from shopchat.search.types import Candidate

_MONEY = re.compile(r"[$€£₹]\s?\d|\b\d+(?:\.\d{2})?\s?(?:usd|eur|gbp|inr|rupees|dollars)\b", re.I)
_TOP = 5


class Condition(BaseModel):
    types: list[str] = Field(default_factory=list)
    attributes: dict[str, list[str]] = Field(default_factory=dict)


class EvalCase(BaseModel):
    query: str
    relevant_if: list[Condition]
    forbid_if: list[Condition] = Field(default_factory=list)
    max_price: Decimal | None = None
    trap: bool = False


class CaseScore(BaseModel):
    relevant_in_top5: float
    fact_violations: int
    invented_products: int
    money_in_reply: bool


def _matches(product: NormalizedProduct, condition: Condition) -> bool:
    if condition.types and product.product_type not in condition.types:
        return False
    return all(
        any(needle.lower() in product.raw_attributes.get(label, "").lower() for needle in needles)
        for label, needles in condition.attributes.items()
    )


def _over_budget(product: NormalizedProduct, limit: Decimal | None) -> bool:
    return limit is not None and min(v.price for v in product.variants) > limit


def _violates(product: NormalizedProduct, case: EvalCase) -> bool:
    return _over_budget(product, case.max_price) or any(
        _matches(product, condition) for condition in case.forbid_if
    )


def _relevant(product: NormalizedProduct, case: EvalCase) -> bool:
    return not _violates(product, case) and any(
        _matches(product, condition) for condition in case.relevant_if
    )


def score_case(
    case: EvalCase,
    products: Sequence[Candidate],
    reply: str,
    catalog: Mapping[str, NormalizedProduct],
) -> CaseScore:
    known = [catalog[p.title] for p in products if p.title in catalog]
    top = known[:_TOP]
    return CaseScore(
        relevant_in_top5=sum(_relevant(p, case) for p in top) / len(top) if top else 0.0,
        fact_violations=sum(_violates(p, case) for p in known),
        invented_products=len(products) - len(known),
        money_in_reply=_MONEY.search(reply) is not None,
    )
