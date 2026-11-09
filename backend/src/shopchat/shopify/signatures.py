"""Verify that a request really came from Shopify."""

import base64
import hashlib
import hmac
from collections.abc import Mapping


def _digest(message: bytes, secret: str) -> bytes:
    return hmac.new(secret.encode(), message, hashlib.sha256).digest()


def verify_proxy_signature(query: Mapping[str, str], secret: str) -> bool:
    """App Proxy: sorted key=value pairs joined with no separator, hex digest."""
    signature = query.get("signature", "")
    pairs = sorted(f"{key}={value}" for key, value in query.items() if key != "signature")
    expected = _digest("".join(pairs).encode(), secret).hex()
    return hmac.compare_digest(expected, signature)


def verify_oauth_hmac(query: Mapping[str, str], secret: str) -> bool:
    """OAuth: sorted key=value pairs joined with ampersands, hex digest."""
    received = query.get("hmac", "")
    pairs = sorted(
        f"{key}={value}" for key, value in query.items() if key not in {"hmac", "signature"}
    )
    expected = _digest("&".join(pairs).encode(), secret).hex()
    return hmac.compare_digest(expected, received)


def verify_webhook_hmac(body: bytes, header: str, secret: str) -> bool:
    """Webhooks: base64 digest of the raw request body."""
    expected = base64.b64encode(_digest(body, secret)).decode()
    return hmac.compare_digest(expected, header)
