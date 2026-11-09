"""The storefront chat endpoint."""

import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sse_starlette import EventSourceResponse, ServerSentEvent

from shopchat.agents.skin import UNUSABLE_SKIN_PHOTO_REPLY, analyze_skin, skin_context_for
from shopchat.agents.vision import (
    FACE_WITH_SKIN_FEATURE_REPLY,
    FACE_WITHOUT_SKIN_FEATURE_REPLY,
    UNUSABLE_IMAGE_REPLY,
    image_context_for,
    read_image,
)
from shopchat.api.deps import WidgetContext, get_bundle, get_chat_service, widget_shop
from shopchat.api.uploads import IMAGE_TYPES, MAX_IMAGE_BYTES, base_media_type, read_upload
from shopchat.chat.service import (
    TRY_AGAIN_REPLY,
    ChatEvent,
    ChatRequest,
    ChatService,
    DoneEvent,
    ErrorEvent,
    SectionsEvent,
    TokenEvent,
)
from shopchat.chat.usage import record_usage
from shopchat.llm.ports import ImagePart, LLMBundle

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_MESSAGE_CHARS = 1000
MAX_SESSION_ID_CHARS = 128
_DEFAULT_PHOTO_MESSAGE = "Please suggest products based on my photo."


@dataclass(frozen=True)
class _ImageOutcome:
    """Either context for the agents, or a reply that ends the turn."""

    context: str | None = None
    events: Sequence[ChatEvent] = ()


def _to_sse(event: ChatEvent) -> ServerSentEvent:
    names: dict[type, str] = {
        TokenEvent: "token",
        SectionsEvent: "sections",
        DoneEvent: "done",
        ErrorEvent: "error",
    }
    return ServerSentEvent(data=event.model_dump_json(), event=names[type(event)])


def clean_message(message: str, has_image: bool = False) -> str:
    cleaned = message.strip()
    if not cleaned and has_image:
        return _DEFAULT_PHOTO_MESSAGE
    if not cleaned or len(cleaned) > MAX_MESSAGE_CHARS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Message must be 1 to {MAX_MESSAGE_CHARS} characters",
        )
    return cleaned


def _reply(text: str) -> _ImageOutcome:
    return _ImageOutcome(events=(TokenEvent(text=text), DoneEvent()))


def _authorize_image(context: WidgetContext, purpose: str, skin_consent: bool) -> None:
    """Every refusal happens here, before the image reaches any model."""
    if purpose == "skin":
        if not context.features["skin_analysis"]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Skin analysis is not enabled")
        if not skin_consent:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Consent is required")
    elif not context.features["image"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Image upload is not enabled")


async def _understand_image(
    image: ImagePart, purpose: str, context: WidgetContext, bundle: LLMBundle
) -> _ImageOutcome:
    if purpose == "skin":
        skin_context = skin_context_for(await analyze_skin(image, bundle.structured))
        return (
            _ImageOutcome(context=skin_context)
            if skin_context
            else _reply(UNUSABLE_SKIN_PHOTO_REPLY)
        )
    reading = await read_image(image, bundle.structured)
    if reading.kind == "face":
        skin_available = context.features["skin_analysis"]
        return _reply(
            FACE_WITH_SKIN_FEATURE_REPLY if skin_available else FACE_WITHOUT_SKIN_FEATURE_REPLY
        )
    photo_context = image_context_for(reading)
    return _ImageOutcome(context=photo_context) if photo_context else _reply(UNUSABLE_IMAGE_REPLY)


async def _process_image(
    upload: UploadFile, purpose: str, context: WidgetContext, bundle: LLMBundle
) -> _ImageOutcome:
    data = await read_upload(upload, IMAGE_TYPES, MAX_IMAGE_BYTES)
    image = ImagePart(data=data, media_type=base_media_type(upload.content_type))
    try:
        outcome = await _understand_image(image, purpose, context, bundle)
        await record_usage(context.shop_id, "image", 1)
    except Exception as error:
        logger.error("image reading failed: %s", type(error).__name__)
        return _ImageOutcome(events=(ErrorEvent(message=TRY_AGAIN_REPLY),))
    return outcome


@router.post("/v1/chat")
async def chat(
    context: Annotated[WidgetContext, Depends(widget_shop)],
    service: Annotated[ChatService, Depends(get_chat_service)],
    bundle: Annotated[LLMBundle, Depends(get_bundle)],
    session_id: Annotated[str, Form(min_length=1, max_length=MAX_SESSION_ID_CHARS)],
    message: Annotated[str, Form()] = "",
    image: Annotated[UploadFile | None, File()] = None,
    image_purpose: Annotated[Literal["product", "skin"], Form()] = "product",
    skin_consent: Annotated[bool, Form()] = False,
) -> EventSourceResponse:
    text = clean_message(message, has_image=image is not None)
    outcome = _ImageOutcome()
    if image is not None:
        _authorize_image(context, image_purpose, skin_consent)
        outcome = await _process_image(image, image_purpose, context, bundle)

    async def stream() -> AsyncIterator[ServerSentEvent]:
        if outcome.events:
            for event in outcome.events:
                yield _to_sse(event)
            return
        request = ChatRequest(
            shop_id=context.shop_id,
            shop_domain=context.shop_domain,
            session_id=session_id,
            message=text,
            image_context=outcome.context,
        )
        async for event in service.handle(request):
            yield _to_sse(event)

    return EventSourceResponse(stream(), headers=context.cors_headers)
