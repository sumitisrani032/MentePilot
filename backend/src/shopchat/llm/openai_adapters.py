"""OpenAI implementations of the LLM ports.

Every public method calls ``_Gate.check`` before any client exists, so no
request can leave the process while ``LLM_CALLS_ENABLED`` is false.
"""

import base64
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any, cast

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from openai import AsyncOpenAI
from pydantic import BaseModel, SecretStr

from shopchat.config import Settings
from shopchat.llm.ports import ImagePart, LLMBundle, ModelTier

EMBEDDING_DIMENSIONS = 1536
_TTS_VOICE = "alloy"
LLM_TIMEOUT_SECONDS = 60
SPEECH_TIMEOUT_SECONDS = 60
LLM_MAX_RETRIES = 1


class LLMCallsDisabledError(RuntimeError):
    """Raised when code tries to reach OpenAI while LLM calls are switched off."""


@dataclass(frozen=True)
class _Gate:
    settings: Settings

    def check(self) -> None:
        if not self.settings.llm_calls_enabled:
            raise LLMCallsDisabledError("LLM calls are disabled (LLM_CALLS_ENABLED=false)")

    def api_key(self) -> SecretStr:
        self.check()
        key = self.settings.openai_api_key
        if key is None:
            raise LLMCallsDisabledError("OPENAI_API_KEY is not set")
        return key

    def model(self, name: str | None, setting: str) -> str:
        self.check()
        if not name:
            raise LLMCallsDisabledError(f"{setting} is not set")
        return name

    def chat_model(self, tier: ModelTier) -> ChatOpenAI:
        api_key = self.api_key()
        if tier is ModelTier.FAST:
            model = self.model(self.settings.openai_model_fast, "OPENAI_MODEL_FAST")
        else:
            model = self.model(self.settings.openai_model_smart, "OPENAI_MODEL_SMART")
        return ChatOpenAI(
            model=model,
            api_key=api_key,
            timeout=LLM_TIMEOUT_SECONDS,
            max_retries=LLM_MAX_RETRIES,
        )

    def client(self) -> AsyncOpenAI:
        return AsyncOpenAI(
            api_key=self.api_key().get_secret_value(),
            timeout=SPEECH_TIMEOUT_SECONDS,
            max_retries=LLM_MAX_RETRIES,
        )


def _messages(system: str, user: str, images: Sequence[ImagePart]) -> list[BaseMessage]:
    if not images:
        return [SystemMessage(content=system), HumanMessage(content=user)]
    content: list[str | dict[str, Any]] = [{"type": "text", "text": user}]
    for image in images:
        encoded = base64.b64encode(image.data).decode("ascii")
        url = f"data:{image.media_type};base64,{encoded}"
        content.append({"type": "image_url", "image_url": {"url": url}})
    return [SystemMessage(content=system), HumanMessage(content=content)]


@dataclass(frozen=True)
class _Structured:
    gate: _Gate

    async def generate[T: BaseModel](
        self,
        system: str,
        user: str,
        schema: type[T],
        tier: ModelTier,
        images: Sequence[ImagePart] = (),
    ) -> T:
        # Function calling accepts dict fields and defaults, which strict JSON schema mode rejects.
        model = self.gate.chat_model(tier).with_structured_output(schema, method="function_calling")
        return cast(T, await model.ainvoke(_messages(system, user, images)))


@dataclass(frozen=True)
class _Streamer:
    gate: _Gate

    async def stream(self, system: str, user: str, tier: ModelTier) -> AsyncIterator[str]:
        model = self.gate.chat_model(tier)
        async for chunk in model.astream(_messages(system, user, ())):
            if chunk.text:
                yield chunk.text


@dataclass(frozen=True)
class _Embedder:
    gate: _Gate

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        api_key = self.gate.api_key()
        model = self.gate.model(self.gate.settings.openai_model_embedding, "OPENAI_MODEL_EMBEDDING")
        client = OpenAIEmbeddings(
            model=model,
            openai_api_key=api_key,
            dimensions=EMBEDDING_DIMENSIONS,
            request_timeout=LLM_TIMEOUT_SECONDS,
            max_retries=LLM_MAX_RETRIES,
        )
        return await client.aembed_documents(list(texts))


@dataclass(frozen=True)
class _SpeechToText:
    gate: _Gate

    async def transcribe(self, audio: bytes, media_type: str) -> str:
        client = self.gate.client()
        model = self.gate.model(self.gate.settings.openai_model_stt, "OPENAI_MODEL_STT")
        extension = media_type.split("/")[-1]
        result = await client.audio.transcriptions.create(
            model=model, file=(f"audio.{extension}", audio, media_type), language="en"
        )
        return result.text


@dataclass(frozen=True)
class _TextToSpeech:
    gate: _Gate

    async def speak(self, text: str) -> bytes:
        client = self.gate.client()
        model = self.gate.model(self.gate.settings.openai_model_tts, "OPENAI_MODEL_TTS")
        response = await client.audio.speech.create(
            model=model, voice=_TTS_VOICE, input=text, response_format="mp3"
        )
        return response.content


def build_openai_bundle(settings: Settings) -> LLMBundle:
    gate = _Gate(settings)
    return LLMBundle(
        structured=_Structured(gate),
        streamer=_Streamer(gate),
        embedder=_Embedder(gate),
        stt=_SpeechToText(gate),
        tts=_TextToSpeech(gate),
    )
