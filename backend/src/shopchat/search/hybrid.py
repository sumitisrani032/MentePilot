"""Hybrid retrieval: vector and keyword search merged by reciprocal rank fusion."""

import re
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, Select, and_, cast, func, or_, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from shopchat.catalog.profile import CatalogProfile
from shopchat.catalog.types import Fact, Provenance
from shopchat.db.models import Product, ProductChunk
from shopchat.db.session import session_for_shop
from shopchat.llm.ports import Embedder
from shopchat.search.filters import effective_requirements
from shopchat.search.types import Candidate, Requirements, SearchPlan

_RESULTS_PER_SEARCH = 50
_WORD = re.compile(r"[^\W_]+")
_CAUTION_KINDS = ("%caution%", "%warning%")
_USAGE_KINDS = ("%how-to-use%", "%usage%", "%direction%", "%instruction%", "%care%", "%tips%")


def rrf(rankings: Sequence[Sequence[UUID]], k: int = 60) -> list[tuple[UUID, float]]:
    scores: dict[UUID, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1 / (k + rank)
    return sorted(scores.items(), key=lambda entry: entry[1], reverse=True)


def _fact_condition(key: str, value: bool | float | str) -> ColumnElement[bool]:
    stored = Product.facts[key]["value"]
    stated = Product.facts[key]["provenance"].astext == Provenance.STATED.value
    if isinstance(value, bool | str):
        # JSONB containment also matches a scalar inside a stored list.
        return and_(stated, stored.op("@>")(cast(value, JSONB)))
    # A numeric requirement is a minimum.
    return and_(
        stated,
        func.jsonb_typeof(stored) == "number",
        stored >= cast(value, JSONB),
    )


def _conditions(shop_id: UUID, firm: Requirements) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = [
        Product.shop_id == shop_id,
        Product.status == "active",
    ]
    if firm.in_stock:
        conditions.append(Product.available.is_(True))
    if firm.min_price is not None:
        conditions.append(Product.max_price >= firm.min_price)
    if firm.max_price is not None:
        conditions.append(Product.min_price <= firm.max_price)
    conditions.extend(_fact_condition(key, value) for key, value in firm.facts.items())
    return conditions


def _chunk_query(conditions: Sequence[ColumnElement[bool]]) -> Select[UUID, str]:
    return (
        select(ProductChunk.product_id, ProductChunk.text)
        .join(Product, Product.id == ProductChunk.product_id)
        .where(*conditions)
    )


def _keyword_query(phrase: str) -> ColumnElement[Any] | None:
    words = _WORD.findall(phrase)
    if not words:
        return None
    return func.websearch_to_tsquery("english", " or ".join(words))


async def _rank(
    session: AsyncSession,
    statement: Select[UUID, str],
    best_chunks: dict[UUID, str],
) -> list[UUID]:
    """Reduce chunk hits to an ordered list of products, remembering each best chunk."""
    ranking: list[UUID] = []
    seen: set[UUID] = set()
    for product_id, chunk_text in await session.execute(statement):
        if product_id not in seen:
            seen.add(product_id)
            ranking.append(product_id)
            best_chunks.setdefault(product_id, chunk_text)
    return ranking


async def retrieve(
    shop_id: UUID,
    plan: SearchPlan,
    profile: CatalogProfile,
    embedder: Embedder,
    limit: int = 30,
) -> list[Candidate]:
    if not plan.search_phrases:
        return []
    firm, _ = effective_requirements(plan.firm, profile)
    conditions = _conditions(shop_id, firm)
    vectors = await embedder.embed(plan.search_phrases)

    rankings: list[list[UUID]] = []
    best_chunks: dict[UUID, str] = {}
    async with session_for_shop(shop_id) as session:
        await session.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))
        for phrase, vector in zip(plan.search_phrases, vectors, strict=True):
            vector_search = (
                _chunk_query(conditions)
                .order_by(ProductChunk.embedding.cosine_distance(vector))
                .limit(_RESULTS_PER_SEARCH)
            )
            rankings.append(await _rank(session, vector_search, best_chunks))
            query = _keyword_query(phrase)
            if query is not None:
                keyword_search = (
                    _chunk_query(conditions)
                    .where(ProductChunk.search_vector.op("@@")(query))
                    .order_by(func.ts_rank(ProductChunk.search_vector, query).desc())
                    .limit(_RESULTS_PER_SEARCH)
                )
                rankings.append(await _rank(session, keyword_search, best_chunks))

        ranked = rrf(rankings)[:limit]
        return await _candidates(session, ranked, best_chunks)


async def _candidates(
    session: AsyncSession,
    ranked: Sequence[tuple[UUID, float]],
    best_chunks: dict[UUID, str],
) -> list[Candidate]:
    ids = [product_id for product_id, _ in ranked]
    products = {
        product.id: product
        for product in (await session.execute(select(Product).where(Product.id.in_(ids)))).scalars()
    }
    cautions = await _chunks_of_kinds(session, ids, _CAUTION_KINDS)
    usage = await _chunks_of_kinds(session, ids, _USAGE_KINDS)
    return [
        Candidate(
            product_id=product_id,
            title=products[product_id].title,
            vendor=products[product_id].vendor,
            product_type=products[product_id].product_type,
            facts={k: Fact.model_validate(v) for k, v in products[product_id].facts.items()},
            best_chunk=best_chunks[product_id],
            score=score,
            min_price=products[product_id].min_price,
            cautions=cautions.get(product_id, []),
            usage=usage.get(product_id, []),
        )
        for product_id, score in ranked
    ]


async def _chunks_of_kinds(
    session: AsyncSession, ids: Sequence[UUID], kinds: Sequence[str]
) -> dict[UUID, list[str]]:
    statement = select(ProductChunk.product_id, ProductChunk.text).where(
        ProductChunk.product_id.in_(ids),
        or_(*(ProductChunk.kind.ilike(pattern) for pattern in kinds)),
    )
    result: dict[UUID, list[str]] = {}
    for product_id, chunk_text in await session.execute(statement):
        result.setdefault(product_id, []).append(chunk_text)
    return result


async def product_detail_chunks(
    shop_id: UUID, product_id: UUID, query: str, embedder: Embedder, limit: int = 4
) -> list[str]:
    [vector] = await embedder.embed([query])
    statement = (
        select(ProductChunk.text)
        .where(ProductChunk.shop_id == shop_id, ProductChunk.product_id == product_id)
        .order_by(ProductChunk.embedding.cosine_distance(vector))
        .limit(limit)
    )
    async with session_for_shop(shop_id) as session:
        return list((await session.execute(statement)).scalars())
