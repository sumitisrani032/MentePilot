from evals.report import CaseResult, SectionResult, render_report
from evals.scoring import CaseScore


def _result(**overrides: object) -> CaseResult:
    values: dict[str, object] = {
        "query": "waterproof mascara",
        "score": CaseScore(
            relevant_in_top5=0.8, fact_violations=1, invented_products=0, money_in_reply=False
        ),
        "relevant_in_catalog": 12,
        "intent": "product_search",
        "firm": {"waterproof": True},
        "search_phrases": ["waterproof mascara"],
        "reply": "Here are some picks.",
        "sections": [
            SectionResult(heading="Mascara", products=[("Lash Ink", "Mascara", "Holds in water")])
        ],
        "follow_up": "Do you prefer black or brown?",
    }
    values.update(overrides)
    return CaseResult(**values)  # type: ignore[arg-type]


def test_summary_averages_relevance_across_cases() -> None:
    low = CaseScore(
        relevant_in_top5=0.2, fact_violations=0, invented_products=0, money_in_reply=False
    )
    report = render_report([_result(), _result(score=low)], "cosmo.myshopify.com", "gpt-4o-mini")
    assert "| Relevant in the top 5 | 50% |" in report
    assert "| Fact violations | 1 |" in report


def test_each_case_shows_its_input_and_output() -> None:
    report = render_report([_result()], "cosmo.myshopify.com", "gpt-4o-mini")
    assert "waterproof mascara" in report
    assert "`waterproof` = True" in report
    assert "Here are some picks." in report
    assert "**Lash Ink** (Mascara): Holds in water" in report
    assert "Do you prefer black or brown?" in report


def test_a_reply_without_products_says_so() -> None:
    report = render_report(
        [_result(sections=[], reply="Sorry, nothing matched.")], "cosmo.myshopify.com", "m"
    )
    assert "Sorry, nothing matched." in report
    assert "No products were recommended." in report


def test_table_cells_cannot_break_on_a_pipe() -> None:
    report = render_report([_result(query="a | b")], "cosmo.myshopify.com", "m")
    assert "a \\| b" in report
