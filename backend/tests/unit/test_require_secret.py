import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from shopchat.api.deps import require_secret


@pytest.mark.parametrize("value", [None, SecretStr("")])
def test_missing_or_blank_secret_is_refused(value: SecretStr | None) -> None:
    with pytest.raises(HTTPException) as error:
        require_secret(value, "X")
    assert error.value.status_code == 503


def test_real_secret_is_returned() -> None:
    assert require_secret(SecretStr("abc"), "X") == "abc"
