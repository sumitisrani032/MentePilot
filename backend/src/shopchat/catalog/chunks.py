"""Turn a product into the text chunks that the RAG index stores."""

import re
from dataclasses import dataclass

from shopchat.catalog.facts import MAX_FACT_VALUE_CHARS
from shopchat.catalog.types import Fact, NormalizedProduct, Provenance

_NON_SLUG = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class ChunkDraft:
    kind: str
    text: str


def _describe(key: str, fact: Fact) -> str:
    label = key.replace("_", " ")
    if fact.value is True:
        text = label
    elif fact.value is False:
        text = f"not {label}"
    elif isinstance(fact.value, list):
        text = f"{label}: {', '.join(fact.value)}"
    else:
        text = f"{label}: {fact.value}"
    if fact.caveat:
        text = f"{text} ({fact.caveat})"
    return f"{text} (likely)" if fact.provenance is Provenance.INFERRED else text


def _summary(product: NormalizedProduct) -> str:
    lines = [
        product.title,
        f"Brand: {product.vendor}",
        f"Type: {product.product_type}",
        f"Category: {product.category}",
    ]
    if product.tags:
        lines.append(f"Tags: {', '.join(product.tags)}")
    if product.description:
        lines.append(product.description)
    if product.facts:
        facts = "; ".join(_describe(key, fact) for key, fact in sorted(product.facts.items()))
        lines.append(f"Details: {facts}")
    return "\n".join(lines)


def _slug(label: str) -> str:
    return _NON_SLUG.sub("-", label.lower()).strip("-")


def build_chunks(product: NormalizedProduct) -> list[ChunkDraft]:
    chunks = [ChunkDraft(kind="summary", text=_summary(product))]
    chunks.extend(
        ChunkDraft(kind=_slug(label), text=f"{product.title} - {label}: {value}")
        for label, value in sorted(product.raw_attributes.items())
        if len(value) > MAX_FACT_VALUE_CHARS
    )
    return chunks
