from shopchat.chat.suggestions import suggestions_for
from tests.agent_helpers import profile


def test_suggestions_come_from_the_stores_categories() -> None:
    questions = suggestions_for(profile(categories=["Apparel > Tops > Linen shirts"]))
    assert questions[0] == "Show me linen shirts"


def test_store_without_a_profile_gets_general_questions() -> None:
    assert 1 <= len(suggestions_for(None)) <= 10


def test_no_more_than_8_suggestions() -> None:
    categories = [f"A > Kind {i}" for i in range(60)]
    assert len(suggestions_for(profile(categories=categories))) == 8


def test_questions_written_for_the_store_come_first() -> None:
    questions = suggestions_for(profile(suggested_questions=["What suits a hot day?"]))
    assert questions[0] == "What suits a hot day?"
