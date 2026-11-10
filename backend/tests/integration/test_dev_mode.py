from collections.abc import Iterator

import pytest

from shopchat.api.app import app
from shopchat.config import Settings, get_settings
from tests.conftest import TwoShops

LOCAL_ORIGIN = "http://localhost:8000"


def _use_settings(**changes: object) -> None:
    settings: Settings = get_settings().model_copy(update=changes)
    app.dependency_overrides[get_settings] = lambda: settings


@pytest.fixture
def dev_mode(two_shops: TwoShops) -> Iterator[None]:
    _use_settings(dev_mode=True, dev_shop_domain=two_shops.domain_a)
    yield


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/dev"),
        ("GET", "/dev/widget/chat.js"),
        ("POST", f"/dev/session?origin={LOCAL_ORIGIN}"),
    ],
)
async def test_dev_routes_do_not_exist_when_dev_mode_is_off(
    client, two_shops: TwoShops, method: str, path: str
) -> None:
    _use_settings(dev_mode=False, dev_shop_domain=two_shops.domain_a)

    response = await client.request(method, path)

    assert response.status_code == 404


async def test_dev_page_hosts_a_maximizable_widget(client, dev_mode: None) -> None:
    response = await client.get("/dev")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'id="shopchat-root"' in response.text
    assert 'data-session-url="/dev/session"' in response.text
    assert "data-maximizable" in response.text


@pytest.mark.parametrize(
    ("name", "media_type"), [("chat.js", "text/javascript"), ("chat.css", "text/css")]
)
async def test_dev_page_loads_the_real_widget_files(
    client, dev_mode: None, name: str, media_type: str
) -> None:
    response = await client.get(f"/dev/widget/{name}")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(media_type)
    assert "shopchat" in response.text


async def test_other_files_are_not_served(client, dev_mode: None) -> None:
    response = await client.get("/dev/widget/..%2F..%2Fshopify.extension.toml")
    assert response.status_code == 404


async def test_dev_session_needs_no_shopify_signature(client, dev_mode: None) -> None:
    response = await client.post(f"/dev/session?origin={LOCAL_ORIGIN}")

    assert response.status_code == 200
    assert response.json()["token"]
    assert response.json()["api_base"] == "http://test"


async def test_dev_session_token_works_for_chat(client, dev_mode: None) -> None:
    session = (await client.post(f"/dev/session?origin={LOCAL_ORIGIN}")).json()
    headers = {"Authorization": f"Bearer {session['token']}", "Origin": LOCAL_ORIGIN}

    response = await client.post(
        "/v1/chat", data={"session_id": "s1", "message": "beach"}, headers=headers
    )

    assert response.status_code == 200


async def test_dev_session_needs_an_origin(client, dev_mode: None) -> None:
    response = await client.post("/dev/session?origin=not-a-url")
    assert response.status_code == 422


async def test_dev_session_explains_a_missing_store(client, two_shops: TwoShops) -> None:
    _use_settings(dev_mode=True, dev_shop_domain="missing.myshopify.com")

    response = await client.post(f"/dev/session?origin={LOCAL_ORIGIN}")

    assert response.status_code == 403
    assert "DEV_SHOP_DOMAIN" in response.json()["detail"]
