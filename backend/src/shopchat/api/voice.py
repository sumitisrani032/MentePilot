"""Speech endpoints. Built and complete, but switched off by default."""

from collections.abc import Mapping
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status

from shopchat.api.deps import WidgetContext, get_bundle, widget_shop
from shopchat.api.uploads import AUDIO_TYPES, MAX_AUDIO_BYTES, base_media_type, read_upload
from shopchat.chat.usage import record_usage
from shopchat.config import Settings
from shopchat.llm.ports import LLMBundle

router = APIRouter()

MAX_SPEECH_CHARS = 1000


def voice_active(settings: Settings, shop_features: Mapping[str, bool]) -> bool:
    return settings.voice_enabled and shop_features.get("voice", False)


def _require_voice(context: WidgetContext) -> None:
    # features["voice"] already includes the global switch.
    if not context.features["voice"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Voice is not enabled")


@router.post("/v1/voice/transcribe")
async def transcribe(
    context: Annotated[WidgetContext, Depends(widget_shop)],
    bundle: Annotated[LLMBundle, Depends(get_bundle)],
    audio: Annotated[UploadFile, File()],
    response: Response,
) -> dict[str, str]:
    _require_voice(context)
    data = await read_upload(audio, AUDIO_TYPES, MAX_AUDIO_BYTES)
    text = await bundle.stt.transcribe(data, base_media_type(audio.content_type))
    await record_usage(context.shop_id, "audio_in", len(data))
    response.headers.update(context.cors_headers)
    return {"text": text}


@router.post("/v1/voice/speak")
async def speak(
    context: Annotated[WidgetContext, Depends(widget_shop)],
    bundle: Annotated[LLMBundle, Depends(get_bundle)],
    text: Annotated[str, Form(min_length=1, max_length=MAX_SPEECH_CHARS)],
) -> Response:
    _require_voice(context)
    audio = await bundle.tts.speak(text)
    await record_usage(context.shop_id, "audio_out", len(text))
    return Response(content=audio, media_type="audio/mpeg", headers=context.cors_headers)
