"""The FastAPI application."""

from fastapi import FastAPI, Request, Response
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.formparsers import MultiPartParser

from shopchat.api import admin, auth, chat, dev, proxy, voice, webhooks
from shopchat.api.limits import MAX_WIDGET_BODY_BYTES, WidgetBodyLimit

# Uploads must stay in memory: photos and audio are never written to disk.
MultiPartParser.spool_max_size = MAX_WIDGET_BODY_BYTES

app = FastAPI(title="Shopify Product Chatbot")
app.add_middleware(WidgetBodyLimit)
app.include_router(admin.router)
app.include_router(auth.router)
app.include_router(proxy.router)
app.include_router(chat.router)
app.include_router(voice.router)
app.include_router(webhooks.router)
app.include_router(dev.router)


def _readable_by_widget(request: Request, response: Response) -> Response:
    """Without this the browser hides the status, so the widget could not react to errors."""
    origin = request.headers.get("origin")
    if origin and request.url.path.startswith("/v1/"):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
    return response


@app.exception_handler(HTTPException)
async def handle_http_error(request: Request, error: HTTPException) -> Response:
    return _readable_by_widget(request, await http_exception_handler(request, error))


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, error: RequestValidationError) -> Response:
    return _readable_by_widget(request, await request_validation_exception_handler(request, error))


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.options("/v1/{path:path}")
async def widget_preflight(request: Request, path: str) -> Response:
    """Preflight carries no token, so the store and origin check happens on the real call."""
    return Response(
        status_code=204,
        headers={
            "Access-Control-Allow-Origin": request.headers.get("origin", ""),
            "Access-Control-Allow-Methods": "POST",
            "Access-Control-Allow-Headers": "Authorization",
            "Access-Control-Max-Age": "600",
            "Vary": "Origin",
        },
    )
