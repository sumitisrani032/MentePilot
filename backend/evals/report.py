"""Write a 52-question run as a readable document: what was asked and what came back."""

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import mean

from evals.scoring import CaseScore


@dataclass(frozen=True)
class SectionResult:
    heading: str
    products: list[tuple[str, str, str]]  # title, product type, reason


@dataclass(frozen=True)
class CaseResult:
    query: str
    score: CaseScore
    relevant_in_catalog: int
    intent: str
    firm: dict[str, bool | float | str]
    search_phrases: list[str]
    reply: str
    sections: list[SectionResult]
    follow_up: str | None


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _summary(results: Sequence[CaseResult]) -> list[str]:
    scores = [result.score for result in results]
    return [
        "| Measure | Result |",
        "| --- | --- |",
        f"| Questions | {len(results)} |",
        f"| Relevant in the top 5 | {mean(s.relevant_in_top5 for s in scores):.0%} |",
        f"| Fact violations | {sum(s.fact_violations for s in scores)} |",
        f"| Invented products | {sum(s.invented_products for s in scores)} |",
        f"| Replies containing a price | {sum(s.money_in_reply for s in scores)} |",
    ]


def _overview(results: Sequence[CaseResult]) -> list[str]:
    rows = [
        f"| {number} | {_cell(result.query)} | {result.score.relevant_in_top5:.2f} "
        f"| {result.score.fact_violations} | {result.relevant_in_catalog} |"
        for number, result in enumerate(results, 1)
    ]
    return ["| # | Customer message | Score | Violations | Relevant in catalog |",
            "| --- | --- | --- | --- | --- |", *rows]  # fmt: skip


def _facts(firm: dict[str, bool | float | str]) -> str:
    return ", ".join(f"`{key}` = {value}" for key, value in firm.items()) or "none"


def _case(number: int, result: CaseResult) -> list[str]:
    lines = [
        f"### {number}. {result.query}",
        "",
        f"Score {result.score.relevant_in_top5:.2f}, "
        f"{result.score.fact_violations} violations, "
        f"{result.relevant_in_catalog} relevant products in the catalog.",
        "",
        f"- **Intent:** {result.intent}",
        f"- **Strict filters:** {_facts(result.firm)}",
        f"- **Search phrases:** {', '.join(result.search_phrases) or 'none'}",
        f"- **Reply:** {result.reply}",
        "",
    ]
    if not result.sections:
        return [*lines, "No products were recommended.", ""]
    for section in result.sections:
        lines.append(f"**{section.heading}**")
        lines.append("")
        lines += [f"- **{title}** ({kind}): {why}" for title, kind, why in section.products]
        lines.append("")
    if result.follow_up:
        lines += [f"Follow-up question: {result.follow_up}", ""]
    return lines


def render_report(results: Sequence[CaseResult], shop: str, model: str) -> str:
    parts = [
        "# 52-question evaluation results",
        "",
        f"Store: `{shop}`. Model: `{model}`. A product counts as relevant when the merchant's "
        "own catalog attributes match the case in `backend/evals/dataset.yaml`.",
        "",
        *_summary(results),
        "",
        "## Overview",
        "",
        *_overview(results),
        "",
        "## Every question and answer",
        "",
    ]
    for number, result in enumerate(results, 1):
        parts += _case(number, result)
    return "\n".join(parts).rstrip() + "\n"
