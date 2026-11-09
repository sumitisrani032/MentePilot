from pathlib import Path

from sqlalchemy import text

from shopchat.agents.vision import (
    FACE_WITH_SKIN_FEATURE_REPLY,
    UNUSABLE_IMAGE_REPLY,
    ImageReading,
)
from tests.conftest import TwoShops
from tests.fakes import FakeChatService
from tests.http_helpers import widget_headers

JPEG = b"\xff\xd8\xff" + b"0" * 32


def _files(data: bytes = JPEG, content_type: str = "image/jpeg") -> dict[str, tuple]:
    return {"image": ("photo.jpg", data, content_type)}


def _reading(kind: str) -> ImageReading:
    return ImageReading(kind=kind, description="a blue scarf")  # type: ignore[arg-type]


async def _post(client, shops: TwoShops, files: dict[str, tuple], message: str = "like this"):
    return await client.post(
        "/v1/chat",
        data={"session_id": "s1", "message": message},
        files=files,
        headers=widget_headers(shops.a, shops.domain_a),
    )


async def test_photo_reading_reaches_the_chat(
    client, two_shops: TwoShops, bundle, chat_service: FakeChatService
) -> None:
    bundle.structured.responses.append(_reading("product"))

    await _post(client, two_shops, _files())

    assert "a blue scarf" in chat_service.requests[0].image_context


async def test_photo_without_a_message_is_accepted(
    client, two_shops: TwoShops, bundle, chat_service: FakeChatService
) -> None:
    bundle.structured.responses.append(_reading("product"))

    response = await _post(client, two_shops, _files(), message="")

    assert response.status_code == 200 and chat_service.requests[0].message


async def test_unusable_photo_asks_for_a_better_one(
    client, two_shops: TwoShops, bundle, chat_service: FakeChatService
) -> None:
    bundle.structured.responses.append(_reading("unusable"))

    response = await _post(client, two_shops, _files())

    assert UNUSABLE_IMAGE_REPLY in response.text and chat_service.requests == []


async def test_face_on_product_path_points_to_consent_flow(
    client, two_shops: TwoShops, bundle, chat_service: FakeChatService
) -> None:
    bundle.structured.responses.append(_reading("face"))

    response = await _post(client, two_shops, _files())

    assert FACE_WITH_SKIN_FEATURE_REPLY in response.text
    assert chat_service.requests == []


async def test_wrong_type_is_rejected(client, two_shops: TwoShops, bundle) -> None:
    response = await _post(client, two_shops, _files(b"GIF89a", "image/gif"))
    assert response.status_code == 415 and bundle.structured.calls == []


async def test_content_must_match_the_declared_type(client, two_shops: TwoShops, bundle) -> None:
    response = await _post(client, two_shops, _files(b"not-a-jpeg", "image/jpeg"))
    assert response.status_code == 415 and bundle.structured.calls == []


async def test_oversized_upload_is_rejected(client, two_shops: TwoShops, bundle) -> None:
    response = await _post(client, two_shops, _files(JPEG + b"0" * (5 * 1024 * 1024)))
    assert response.status_code == 413 and bundle.structured.calls == []


async def test_image_is_not_written_to_disk_or_redis(
    client, two_shops: TwoShops, bundle, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    bundle.structured.responses.append(_reading("product"))

    await _post(client, two_shops, _files())

    assert list(tmp_path.iterdir()) == []


async def test_image_disabled_for_shop_is_rejected(
    client, two_shops: TwoShops, bundle, owner_conn
) -> None:
    await owner_conn.execute(
        text("UPDATE shops SET features = '{\"image\": false}' WHERE id = :id"),
        {"id": two_shops.a},
    )
    await owner_conn.commit()

    response = await _post(client, two_shops, _files())

    assert response.status_code == 403 and bundle.structured.calls == []
