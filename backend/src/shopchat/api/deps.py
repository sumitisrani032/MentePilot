"""Shared API dependencies: application services and widget authentication."""

import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any
from uuid import UUID

import jwt
import redis.asyncio as redis_asyncio
from arq.connections import ArqRedis, RedisSettings, create_pool
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select

from shopchat.agents.graph import build_graph
from shopchat.catalog.repository import load_profile
from shopchat.chat.features import effective_features
from shopchat.chat.service import ChatService
from shopchat.chat.session_store import SessionStore
from shopchat.chat.usage import record_usage
from shopchat.config import Settings, get_settings
from shopchat.db.models import Shop
from shopchat.db.session import system_session
from shopchat.llm.openai_adapters import build_openai_bundle
from shopchat.llm.ports import LLMBundle
from shopchat.search.cards import load_cards
from shopchat.search.hybrid import product_detail_chunks, retrieve

WIDGET_TOKEN_SECONDS = 3600
_ALGORITHM = "HS256"


@lru_cache
def get_bundle() -> LLMBundle:
    return build_openai_bundle(get_settings())


@lru_cache
def get_redis() -> Any:
    return redis_asyncio.Redis.from_url(get_settings().redis_url, decode_responses=True)


_queue: ArqRedis | None = None


async def get_queue() -> ArqRedis:
    """The background job queue, connected on first use."""
    global _queue
    if _queue is None:
        _queue = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    return _queue


@lru_cache
def get_chat_service() -> ChatService:
    return ChatService(
        graph=build_graph(get_bundle(), retrieve, product_detail_chunks),
        sessions=SessionStore(get_redis()),
        load_profile=load_profile,
        load_cards=load_cards,
        record_usage=record_usage,
    )


def require_secret(value: Any, name: str) -> str:
    secret = "" if value is None else str(value.get_secret_value())
    if not secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"{name} is not configured")
    return secret


def issue_widget_token(shop_id: UUID, shop_domain: str, origin: str) -> str:
    secret = require_secret(get_settings().widget_token_secret, "WIDGET_TOKEN_SECRET")
    claims = {
        "shop_id": str(shop_id),
        "shop_domain": shop_domain,
        "origin": origin,
        "exp": int(time.time()) + WIDGET_TOKEN_SECONDS,
    }
    return jwt.encode(claims, secret, algorithm=_ALGORITHM)


@dataclass(frozen=True)
class WidgetContext:
    shop_id: UUID
    shop_domain: str
    origin: str
    features: dict[str, bool]

    @property
    def cors_headers(self) -> dict[str, str]:
        return {"Access-Control-Allow-Origin": self.origin, "Vary": "Origin"}


async def load_active_shop(domain: str) -> Shop | None:
    async with system_session() as session:
        result = await session.execute(select(Shop).where(Shop.domain == domain))
        shop = result.scalar_one_or_none()
    return shop if shop is not None and shop.status == "active" else None


async def widget_shop(
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str, Header()] = "",
    origin: Annotated[str, Header()] = "",
) -> WidgetContext:
    """Authenticate a widget call. The token fixes both the store and the browser origin."""
    secret = require_secret(settings.widget_token_secret, "WIDGET_TOKEN_SECRET")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        claims = jwt.decode(token, secret, algorithms=[_ALGORITHM])
    except jwt.PyJWTError as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session") from error
    if origin != claims["origin"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Origin not allowed")
    shop = await load_active_shop(claims["shop_domain"])
    if shop is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Store is not active")
    features = effective_features(settings, shop.features, await load_profile(shop.id))
    return WidgetContext(shop.id, shop.domain, claims["origin"], features)
