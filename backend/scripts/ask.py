"""Ask the assistant a question from the terminal, without Shopify. Makes paid LLM calls."""

import argparse
import asyncio
import sys
from collections.abc import Sequence

from sqlalchemy import select

from shopchat.agents.graph import build_graph
from shopchat.agents.state import ChatState, ValidatedSelection
from shopchat.catalog.repository import load_profile
from shopchat.config import get_settings
from shopchat.db.models import Shop
from shopchat.db.session import system_session
from shopchat.llm.openai_adapters import build_openai_bundle
from shopchat.search.hybrid import product_detail_chunks, retrieve

_EXIT_STOPPED = 2


def _print_answer(outcome: dict[str, object]) -> None:
    answer = outcome.get("answer")
    validated = outcome.get("validated")
    if answer or not isinstance(validated, ValidatedSelection):
        print(answer)
        return
    candidates = outcome["candidates"]
    assert isinstance(candidates, list)
    titles = {candidate.product_id: candidate.title for candidate in candidates}
    print(validated.intro)
    for section in validated.sections:
        print(f"\n{section.heading}: {section.detail}")
        for pick in section.picks:
            print(f"  - {titles[pick.product_id]}: {pick.reason}")
    if validated.follow_up_question:
        print(f"\n{validated.follow_up_question}")


async def _ask(message: str, domain: str) -> int:
    settings = get_settings()
    if not settings.llm_calls_enabled:
        print("Refusing to run: LLM_CALLS_ENABLED is false.", file=sys.stderr)
        return _EXIT_STOPPED
    async with system_session() as session:
        found = await session.execute(select(Shop.id).where(Shop.domain == domain))
        shop_id = found.scalar_one_or_none()
    profile = await load_profile(shop_id) if shop_id else None
    if shop_id is None or profile is None:
        print(f"No indexed store named {domain}.", file=sys.stderr)
        return _EXIT_STOPPED
    graph = build_graph(build_openai_bundle(settings), retrieve, product_detail_chunks)
    state: ChatState = {
        "shop_id": shop_id,
        "message": message,
        "image_context": None,
        "history": [],
        "profile": profile,
        "retries": 0,
    }
    _print_answer(dict(await graph.ainvoke(state)))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("message")
    parser.add_argument("--shop-domain", default="cosmo-genie.myshopify.com")
    args = parser.parse_args(argv)
    return asyncio.run(_ask(args.message, args.shop_domain))


if __name__ == "__main__":
    raise SystemExit(main())
