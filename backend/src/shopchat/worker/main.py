"""Entry point for the arq background worker."""

from typing import Any, ClassVar

import httpx
from arq.connections import RedisSettings

from shopchat.config import get_settings
from shopchat.llm.openai_adapters import build_openai_bundle
from shopchat.shopify.graphql import AdminClient
from shopchat.worker import tasks

_DOWNLOAD_TIMEOUT_SECONDS = 300
_JOB_TIMEOUT_SECONDS = 4 * 60 * 60


def split_jsonl(text: str) -> list[str]:
    """Split only on newlines. str.splitlines also breaks on U+2028 inside JSON strings."""
    return text.split("\n")


async def _download(url: str) -> list[str]:
    async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT_SECONDS) as client:
        response = await client.get(url)
    response.raise_for_status()
    return split_jsonl(response.text)


async def _startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()

    def client_for(domain: str, token: str) -> AdminClient:
        return AdminClient(domain, token, settings.shopify_api_version)

    ctx["bundle"] = build_openai_bundle(settings)
    ctx["client_for"] = client_for
    ctx["download"] = _download


class WorkerSettings:
    functions: ClassVar[list[Any]] = [
        tasks.sync_shop,
        tasks.finish_bulk,
        tasks.upsert_product,
        tasks.delete_product,
        tasks.update_inventory,
        tasks.deactivate_shop,
        tasks.redact_shop,
    ]
    on_startup = _startup
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_tries = tasks.MAX_TRIES
    job_timeout = _JOB_TIMEOUT_SECONDS
