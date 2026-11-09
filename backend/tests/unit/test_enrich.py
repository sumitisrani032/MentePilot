import asyncio

from shopchat.catalog.enrich import (
    InferredAttributes,
    InferredFact,
    enrich_missing,
    needs_enrichment,
)
from shopchat.catalog.types import Fact, Provenance
from tests.factories import normalized
from tests.fakes import FakeStructuredLLM


def _stated(value: object) -> Fact:
    return Fact(value=value, provenance=Provenance.STATED)  # type: ignore[arg-type]


RICH_FACTS = {"a": _stated("1"), "b": _stated("2"), "c": _stated("3")}


def test_rich_product_needs_no_enrichment() -> None:
    assert not needs_enrichment(normalized(facts=RICH_FACTS))


def test_few_facts_needs_enrichment() -> None:
    assert needs_enrichment(normalized(facts={"a": _stated("1")}))


def test_short_description_needs_enrichment() -> None:
    assert needs_enrichment(normalized(description="Short.", facts=RICH_FACTS))


async def test_inferred_never_overwrites_stated() -> None:
    llm = FakeStructuredLLM([InferredAttributes(facts=[InferredFact(key="fit", value="loose")])])

    [product] = await enrich_missing([normalized(facts={"fit": _stated("slim")})], llm)

    assert product.facts["fit"].value == "slim"
    assert product.facts["fit"].provenance is Provenance.STATED


async def test_new_facts_are_marked_inferred() -> None:
    llm = FakeStructuredLLM([InferredAttributes(facts=[InferredFact(key="use", value="beach")])])

    [product] = await enrich_missing([normalized()], llm)

    assert product.facts["use"].provenance is Provenance.INFERRED


async def test_rich_products_make_no_llm_call() -> None:
    llm = FakeStructuredLLM()

    await enrich_missing([normalized(facts=RICH_FACTS)], llm)

    assert llm.calls == []


async def test_enrichment_runs_at_most_8_at_once() -> None:
    class Tracking:
        active = 0
        peak = 0

        async def generate(self, system, user, schema, tier, images=()):
            Tracking.active += 1
            Tracking.peak = max(Tracking.peak, Tracking.active)
            await asyncio.sleep(0)
            Tracking.active -= 1
            return InferredAttributes(facts=[])

    await enrich_missing([normalized(str(i)) for i in range(30)], Tracking())

    assert 1 < Tracking.peak <= 8
