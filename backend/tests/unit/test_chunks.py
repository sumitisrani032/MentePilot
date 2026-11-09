from shopchat.catalog.chunks import build_chunks
from shopchat.catalog.indexer import content_hash
from shopchat.catalog.types import Fact, Provenance
from tests.factories import normalized


def _stated(value: object, caveat: str | None = None) -> Fact:
    return Fact(value=value, provenance=Provenance.STATED, caveat=caveat)  # type: ignore[arg-type]


def _summary(chunks) -> str:
    return next(chunk.text for chunk in chunks if chunk.kind == "summary")


def test_summary_chunk_has_title_and_stated_facts() -> None:
    text = _summary(build_chunks(normalized(title="Sea Lotion", facts={"fit": _stated("slim")})))
    assert "Sea Lotion" in text and "fit: slim" in text


def test_negated_fact_reads_in_plain_words() -> None:
    text = _summary(build_chunks(normalized(facts={"waterproof": _stated(False)})))
    assert "not waterproof" in text


def test_caveat_is_included() -> None:
    text = _summary(build_chunks(normalized(facts={"spf": _stated(20.0, "use sunscreen too")})))
    assert "use sunscreen too" in text


def test_inferred_fact_is_labelled() -> None:
    fact = Fact(value="beach", provenance=Provenance.INFERRED)
    assert "likely" in _summary(build_chunks(normalized(facts={"use": fact})))


def test_long_attributes_become_detail_chunks() -> None:
    chunks = build_chunks(normalized(title="Cream", raw={"How to use": "x" * 90}))
    detail = next(chunk for chunk in chunks if chunk.kind == "how-to-use")
    assert detail.text.startswith("Cream") and "x" * 90 in detail.text


def test_short_attributes_do_not_become_detail_chunks() -> None:
    assert [c.kind for c in build_chunks(normalized(raw={"Fit": "Slim"}))] == ["summary"]


def test_hash_ignores_facts_so_unchanged_products_skip_the_llm() -> None:
    assert content_hash(normalized()) == content_hash(normalized(facts={"a": _stated("b")}))


def test_hash_changes_when_price_changes() -> None:
    assert content_hash(normalized(price="1.00")) != content_hash(normalized(price="2.00"))
