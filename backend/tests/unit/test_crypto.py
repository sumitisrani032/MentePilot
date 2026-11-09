from shopchat.shopify.crypto import decrypt_token, encrypt_token


def test_token_round_trips() -> None:
    assert decrypt_token(encrypt_token("shpat_abc")) == "shpat_abc"


def test_ciphertext_does_not_contain_the_token() -> None:
    assert b"shpat_abc" not in encrypt_token("shpat_abc")
