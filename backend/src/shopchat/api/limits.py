"""Reject oversized widget requests before anything parses or stores them."""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

MAX_WIDGET_BODY_BYTES = 11 * 1024 * 1024


class WidgetBodyLimit:
    """Pure ASGI so that streamed chat responses pass through untouched."""

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_WIDGET_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._applies(scope):
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        length = headers.get(b"content-length", b"")
        if not length.isdigit():
            status, detail = 411, "Content-Length is required"
        elif int(length) > self.max_bytes:
            status, detail = 413, "File is too large"
        else:
            await self.app(scope, receive, send)
            return
        origin = headers.get(b"origin", b"").decode("latin-1")
        response_headers = {"Access-Control-Allow-Origin": origin, "Vary": "Origin"}
        response = JSONResponse({"detail": detail}, status, headers=response_headers)
        await response(scope, receive, send)

    @staticmethod
    def _applies(scope: Scope) -> bool:
        return (
            scope["type"] == "http"
            and scope["method"] == "POST"
            and str(scope["path"]).startswith("/v1/")
        )
