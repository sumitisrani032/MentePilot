"""Score the whole agent pipeline on a real catalog. Makes paid LLM calls when allowed."""

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path
from statistics import mean
from uuid import UUID, uuid4

import yaml
from sqlalchemy import select

from evals.report import CaseResult, SectionResult, render_report
from evals.scoring import CaseScore, EvalCase, _relevant, score_case
from shopchat.agents.graph import ChatGraph, build_graph
from shopchat.agents.state import ChatState, ValidatedSelection
from shopchat.catalog.csv_source import read_csv
from shopchat.catalog.pipeline import run_catalog_pipeline
from shopchat.catalog.profile import CatalogProfile
from shopchat.catalog.repository import load_profile
from shopchat.catalog.types import NormalizedProduct
from shopchat.config import get_settings
from shopchat.db.models import Shop
from shopchat.db.session import system_session
from shopchat.llm.openai_adapters import build_openai_bundle
from shopchat.search.hybrid import product_detail_chunks, retrieve
from shopchat.search.types import Candidate, SearchPlan

_DATASET = Path(__file__).parent / "dataset.yaml"
_EXIT_LLM_DISABLED = 2
_TARGET_FULL = 0.80
_TARGET_SPARSE = 0.60
_CONCURRENT_CASES = 5


def _sparse(products: Sequence[NormalizedProduct]) -> list[NormalizedProduct]:
    """Simulate a store with only titles and descriptions."""
    return [p.model_copy(update={"raw_attributes": {}, "tags": []}) for p in products]


async def _eval_shop(domain: str) -> UUID:
    async with system_session() as session:
        found = await session.execute(select(Shop.id).where(Shop.domain == domain))
        existing = found.scalar_one_or_none()
        if existing is not None:
            return existing
        new_id = uuid4()
        session.add(Shop(id=new_id, domain=domain, status="active", features={}))
        return new_id


def _picked(state: dict[str, object]) -> tuple[list[Candidate], str]:
    validated = state.get("validated")
    answer = state.get("answer")
    if not isinstance(validated, ValidatedSelection) or answer:
        return [], str(answer or "")
    candidates = state["candidates"]
    assert isinstance(candidates, list)
    by_id = {candidate.product_id: candidate for candidate in candidates}
    lines = [line for section in validated.sections for line in section.how_to_use + section.tips]
    reasons = [pick.reason for pick in validated.picks]
    reply = " ".join([validated.intro, *reasons, *lines])
    return [by_id[pick.product_id] for pick in validated.picks], reply


def _sections(state: dict[str, object]) -> list[SectionResult]:
    validated = state.get("validated")
    if not isinstance(validated, ValidatedSelection) or state.get("answer"):
        return []
    candidates = state["candidates"]
    assert isinstance(candidates, list)
    by_id = {candidate.product_id: candidate for candidate in candidates}
    return [
        SectionResult(
            heading=section.heading,
            products=[
                (by_id[p.product_id].title, by_id[p.product_id].product_type or "", p.reason)
                for p in section.picks
            ],
        )
        for section in validated.sections
    ]


async def _run_case(
    graph: ChatGraph,
    shop_id: UUID,
    profile: CatalogProfile,
    case: EvalCase,
    catalog: dict[str, NormalizedProduct],
) -> CaseResult:
    state: ChatState = {
        "shop_id": shop_id,
        "message": case.query,
        "image_context": None,
        "history": [],
        "profile": profile,
        "retries": 0,
    }
    outcome = dict(await graph.ainvoke(state))
    picks, reply = _picked(outcome)
    plan = outcome.get("plan")
    validated = outcome.get("validated")
    answer = outcome.get("answer")
    return CaseResult(
        query=case.query,
        score=score_case(case, picks, reply, catalog),
        relevant_in_catalog=sum(_relevant(product, case) for product in catalog.values()),
        intent=str(getattr(outcome.get("intent"), "value", "")),
        firm=plan.firm.facts if isinstance(plan, SearchPlan) else {},
        search_phrases=plan.search_phrases if isinstance(plan, SearchPlan) else [],
        reply=str(answer) if answer else getattr(validated, "intro", ""),
        sections=_sections(outcome),
        follow_up=getattr(validated, "follow_up_question", None) if not answer else None,
    )


def _report(cases: Sequence[EvalCase], scores: Sequence[CaseScore], target: float) -> None:
    for case, score in zip(cases, scores, strict=True):
        print(f"{score.relevant_in_top5:4.2f}  v={score.fact_violations}  {case.query}")
    relevance = mean(score.relevant_in_top5 for score in scores)
    print(f"\nRelevant in top 5: {relevance:.0%} (target {target:.0%})")
    print(f"Fact violations:   {sum(s.fact_violations for s in scores)} (target 0)")
    print(f"Invented products: {sum(s.invented_products for s in scores)} (target 0)")
    print(f"Prices in replies: {sum(s.money_in_reply for s in scores)} (target 0)")


def _target(args: argparse.Namespace) -> float:
    return _TARGET_SPARSE if args.sparse else _TARGET_FULL


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    if not settings.llm_calls_enabled:
        print("Refusing to run: LLM_CALLS_ENABLED is false.", file=sys.stderr)
        return _EXIT_LLM_DISABLED

    bundle = build_openai_bundle(settings)
    full = read_csv(args.csv, args.currency)
    domain = args.shop_domain or (
        "eval-sparse.myshopify.com" if args.sparse else "eval-full.myshopify.com"
    )
    shop_id = await _eval_shop(domain)
    if not args.shop_domain:  # An existing store is already indexed, so it costs nothing extra.
        await run_catalog_pipeline(shop_id, _sparse(full) if args.sparse else full, bundle)
    profile = await load_profile(shop_id)
    assert profile is not None

    graph = build_graph(bundle, retrieve, product_detail_chunks)
    cases = [EvalCase.model_validate(item) for item in yaml.safe_load(_DATASET.read_text())]
    catalog = {product.title: product for product in full}
    limit = asyncio.Semaphore(_CONCURRENT_CASES)

    async def run_one(case: EvalCase) -> CaseResult:
        async with limit:
            return await _run_case(graph, shop_id, profile, case, catalog)

    results = await asyncio.gather(*(run_one(case) for case in cases))
    _report(cases, [result.score for result in results], _target(args))
    if args.report:
        args.report.write_text(
            render_report(results, args.shop_domain or domain, settings.openai_model_smart or "")
        )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--currency", default="USD")
    parser.add_argument("--sparse", action="store_true")
    parser.add_argument("--shop-domain", help="Score a store that is already indexed")
    parser.add_argument("--report", type=Path, help="Write every question and answer to a file")
    return asyncio.run(_run(parser.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
