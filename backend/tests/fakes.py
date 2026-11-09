"""In-memory stand-ins for the LLM ports. None of these touch the network."""

import hashlib
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel

from shopchat.chat.service import ChatEvent, ChatRequest, DoneEvent, TokenEvent
from shopchat.llm.ports import ImagePart, LLMBundle, ModelTier

DIMENSIONS = 1536


@dataclass
class LLMCall:
    system: str
    user: str
    schema: type[BaseModel]
    tier: ModelTier
    images: Sequence[ImagePart]


@dataclass
class FakeStructuredLLM:
    responses: list[BaseModel] = field(default_factory=list)
    calls: list[LLMCall] = field(default_factory=list)
    fail_with: Exception | None = None

    async def generate[T: BaseModel](
        self,
        system: str,
        user: str,
        schema: type[T],
        tier: ModelTier,
        images: Sequence[ImagePart] = (),
    ) -> T:
        self.calls.append(LLMCall(system, user, schema, tier, images))
        if self.fail_with is not None:
            raise self.fail_with
        response = self.responses.pop(0)
        assert isinstance(response, schema), f"expected {schema}, queued {type(response)}"
        return response


@dataclass
class FakeStreamer:
    tokens: list[str] = field(default_factory=lambda: ["Hello", " there"])
    calls: list[tuple[str, str, ModelTier]] = field(default_factory=list)

    async def stream(self, system: str, user: str, tier: ModelTier) -> AsyncIterator[str]:
        self.calls.append((system, user, tier))
        for token in self.tokens:
            yield token


@dataclass
class FakeEmbedder:
    calls: list[list[str]] = field(default_factory=list)

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [_vector(text) for text in texts]


def _vector(text: str) -> list[float]:
    """Deterministic unit-length-ish vector: identical text gives identical vectors."""
    seed = hashlib.sha256(text.encode()).digest()
    return [(seed[i % len(seed)] - 127.5) / 127.5 for i in range(DIMENSIONS)]


@dataclass
class FakeSpeechToText:
    text: str = "hello"

    async def transcribe(self, audio: bytes, media_type: str) -> str:
        return self.text


@dataclass
class FakeTextToSpeech:
    audio: bytes = b"mp3-bytes"

    async def speak(self, text: str) -> bytes:
        return self.audio


def fake_bundle(
    structured: FakeStructuredLLM | None = None,
    streamer: FakeStreamer | None = None,
    embedder: FakeEmbedder | None = None,
) -> LLMBundle:
    return LLMBundle(
        structured=structured or FakeStructuredLLM(),
        streamer=streamer or FakeStreamer(),
        embedder=embedder or FakeEmbedder(),
        stt=FakeSpeechToText(),
        tts=FakeTextToSpeech(),
    )


@dataclass
class FakeQueue:
    jobs: list[tuple] = field(default_factory=list)
    job_ids: list[str | None] = field(default_factory=list)

    async def enqueue_job(self, name: str, *args: object, _job_id: str | None = None) -> None:
        self.jobs.append((name, *args))
        self.job_ids.append(_job_id)


@dataclass
class FakeChatService:
    requests: list[ChatRequest] = field(default_factory=list)

    async def handle(self, request: ChatRequest) -> AsyncIterator[ChatEvent]:
        self.requests.append(request)
        yield TokenEvent(text="Hello")
        yield DoneEvent()
