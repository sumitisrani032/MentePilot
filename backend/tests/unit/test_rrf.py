from uuid import uuid4

from shopchat.search.hybrid import rrf


def test_rrf_rewards_appearing_in_both_lists() -> None:
    both, only_first, only_second = uuid4(), uuid4(), uuid4()

    ranked = rrf([[only_first, both], [only_second, both]])

    assert ranked[0][0] == both


def test_rrf_uses_k_60() -> None:
    item = uuid4()
    assert rrf([[item]])[0][1] == 1 / 61


def test_rrf_with_no_rankings_is_empty() -> None:
    assert rrf([]) == []
