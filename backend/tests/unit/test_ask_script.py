from uuid import uuid4

import pytest
from scripts.ask import _EXIT_STOPPED, _print_answer, main

from shopchat.agents.state import Pick, Section, ValidatedSelection
from tests.agent_helpers import candidate


def test_refuses_to_run_while_paid_calls_are_off(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["hello"]) == _EXIT_STOPPED
    assert "LLM_CALLS_ENABLED" in capsys.readouterr().err


def test_prints_products_by_title(capsys: pytest.CaptureFixture[str]) -> None:
    product_id = uuid4()
    selection = ValidatedSelection(
        intro="Here you go.",
        sections=[
            Section(
                heading="Sunscreen",
                detail="For the beach.",
                picks=[Pick(product_id=product_id, reason="Stays on in water.")],
            )
        ],
    )

    _print_answer({"validated": selection, "candidates": [candidate("Sun Veil", product_id)]})

    output = capsys.readouterr().out
    assert "Sun Veil: Stays on in water." in output and "Sunscreen: For the beach." in output
