from decimal import Decimal
from uuid import uuid4

from evals.scoring import Condition, EvalCase, score_case

from shopchat.search.types import Candidate
from tests.factories import normalized

WATER = "Water and sweat resistance"
CATALOG = {
    "good": normalized("g", title="good", raw={WATER: "Waterproof & humidity-proof"}),
    "trap": normalized("t", title="trap", raw={WATER: "Not waterproof"}),
    "pricey": normalized("p", title="pricey", price="99.00", raw={WATER: "Sweat-resistant"}),
}
CASE = EvalCase(
    query="waterproof please",
    relevant_if=[Condition(attributes={WATER: ["waterproof & humidity"]})],
    forbid_if=[Condition(attributes={WATER: ["not waterproof"]})],
    max_price=Decimal("50"),
)


def _picks(*titles: str) -> list[Candidate]:
    return [
        Candidate(
            product_id=uuid4(),
            title=t,
            vendor="",
            product_type="",
            facts={},
            best_chunk="",
            score=0,
        )
        for t in titles
    ]


def test_top5_relevance() -> None:
    score = score_case(CASE, _picks("good", "good", "good", "good", "pricey"), "", CATALOG)
    assert score.relevant_in_top5 == 0.8


def test_only_the_top_5_count() -> None:
    picks = _picks("good", "good", "good", "good", "good", "pricey")
    assert score_case(CASE, picks, "", CATALOG).relevant_in_top5 == 1.0


def test_no_products_scores_zero() -> None:
    assert score_case(CASE, [], "", CATALOG).relevant_in_top5 == 0.0


def test_trap_violation_is_counted() -> None:
    assert score_case(CASE, _picks("trap"), "", CATALOG).fact_violations == 1


def test_over_budget_is_a_violation() -> None:
    assert score_case(CASE, _picks("pricey"), "", CATALOG).fact_violations == 1


def test_price_in_reply_is_flagged() -> None:
    assert score_case(CASE, _picks("good"), "only $12.99", CATALOG).money_in_reply is True


def test_clean_reply_is_not_flagged() -> None:
    assert score_case(CASE, _picks("good"), "a lovely pick", CATALOG).money_in_reply is False


def test_unknown_title_counts_as_invented_product() -> None:
    assert score_case(CASE, _picks("ghost"), "", CATALOG).invented_products == 1


def test_type_condition_matches() -> None:
    case = EvalCase(query="q", relevant_if=[Condition(types=["Test Type"])])
    assert score_case(case, _picks("good"), "", CATALOG).relevant_in_top5 == 1.0
