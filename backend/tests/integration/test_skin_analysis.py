from sqlalchemy import text

from shopchat.agents.skin import SKIN_CONSENT_TEXT, SkinObservations, analyze_skin
from shopchat.llm.ports import ImagePart
from tests.conftest import TwoShops
from tests.fakes import FakeChatService, FakeStructuredLLM
from tests.http_helpers import widget_headers

JPEG = b"\xff\xd8\xff" + b"0" * 32


async def _post(client, shops: TwoShops, consent: str | None):
    data = {"session_id": "s1", "message": "", "image_purpose": "skin"}
    if consent is not None:
        data["skin_consent"] = consent
    return await client.post(
        "/v1/chat",
        data=data,
        files={"image": ("face.jpg", JPEG, "image/jpeg")},
        headers=widget_headers(shops.a, shops.domain_a),
    )


async def test_no_consent_rejected_before_any_llm_call(client, two_shops, bundle) -> None:
    response = await _post(client, two_shops, None)
    assert response.status_code == 403 and bundle.structured.calls == []


async def test_disabled_store_rejected_before_any_llm_call(
    client, two_shops, bundle, owner_conn
) -> None:
    await owner_conn.execute(
        text("UPDATE shops SET features = '{\"skin_analysis\": false}' WHERE id = :id"),
        {"id": two_shops.a},
    )
    await owner_conn.commit()

    response = await _post(client, two_shops, "true")

    assert response.status_code == 403 and bundle.structured.calls == []


async def test_needs_feed_the_normal_search_path(
    client, two_shops, bundle, chat_service: FakeChatService
) -> None:
    bundle.structured.responses.append(SkinObservations(observations=["shine"], needs=["oil"]))

    await _post(client, two_shops, "true")

    assert "oil" in chat_service.requests[0].image_context


async def test_consent_applies_to_one_image_only(client, two_shops, bundle) -> None:
    bundle.structured.responses.append(SkinObservations(observations=["a"], needs=["b"]))
    first = await _post(client, two_shops, "true")

    second = await _post(client, two_shops, None)

    assert first.status_code == 200 and second.status_code == 403


async def test_no_visible_skin_asks_for_a_better_photo(
    client, two_shops, bundle, chat_service: FakeChatService
) -> None:
    bundle.structured.responses.append(SkinObservations(observations=[], needs=[]))

    await _post(client, two_shops, "true")

    assert chat_service.requests == []


async def test_prompt_forbids_diagnosis_identity_age_and_ethnicity() -> None:
    llm = FakeStructuredLLM([SkinObservations(observations=[], needs=[])])

    await analyze_skin(ImagePart(data=JPEG, media_type="image/jpeg"), llm)

    system = llm.calls[0].system
    for word in ("diagnose", "identify", "age", "ethnicity"):
        assert word in system


def test_consent_text_mentions_openai_and_no_storage() -> None:
    assert "OpenAI" in SKIN_CONSENT_TEXT and "not stored" in SKIN_CONSENT_TEXT
