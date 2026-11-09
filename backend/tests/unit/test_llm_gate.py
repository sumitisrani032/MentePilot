import pytest
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, SecretStr

from shopchat.config import Settings
from shopchat.llm.openai_adapters import (
    LLM_TIMEOUT_SECONDS,
    LLMCallsDisabledError,
    _Gate,
    build_openai_bundle,
)
from shopchat.llm.ports import ModelTier


class Dummy(BaseModel):
    value: str


def _disabled_bundle():
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="x",
        database_owner_url="x",
        redis_url="x",
        app_url="x",
        llm_calls_enabled=False,
        openai_api_key=SecretStr("sk-present-but-must-not-be-used"),
    )
    return build_openai_bundle(settings)


async def test_structured_refuses_when_disabled() -> None:
    with pytest.raises(LLMCallsDisabledError):
        await _disabled_bundle().structured.generate(
            system="s", user="u", schema=Dummy, tier=ModelTier.FAST
        )


async def test_streamer_refuses_when_disabled() -> None:
    with pytest.raises(LLMCallsDisabledError):
        async for _ in _disabled_bundle().streamer.stream("s", "u", ModelTier.FAST):
            pass


async def test_embedder_refuses_when_disabled() -> None:
    with pytest.raises(LLMCallsDisabledError):
        await _disabled_bundle().embedder.embed(["x"])


async def test_speech_to_text_refuses_when_disabled() -> None:
    with pytest.raises(LLMCallsDisabledError):
        await _disabled_bundle().stt.transcribe(b"x", "audio/webm")


async def test_text_to_speech_refuses_when_disabled() -> None:
    with pytest.raises(LLMCallsDisabledError):
        await _disabled_bundle().tts.speak("x")


def _enabled_settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="x",
        database_owner_url="x",
        redis_url="x",
        app_url="x",
        llm_calls_enabled=True,
        openai_api_key=SecretStr("sk-test"),
        openai_model_fast="test-model",
    )


async def test_structured_output_uses_function_calling(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class Runnable:
        async def ainvoke(self, messages: object) -> Dummy:
            return Dummy(value="x")

    def fake(self: object, schema: object, **kwargs: object) -> Runnable:
        captured.update(kwargs)
        return Runnable()

    monkeypatch.setattr(ChatOpenAI, "with_structured_output", fake)

    await build_openai_bundle(_enabled_settings()).structured.generate(
        system="s", user="u", schema=Dummy, tier=ModelTier.FAST
    )

    assert captured["method"] == "function_calling"


def test_chat_model_has_a_short_timeout() -> None:
    model = _Gate(_enabled_settings()).chat_model(ModelTier.FAST)
    assert model.request_timeout == LLM_TIMEOUT_SECONDS and model.max_retries == 1
