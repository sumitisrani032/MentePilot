import base64
import hashlib
import hmac
import json
import os

from tests.conftest import TwoShops

SECRET = os.environ["SHOPIFY_API_SECRET"]


async def _send(
    client, shop: str, topic: str, payload: dict, signature: str | None = None, wid: str = "w1"
):
    body = json.dumps(payload).encode()
    digest = hmac.new(SECRET.encode(), body, hashlib.sha256).digest()
    return await client.post(
        "/webhooks/shopify",
        content=body,
        headers={
            "X-Shopify-Hmac-Sha256": signature or base64.b64encode(digest).decode(),
            "X-Shopify-Topic": topic,
            "X-Shopify-Shop-Domain": shop,
            "X-Shopify-Webhook-Id": wid,
        },
    )


async def test_bad_hmac_is_401_and_not_enqueued(client, two_shops: TwoShops, queue) -> None:
    response = await _send(client, two_shops.domain_a, "products/update", {}, signature="bad")
    assert response.status_code == 401 and queue.jobs == []


async def test_product_update_is_queued(client, two_shops: TwoShops, queue) -> None:
    gid = "gid://shopify/Product/1"

    await _send(client, two_shops.domain_a, "products/update", {"admin_graphql_api_id": gid})

    assert queue.jobs == [("upsert_product", str(two_shops.a), gid)]


async def test_webhook_id_prevents_duplicate_jobs(client, two_shops: TwoShops, queue) -> None:
    payload = {"admin_graphql_api_id": "gid://shopify/Product/1"}

    await _send(client, two_shops.domain_a, "products/update", payload, wid="same-id")

    assert queue.job_ids == ["same-id"]


async def test_product_delete_builds_the_global_id(client, two_shops: TwoShops, queue) -> None:
    await _send(client, two_shops.domain_a, "products/delete", {"id": 42})
    assert queue.jobs == [("delete_product", str(two_shops.a), "gid://shopify/Product/42")]


async def test_uninstall_is_queued(client, two_shops: TwoShops, queue) -> None:
    await _send(client, two_shops.domain_a, "app/uninstalled", {})
    assert queue.jobs == [("deactivate_shop", str(two_shops.a))]


async def test_shop_redact_is_queued(client, two_shops: TwoShops, queue) -> None:
    await _send(client, two_shops.domain_a, "shop/redact", {"shop_id": 1})
    assert queue.jobs == [("redact_shop", str(two_shops.a))]


async def test_customers_redact_and_data_request_return_200(
    client, two_shops: TwoShops, queue
) -> None:
    redact = await _send(client, two_shops.domain_a, "customers/redact", {})
    request = await _send(client, two_shops.domain_a, "customers/data_request", {})

    assert (redact.status_code, request.status_code) == (200, 200) and queue.jobs == []


async def test_unknown_shop_is_acknowledged(client, queue) -> None:
    response = await _send(client, "gone.myshopify.com", "products/delete", {"id": 1})
    assert response.status_code == 200 and queue.jobs == []
