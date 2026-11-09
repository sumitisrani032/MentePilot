"""Development command: load a product CSV into a store's index."""

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select

from shopchat.catalog.csv_source import read_csv
from shopchat.catalog.pipeline import run_catalog_pipeline
from shopchat.config import get_settings
from shopchat.db.models import Shop
from shopchat.db.session import system_session
from shopchat.llm.openai_adapters import build_openai_bundle

_EXIT_LLM_DISABLED = 2


async def _shop_id(domain: str) -> UUID:
    async with system_session() as session:
        shop = (
            await session.execute(select(Shop).where(Shop.domain == domain))
        ).scalar_one_or_none()
        if shop is not None:
            return shop.id
        new_id = uuid4()
        session.add(Shop(id=new_id, domain=domain, status="active", features={"image": True}))
        return new_id


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    if not settings.llm_calls_enabled:
        print("Refusing to run: LLM_CALLS_ENABLED is false.", file=sys.stderr)
        return _EXIT_LLM_DISABLED
    products = read_csv(args.csv, args.currency)
    shop_id = await _shop_id(args.shop_domain)
    result = await run_catalog_pipeline(shop_id, products, build_openai_bundle(settings))
    print(f"Indexed {result.indexed}, skipped {result.skipped}.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shop-domain", required=True)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--currency", required=True)
    return asyncio.run(_run(parser.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
