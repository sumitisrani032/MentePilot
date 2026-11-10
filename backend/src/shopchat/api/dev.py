"""Local development page: the real widget on a placeholder shop, with no Shopify store.

Every route here answers 404 unless DEV_MODE is true, so production never exposes them.
"""

from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse

from shopchat.api.deps import load_active_shop
from shopchat.api.proxy import build_session
from shopchat.config import Settings, get_settings

_FRONTEND_DIR = Path(__file__).resolve().parents[4] / "frontend"
_PAGE = _FRONTEND_DIR / "dev" / "index.html"
_WIDGET_DIR = _FRONTEND_DIR / "extensions" / "chat-widget" / "assets"
_WIDGET_FILES = {"chat.js": "text/javascript", "chat.css": "text/css"}
# Widget edits should show on a plain refresh.
_NO_CACHE = {"Cache-Control": "no-store"}


def require_dev_mode(settings: Annotated[Settings, Depends(get_settings)]) -> None:
    if not settings.dev_mode:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")


router = APIRouter(prefix="/dev", dependencies=[Depends(require_dev_mode)])


def _valid_dev_origin(origin: str) -> bool:
    parts = urlsplit(origin)
    return parts.scheme in {"http", "https"} and bool(parts.netloc) and not parts.path


@router.get("")
async def dev_page() -> FileResponse:
    return FileResponse(_PAGE, media_type="text/html", headers=_NO_CACHE)


@router.get("/widget/{name}")
async def widget_file(name: str) -> FileResponse:
    media_type = _WIDGET_FILES.get(name)
    if media_type is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    return FileResponse(_WIDGET_DIR / name, media_type=media_type, headers=_NO_CACHE)


@router.post("/session")
async def dev_session(
    request: Request, origin: str, settings: Annotated[Settings, Depends(get_settings)]
) -> dict[str, Any]:
    """Like the App Proxy session, but for DEV_SHOP_DOMAIN and with no Shopify signature."""
    if not _valid_dev_origin(origin):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid origin")
    shop = await load_active_shop(settings.dev_shop_domain)
    if shop is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Store {settings.dev_shop_domain} is not in the database. "
            "Load the seed data or set DEV_SHOP_DOMAIN to an indexed store.",
        )
    api_base = str(request.base_url).rstrip("/")
    return await build_session(shop, origin, api_base, settings)
