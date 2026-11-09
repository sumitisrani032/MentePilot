"""Validate uploads. Files stay in memory and are never written anywhere."""

from fastapi import HTTPException, UploadFile, status

IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
AUDIO_TYPES = frozenset({"audio/webm", "audio/mp4", "audio/mpeg", "audio/wav"})
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_AUDIO_BYTES = 10 * 1024 * 1024


def _is_declared_image(data: bytes, content_type: str) -> bool:
    if content_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if content_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/webp":
        return data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return True


def base_media_type(content_type: str | None) -> str:
    return (content_type or "").split(";")[0].strip().lower()


def validate_upload(
    data: bytes, content_type: str, allowed: frozenset[str], max_bytes: int
) -> None:
    if content_type not in allowed:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Unsupported file type")
    if len(data) > max_bytes:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "File is too large")
    if not data or not _is_declared_image(data, content_type):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "File content is not valid")


async def read_upload(upload: UploadFile, allowed: frozenset[str], max_bytes: int) -> bytes:
    data = await upload.read(max_bytes + 1)
    validate_upload(data, base_media_type(upload.content_type), allowed, max_bytes)
    return data
