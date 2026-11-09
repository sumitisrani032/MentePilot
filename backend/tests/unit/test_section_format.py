from uuid import uuid4

from shopchat.agents.state import Section, Selection


def _raw(**overrides: object) -> dict:
    pick = {"product_id": str(uuid4()), "reason": "fits"}
    return {"heading": "Sun", "detail": "For you", "picks": [pick], **overrides}


def test_null_lists_become_empty() -> None:
    section = Section.model_validate(_raw(how_to_use=None, tips=None))
    assert (section.how_to_use, section.tips) == ([], [])


def test_a_single_string_becomes_one_line() -> None:
    assert Section.model_validate(_raw(tips="Reapply often")).tips == ["Reapply often"]


def test_null_detail_becomes_empty() -> None:
    assert Section.model_validate(_raw(detail=None)).detail == ""


def test_missing_reason_is_allowed() -> None:
    section = Section.model_validate(_raw(picks=[{"product_id": str(uuid4())}]))
    assert section.picks[0].reason == ""


def test_malformed_product_id_drops_only_that_pick() -> None:
    good = {"product_id": str(uuid4()), "reason": "fits"}
    section = Section.model_validate(_raw(picks=[{"product_id": "Sea Lotion"}, good]))
    assert [str(pick.product_id) for pick in section.picks] == [good["product_id"]]


def test_whole_selection_parses_from_model_style_output() -> None:
    selection = Selection.model_validate(
        {"intro": "Hi", "sections": [_raw(how_to_use=None, tips="One tip")]}
    )
    assert len(selection.picks) == 1


def test_stray_items_in_sections_are_dropped() -> None:
    selection = Selection.model_validate({"intro": "Hi", "sections": [_raw(), "oops"]})
    assert len(selection.sections) == 1
