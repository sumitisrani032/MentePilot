"""Provider-neutral interfaces for every model capability the app uses."""

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel


class ModelTier(StrEnum):
    FAST = "fast"
    SMART = "smart"


class ImagePart(BaseModel):
    data: bytes
    media_type: str


class StructuredLLM(Protocol):
    async def generate[T: BaseModel](
        self,
        system: str,
        user: str,
        schema: type[T],
        tier: ModelTier,
        images: Sequence[ImagePart] = (),
    ) -> T: ...


class TextStreamer(Protocol):
    def stream(self, system: str, user: str, tier: ModelTier) -> AsyncIterator[str]: ...


class Embedder(Protocol):
    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class SpeechToText(Protocol):
    async def transcribe(self, audio: bytes, media_type: str) -> str: ...


class TextToSpeech(Protocol):
    async def speak(self, text: str) -> bytes: ...


@dataclass(frozen=True)
class LLMBundle:
    structured: StructuredLLM
    streamer: TextStreamer
    embedder: Embedder
    stt: SpeechToText
    tts: TextToSpeech
