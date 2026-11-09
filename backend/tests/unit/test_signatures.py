import base64
import hashlib
import hmac

from shopchat.shopify.signatures import (
    verify_oauth_hmac,
    verify_proxy_signature,
    verify_webhook_hmac,
)
from tests.http_helpers import signed_proxy_query

SECRET = "shh"


def test_valid_proxy_signature_is_accepted() -> None:
    assert verify_proxy_signature(signed_proxy_query({"shop": "a", "b": "2"}, SECRET), SECRET)


def test_tampered_proxy_signature_is_rejected() -> None:
    query = signed_proxy_query({"shop": "a.myshopify.com"}, SECRET)
    query["shop"] = "b.myshopify.com"
    assert not verify_proxy_signature(query, SECRET)


def test_missing_proxy_signature_is_rejected() -> None:
    assert not verify_proxy_signature({"shop": "a"}, SECRET)


def test_oauth_hmac_is_verified() -> None:
    message = "code=1&shop=a"
    digest = hmac.new(SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    assert verify_oauth_hmac({"shop": "a", "code": "1", "hmac": digest}, SECRET)


def test_oauth_hmac_with_wrong_digest_is_rejected() -> None:
    assert not verify_oauth_hmac({"shop": "a", "hmac": "00"}, SECRET)


def test_webhook_hmac_is_verified() -> None:
    body = b'{"id": 1}'
    header = base64.b64encode(hmac.new(SECRET.encode(), body, hashlib.sha256).digest()).decode()
    assert verify_webhook_hmac(body, header, SECRET)


def test_webhook_with_altered_body_is_rejected() -> None:
    header = base64.b64encode(hmac.new(SECRET.encode(), b"a", hashlib.sha256).digest()).decode()
    assert not verify_webhook_hmac(b"b", header, SECRET)
