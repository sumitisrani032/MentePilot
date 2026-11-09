"""The one path every product takes into the index, from any source."""

from collections.abc import Sequence
from itertools import batched
from uuid import UUID

from shopchat.catalog.enrich import enrich_missing
from shopchat.catalog.facts import parse_stated_facts
from shopchat.catalog.indexer import (
    IndexResult,
    index_products,
    save_new_records,
    select_changed,
)
from shopchat.catalog.profile import build_profile
from shopchat.catalog.repository import load_products, load_profile, save_profile
from shopchat.catalog.types import NormalizedProduct
from shopchat.llm.ports import LLMBundle

_SAVE_EVERY = 100


async def run_catalog_pipeline(
    shop_id: UUID,
    products: Sequence[NormalizedProduct],
    bundle: LLMBundle,
    refresh_profile: bool = True,
) -> IndexResult:
    """Facts, enrichment, indexing, then the profile. Only changed products reach the LLM.

    Progress is saved in batches, so a retry after a failure resumes rather than repays.
    """
    changed = await select_changed(shop_id, products)
    await save_new_records(shop_id, changed)
    with_facts = await parse_stated_facts(changed, bundle.structured)
    indexed = 0
    for batch in batched(with_facts, _SAVE_EVERY):
        enriched = await enrich_missing(batch, bundle.structured)
        indexed += (await index_products(shop_id, enriched, bundle.embedder)).indexed

    if (refresh_profile and changed) or await load_profile(shop_id) is None:
        profile = await build_profile(await load_products(shop_id), bundle.structured)
        await save_profile(shop_id, profile)
    return IndexResult(indexed=indexed, skipped=len(products) - len(changed))
