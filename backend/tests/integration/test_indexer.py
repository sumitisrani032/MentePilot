from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

from shopchat.catalog import import_csv
from shopchat.catalog.enrich import InferredAttributes
from shopchat.catalog.indexer import index_products, save_new_records
from shopchat.catalog.pipeline import run_catalog_pipeline
from shopchat.catalog.profile import ProfileNarrative
from shopchat.catalog.repository import load_profile
from shopchat.db.models import Product, ProductChunk
from shopchat.db.session import session_for_shop
from tests.conftest import TwoShops
from tests.factories import normalized
from tests.fakes import FakeEmbedder, FakeStructuredLLM, fake_bundle

MINI = Path(__file__).parent.parent / "fixtures" / "mini_catalog.csv"


async def test_unchanged_product_is_skipped(two_shops: TwoShops) -> None:
    await index_products(two_shops.a, [normalized()], FakeEmbedder())

    second = await index_products(two_shops.a, [normalized()], FakeEmbedder())

    assert (second.indexed, second.skipped) == (0, 1)


async def test_changed_product_is_reindexed(two_shops: TwoShops) -> None:
    await index_products(two_shops.a, [normalized(price="1.00")], FakeEmbedder())

    second = await index_products(two_shops.a, [normalized(price="2.00")], FakeEmbedder())

    assert second.indexed == 1


async def test_reindex_replaces_chunks(two_shops: TwoShops) -> None:
    await index_products(two_shops.a, [normalized(price="1.00")], FakeEmbedder())
    await index_products(two_shops.a, [normalized(price="2.00")], FakeEmbedder())

    async with session_for_shop(two_shops.a) as session:
        count = (await session.execute(select(func.count()).select_from(ProductChunk))).scalar_one()

    assert count == 1


async def test_same_product_id_is_separate_per_shop(two_shops: TwoShops) -> None:
    await index_products(two_shops.a, [normalized("same")], FakeEmbedder())
    await index_products(two_shops.b, [normalized("same")], FakeEmbedder())

    async with session_for_shop(two_shops.b) as session:
        count = (await session.execute(select(func.count()).select_from(Product))).scalar_one()

    assert count == 1


async def test_unchanged_products_make_no_llm_calls(two_shops: TwoShops) -> None:
    first_llm = FakeStructuredLLM(
        [
            InferredAttributes(facts=[]),
            ProfileNarrative(summary="s", vocabulary=[], has_skincare=False),
        ]
    )
    await run_catalog_pipeline(two_shops.a, [normalized()], fake_bundle(first_llm))
    second_llm = FakeStructuredLLM()

    result = await run_catalog_pipeline(two_shops.a, [normalized()], fake_bundle(second_llm))

    assert second_llm.calls == [] and result.skipped == 1


def test_cli_refuses_when_llm_calls_disabled() -> None:
    code = import_csv.main(
        ["--shop-domain", "x.myshopify.com", "--csv", str(MINI), "--currency", "USD"]
    )
    assert code == 2


class _AnswerAnything:
    async def generate(self, system, user, schema, tier, images=()):
        if schema is InferredAttributes:
            return InferredAttributes(facts=[])
        return ProfileNarrative(summary="s", vocabulary=[], has_skincare=False)


async def test_completed_batches_survive_a_later_failure(two_shops: TwoShops) -> None:
    class FailsOnSecondBatch(FakeEmbedder):
        async def embed(self, texts):
            if self.calls:
                raise RuntimeError("provider down")
            return await super().embed(texts)

    bundle = fake_bundle(_AnswerAnything(), embedder=FailsOnSecondBatch())
    products = [normalized(str(i)) for i in range(150)]

    with pytest.raises(RuntimeError):
        await run_catalog_pipeline(two_shops.a, products, bundle)

    async with session_for_shop(two_shops.a) as session:
        products_saved = (
            await session.execute(select(func.count()).select_from(Product))
        ).scalar_one()
        indexed = (
            await session.execute(select(func.count()).select_from(ProductChunk))
        ).scalar_one()
    assert products_saved == 150 and indexed == 100


async def test_records_are_saved_when_the_llm_fails(two_shops: TwoShops) -> None:
    llm = FakeStructuredLLM(fail_with=RuntimeError("no credits"))
    product = normalized(raw={"Fit": "Slim"})

    with pytest.raises(RuntimeError):
        await run_catalog_pipeline(two_shops.a, [product], fake_bundle(llm))

    async with session_for_shop(two_shops.a) as session:
        saved = (await session.execute(select(Product.title))).scalars().all()
        chunks = (
            await session.execute(select(func.count()).select_from(ProductChunk))
        ).scalar_one()
    assert saved == ["Test Product"] and chunks == 0


async def test_indexing_records_when_it_happened(two_shops: TwoShops) -> None:
    before = datetime.now(UTC)

    await index_products(two_shops.a, [normalized()], FakeEmbedder())

    async with session_for_shop(two_shops.a) as session:
        indexed_at = (await session.execute(select(Product.indexed_at))).scalar_one()
    assert indexed_at is not None and indexed_at >= before


async def test_saved_record_has_no_indexed_time(two_shops: TwoShops) -> None:
    await save_new_records(two_shops.a, [normalized()])

    async with session_for_shop(two_shops.a) as session:
        indexed_at = (await session.execute(select(Product.indexed_at))).scalar_one()
    assert indexed_at is None


async def test_saved_record_is_still_indexed_on_the_next_run(two_shops: TwoShops) -> None:
    await save_new_records(two_shops.a, [normalized()])

    result = await index_products(two_shops.a, [normalized()], FakeEmbedder())

    assert result.indexed == 1


async def test_failed_update_keeps_an_existing_product_searchable(two_shops: TwoShops) -> None:
    await index_products(two_shops.a, [normalized(price="1.00")], FakeEmbedder())

    await save_new_records(two_shops.a, [normalized(price="2.00")])

    async with session_for_shop(two_shops.a) as session:
        chunks = (
            await session.execute(select(func.count()).select_from(ProductChunk))
        ).scalar_one()
    assert chunks == 1


async def test_profile_is_built_when_a_store_has_none(two_shops: TwoShops) -> None:
    bundle = fake_bundle(_AnswerAnything())

    await run_catalog_pipeline(two_shops.a, [normalized()], bundle, refresh_profile=False)

    assert await load_profile(two_shops.a) is not None


async def test_older_data_cannot_overwrite_newer_data(two_shops: TwoShops) -> None:
    newer = datetime(2026, 10, 5, tzinfo=UTC)
    older = datetime(2026, 10, 1, tzinfo=UTC)
    await index_products(
        two_shops.a, [normalized(title="Newest", source_updated_at=newer)], FakeEmbedder()
    )

    await index_products(
        two_shops.a, [normalized(title="Older", source_updated_at=older)], FakeEmbedder()
    )

    async with session_for_shop(two_shops.a) as session:
        title = (await session.execute(select(Product.title))).scalar_one()
    assert title == "Newest"
