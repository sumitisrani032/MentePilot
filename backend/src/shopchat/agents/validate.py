"""Guarantee the bot can only present real products and never quotes a price."""

import re
from collections.abc import Sequence
from uuid import UUID

from shopchat.agents.state import Pick, Section, Selection, ValidatedSelection
from shopchat.search.types import Candidate

_MONEY = re.compile(
    r"[$€£₹]\s?\d[\d,]*(?:\.\d+)?"
    r"|\b(?:rs\.?|inr|usd|eur|gbp)\s?\d[\d,]*(?:\.\d+)?"
    r"|\b\d[\d,]*(?:\.\d+)?\s?(?:usd|eur|gbp|inr|rs\b|rupees|dollars|euros|pounds)\b",
    re.IGNORECASE,
)
_EXTRA_SPACES = re.compile(r"[ \t]{2,}")
_MAX_LINES = 6
_MAX_QUICK_REPLIES = 3
_MAX_LINE_CHARS = 300


def scrub_money(text: str) -> str:
    return _EXTRA_SPACES.sub(" ", _MONEY.sub("", text)).strip()


def _clean_lines(lines: Sequence[str]) -> list[str]:
    cleaned = (scrub_money(line) for line in lines)
    return [line[:_MAX_LINE_CHARS] for line in cleaned if line][:_MAX_LINES]


def _clean_section(
    section: Section, allowed: set[UUID], seen: set[UUID], max_picks: int
) -> Section | None:
    picks: list[Pick] = []
    for pick in section.picks:
        if pick.product_id in allowed and pick.product_id not in seen and len(picks) < max_picks:
            seen.add(pick.product_id)
            picks.append(Pick(product_id=pick.product_id, reason=scrub_money(pick.reason)))
    if not picks:
        return None
    return Section(
        heading=scrub_money(section.heading),
        detail=scrub_money(section.detail),
        picks=picks,
        how_to_use=_clean_lines(section.how_to_use),
        tips=_clean_lines(section.tips),
    )


def validate_selection(
    selection: Selection,
    candidates: Sequence[Candidate],
    max_picks_per_section: int = 5,
    max_sections: int = 4,
) -> ValidatedSelection:
    allowed = {candidate.product_id for candidate in candidates}
    seen: set[UUID] = set()
    cleaned = (
        _clean_section(section, allowed, seen, max_picks_per_section)
        for section in selection.sections
    )
    sections = [section for section in cleaned if section is not None][:max_sections]
    question = selection.clarifying_question
    follow_up = selection.follow_up_question
    return ValidatedSelection(
        intro=scrub_money(selection.intro),
        sections=sections,
        clarifying_question=scrub_money(question) if question else None,
        follow_up_question=scrub_money(follow_up) if follow_up else None,
        quick_replies=_clean_lines(selection.quick_replies)[:_MAX_QUICK_REPLIES],
    )
