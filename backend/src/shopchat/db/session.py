"""Database sessions. Store data is only reachable through ``session_for_shop``."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from shopchat.config import get_settings


@lru_cache
def _session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def session_for_shop(shop_id: UUID) -> AsyncIterator[AsyncSession]:
    """Open a transaction in which row-level security exposes only this store."""
    async with _session_factory()() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.shop_id', :shop_id, true)"),
            {"shop_id": str(shop_id)},
        )
        yield session


@asynccontextmanager
async def system_session() -> AsyncIterator[AsyncSession]:
    """Open a transaction with no store context. Only the ``shops`` table is visible."""
    async with _session_factory()() as session, session.begin():
        yield session
