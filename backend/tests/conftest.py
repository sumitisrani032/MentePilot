"""Shared fixtures. Integration tests expect local Postgres and Redis from docker compose."""

import os
import subprocess
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

if TYPE_CHECKING:
    from shopchat.llm.ports import LLMBundle
    from tests.fakes import FakeChatService, FakeQueue

_PG_PORT = os.environ.get("SHOPCHAT_POSTGRES_PORT", "5432")
_REDIS_PORT = os.environ.get("SHOPCHAT_REDIS_PORT", "6379")

# Always a dedicated test database, and LLM calls stay off for the whole suite.
os.environ["DATABASE_URL"] = (
    f"postgresql+asyncpg://shopchat_app:shopchat_app@localhost:{_PG_PORT}/shopchat_test"
)
os.environ["DATABASE_OWNER_URL"] = (
    f"postgresql+asyncpg://shopchat_owner:shopchat_owner@localhost:{_PG_PORT}/shopchat_test"
)
os.environ["REDIS_URL"] = f"redis://localhost:{_REDIS_PORT}/15"
os.environ["APP_URL"] = "https://app.example.test"
os.environ["LLM_CALLS_ENABLED"] = "false"
# Graph runs must never be traced to an external service.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["VOICE_ENABLED"] = "false"
os.environ["SHOPIFY_API_KEY"] = "test-client-id"
os.environ["SHOPIFY_API_SECRET"] = "test-client-secret"
os.environ["WIDGET_TOKEN_SECRET"] = "test-widget-secret-with-enough-length-for-hs256"
# A valid, throwaway Fernet key used only by tests.
os.environ["TOKEN_ENCRYPTION_KEY"] = "MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU2Nzg5MDE="


@dataclass(frozen=True)
class TwoShops:
    a: UUID
    b: UUID
    domain_a: str
    domain_b: str


@pytest.fixture(scope="session")
def migrated() -> Iterator[None]:
    subprocess.run(["alembic", "upgrade", "head"], check=True)
    yield


@pytest.fixture
async def owner_conn(migrated: None) -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(os.environ["DATABASE_OWNER_URL"], poolclass=NullPool)
    async with engine.begin() as connection:
        yield connection
    await engine.dispose()


@pytest.fixture
async def db_app_conn(migrated: None) -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    async with engine.connect() as connection:
        yield connection
    await engine.dispose()


@pytest.fixture
async def two_shops(migrated: None) -> AsyncIterator[TwoShops]:
    shops = TwoShops(
        a=uuid4(),
        b=uuid4(),
        domain_a=f"a-{uuid4().hex[:8]}.myshopify.com",
        domain_b=f"b-{uuid4().hex[:8]}.myshopify.com",
    )
    engine = create_async_engine(os.environ["DATABASE_OWNER_URL"], poolclass=NullPool)
    insert = text(
        "INSERT INTO shops (id, domain, scopes, status, features) "
        "VALUES (:id, :domain, 'read_products,read_inventory', 'active', "
        '\'{"image": true, "skin_analysis": true, "voice": false}\')'
    )
    async with engine.begin() as connection:
        await connection.execute(insert, {"id": shops.a, "domain": shops.domain_a})
        await connection.execute(insert, {"id": shops.b, "domain": shops.domain_b})
    yield shops
    async with engine.begin() as connection:
        await connection.execute(
            text("DELETE FROM shops WHERE id IN (:a, :b)"), {"a": shops.a, "b": shops.b}
        )
    await engine.dispose()


@pytest.fixture
def chat_service() -> "FakeChatService":
    from tests.fakes import FakeChatService

    return FakeChatService()


@pytest.fixture
def bundle() -> "LLMBundle":
    from tests.fakes import fake_bundle

    return fake_bundle()


@pytest.fixture
def queue() -> "FakeQueue":
    from tests.fakes import FakeQueue

    return FakeQueue()


@pytest.fixture
async def client(
    chat_service: "FakeChatService", bundle: "LLMBundle", queue: "FakeQueue", migrated: None
) -> AsyncIterator[httpx.AsyncClient]:
    from shopchat.api.app import app
    from shopchat.api.deps import get_bundle, get_chat_service, get_queue

    app.dependency_overrides[get_chat_service] = lambda: chat_service
    app.dependency_overrides[get_bundle] = lambda: bundle
    app.dependency_overrides[get_queue] = lambda: queue
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
    app.dependency_overrides.clear()
