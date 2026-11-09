from shopchat.catalog.facts import (
    ValueInterpretation,
    ValueInterpretations,
    negation_contradicts,
    parse_stated_facts,
)
from shopchat.catalog.types import Provenance
from tests.factories import normalized
from tests.fakes import FakeStructuredLLM


def _interp(attribute: str, value: str, key: str, fact: object, caveat: str | None = None):
    return ValueInterpretations(
        items=[
            ValueInterpretation(
                attribute=attribute,
                value_text=value,
                fact_key=key,
                fact_value=fact,  # type: ignore[arg-type]
                caveat=caveat,
            )
        ]
    )


def test_plain_negation_contradicts() -> None:
    assert negation_contradicts("Not waterproof", "waterproof")
    assert negation_contradicts("No parabens", "parabens")


def test_mid_value_negation_contradicts() -> None:
    assert negation_contradicts("Transfer-resistant (not waterproof)", "waterproof")


def test_hyphenated_value_matches_underscored_key() -> None:
    assert negation_contradicts("Not water-resistant, reapply often", "water_resistant")


def test_positive_value_does_not_contradict() -> None:
    assert not negation_contradicts("Waterproof", "waterproof")


def test_free_from_claim_does_not_contradict() -> None:
    assert not negation_contradicts("No parabens", "paraben_free")


def test_negative_named_key_does_not_contradict() -> None:
    assert not negation_contradicts("Non-comedogenic", "non_comedogenic")


async def test_negation_guard_overrides_llm_true() -> None:
    llm = FakeStructuredLLM([_interp("Water", "Not waterproof", "waterproof", True)])

    [product] = await parse_stated_facts([normalized(raw={"Water": "Not waterproof"})], llm)

    assert product.facts["waterproof"].value is False
    assert product.facts["waterproof"].provenance is Provenance.STATED


async def test_caveat_is_kept() -> None:
    value = "SPF 20 (still wear a dedicated sunscreen)"
    llm = FakeStructuredLLM([_interp("Sun", value, "spf", 20.0, "still wear sunscreen")])

    [product] = await parse_stated_facts([normalized(raw={"Sun": value})], llm)

    assert product.facts["spf"].value == 20.0
    assert product.facts["spf"].caveat == "still wear sunscreen"


async def test_identical_values_are_sent_once() -> None:
    products = [normalized("a", raw={"Fit": "Slim"}), normalized("b", raw={"Fit": "Slim"})]
    llm = FakeStructuredLLM([_interp("Fit", "Slim", "fit", "slim")])

    parsed = await parse_stated_facts(products, llm)

    assert llm.calls[0].user.count("Slim") == 1
    assert all(p.facts["fit"].value == "slim" for p in parsed)


async def test_long_free_text_is_not_a_fact() -> None:
    llm = FakeStructuredLLM()

    [product] = await parse_stated_facts([normalized(raw={"Story": "x" * 81})], llm)

    assert llm.calls == [] and product.facts == {}


async def test_true_never_overwrites_false_from_another_attribute() -> None:
    llm = FakeStructuredLLM(
        [
            ValueInterpretations(
                items=[
                    ValueInterpretation(
                        attribute="A", value_text="Not waterproof", fact_key="wp", fact_value=False
                    ),
                    ValueInterpretation(
                        attribute="B", value_text="Great", fact_key="wp", fact_value=True
                    ),
                ]
            )
        ]
    )

    [product] = await parse_stated_facts(
        [normalized(raw={"A": "Not waterproof", "B": "Great"})], llm
    )

    assert product.facts["wp"].value is False


async def test_merchant_text_is_delimited_as_untrusted() -> None:
    llm = FakeStructuredLLM([_interp("Fit", "Slim", "fit", "slim")])

    await parse_stated_facts([normalized(raw={"Fit": "Slim"})], llm)

    assert "<merchant_values>" in llm.calls[0].user


async def test_large_catalogs_are_sent_in_batches_a_model_can_finish() -> None:
    values = [f"Value {number}" for number in range(21)]
    products = [normalized(str(n), raw={"Fit": value}) for n, value in enumerate(values)]
    llm = FakeStructuredLLM([ValueInterpretations(items=[]), ValueInterpretations(items=[])])

    await parse_stated_facts(products, llm)

    assert len(llm.calls) == 2
