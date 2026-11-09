"""Helpers for building requests that look like they came from Shopify or the widget."""

import hashlib
import hmac
from uuid import UUID

from shopchat.api.deps import issue_widget_token

ORIGIN = "https://store.example.test"


def signed_proxy_query(params: dict[str, str], secret: str) -> dict[str, str]:
    message = "".join(sorted(f"{key}={value}" for key, value in params.items()))
    signature = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return {**params, "signature": signature}


def widget_headers(shop_id: UUID, domain: str, origin: str = ORIGIN) -> dict[str, str]:
    token = issue_widget_token(shop_id, domain, origin)
    return {"Authorization": f"Bearer {token}", "Origin": origin}
