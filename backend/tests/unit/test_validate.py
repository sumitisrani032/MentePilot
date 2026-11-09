from uuid import uuid4

from shopchat.agents.state import Pick, Section, Selection
from shopchat.agents.validate import scrub_money, validate_selection
from tests.agent_helpers import candidate, one_section


def _selection(*picks: Pick, intro: str = "Try these.") -> Selection:
    return Selection(intro=intro, sections=one_section(list(picks)))


def test_unknown_product_id_is_dropped() -> None:
    real = candidate()
    picks = [Pick(product_id=uuid4(), reason="x"), Pick(product_id=real.product_id, reason="y")]

    validated = validate_selection(_selection(*picks), [real])

    assert [pick.product_id for pick in validated.picks] == [real.product_id]


def test_duplicates_are_removed() -> None:
    real = candidate()
    picks = [Pick(product_id=real.product_id, reason="a")] * 2
    assert len(validate_selection(_selection(*picks), [real]).picks) == 1


def test_picks_are_capped_at_5() -> None:
    items = [candidate(str(i)) for i in range(8)]
    picks = [Pick(product_id=i.product_id, reason="r") for i in items]
    assert len(validate_selection(_selection(*picks), items).picks) == 5


def test_a_product_appears_in_only_one_section() -> None:
    real = candidate()
    pick = Pick(product_id=real.product_id, reason="x")
    selection = Selection(
        intro="Hi",
        sections=[Section(heading="A", picks=[pick]), Section(heading="B", picks=[pick])],
    )

    validated = validate_selection(selection, [real])

    assert [section.heading for section in validated.sections] == ["A"]


def test_section_with_no_valid_products_is_dropped() -> None:
    selection = Selection(
        intro="Hi", sections=[Section(heading="A", picks=[Pick(product_id=uuid4(), reason="x")])]
    )
    assert validate_selection(selection, [candidate()]).sections == []


def test_at_most_4_sections_are_kept() -> None:
    items = [candidate(str(i)) for i in range(6)]
    sections = [
        Section(heading=str(i), picks=[Pick(product_id=item.product_id, reason="r")])
        for i, item in enumerate(items)
    ]
    selection = Selection(intro="Hi", sections=sections)
    assert len(validate_selection(selection, items).sections) == 4


def test_money_is_scrubbed_from_tips_and_empty_lines_dropped() -> None:
    real = candidate()
    section = Section(
        heading="A",
        picks=[Pick(product_id=real.product_id, reason="r")],
        tips=["Best value at $5 today", "$9"],
    )

    validated = validate_selection(Selection(intro="Hi", sections=[section]), [real])

    assert validated.sections[0].tips == ["Best value at today"]


def test_money_is_removed_from_text() -> None:
    assert scrub_money("only $12.99 today") == "only today"


def test_rupee_amounts_are_removed() -> None:
    assert "499" not in scrub_money("yours for ₹499 or Rs. 499 or 499 rupees")


def test_plain_numbers_are_kept() -> None:
    assert scrub_money("SPF 50 lasts 12 hours") == "SPF 50 lasts 12 hours"


def test_prices_are_scrubbed_from_reasons_and_intro() -> None:
    real = candidate()
    selection = _selection(
        Pick(product_id=real.product_id, reason="Great at $5"), intro="Deals from $5 here"
    )

    validated = validate_selection(selection, [real])

    assert "$" not in validated.intro and "$" not in validated.picks[0].reason


def test_follow_up_and_quick_replies_are_cleaned_and_capped() -> None:
    real = candidate()
    selection = Selection(
        intro="Hi",
        sections=one_section([Pick(product_id=real.product_id, reason="r")]),
        follow_up_question="Want more under $5?",
        quick_replies=["a", "b", "c", "d"],
    )

    validated = validate_selection(selection, [real])

    assert "$" not in (validated.follow_up_question or "")
    assert validated.quick_replies == ["a", "b", "c"]
