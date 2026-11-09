from pathlib import Path

import pytest
from sqlalchemy import text

from shopchat.config import Settings, get_settings
from tests.conftest import TwoShops
from tests.http_helpers import widget_headers


def _audio(data: bytes = b"audio-bytes", content_type: str = "audio/webm") -> dict[str, tuple]:
    return {"audio": ("a.webm", data, content_type)}


@pytest.fixture
async def voice_on(client, two_shops: TwoShops, owner_conn):
    from shopchat.api.app import app

    settings = Settings(voice_enabled=True)
    app.dependency_overrides[get_settings] = lambda: settings
    await owner_conn.execute(
        text("UPDATE shops SET features = '{\"voice\": true}' WHERE id = :id"),
        {"id": two_shops.a},
    )
    await owner_conn.commit()


async def test_transcribe_refuses_when_voice_is_off(client, two_shops: TwoShops) -> None:
    response = await client.post(
        "/v1/voice/transcribe",
        files=_audio(),
        headers=widget_headers(two_shops.a, two_shops.domain_a),
    )
    assert response.status_code == 403


async def test_speak_refuses_when_voice_is_off(client, two_shops: TwoShops) -> None:
    response = await client.post(
        "/v1/voice/speak",
        data={"text": "hello"},
        headers=widget_headers(two_shops.a, two_shops.domain_a),
    )
    assert response.status_code == 403


async def test_transcribe_returns_text_when_on(client, two_shops: TwoShops, voice_on) -> None:
    response = await client.post(
        "/v1/voice/transcribe",
        files=_audio(),
        headers=widget_headers(two_shops.a, two_shops.domain_a),
    )
    assert response.status_code == 200 and response.json() == {"text": "hello"}


async def test_speak_returns_audio_when_on(client, two_shops: TwoShops, voice_on) -> None:
    response = await client.post(
        "/v1/voice/speak",
        data={"text": "hello"},
        headers=widget_headers(two_shops.a, two_shops.domain_a),
    )
    assert response.headers["content-type"] == "audio/mpeg" and response.content == b"mp3-bytes"


async def test_oversized_audio_is_rejected(client, two_shops: TwoShops, voice_on) -> None:
    response = await client.post(
        "/v1/voice/transcribe",
        files=_audio(b"0" * (10 * 1024 * 1024 + 1)),
        headers=widget_headers(two_shops.a, two_shops.domain_a),
    )
    assert response.status_code == 413


async def test_audio_is_not_stored(
    client, two_shops: TwoShops, voice_on, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)

    await client.post(
        "/v1/voice/transcribe",
        files=_audio(),
        headers=widget_headers(two_shops.a, two_shops.domain_a),
    )

    assert list(tmp_path.iterdir()) == []
