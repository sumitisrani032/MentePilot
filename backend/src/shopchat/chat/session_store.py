"""Short-lived conversation memory. Nothing here outlives 24 hours."""

from typing import Any
from uuid import UUID

from shopchat.agents.state import Turn

SESSION_TTL_SECONDS = 86400
MAX_TURNS = 10


class SessionStore:
    def __init__(self, redis: Any) -> None:
        self._redis = redis

    @staticmethod
    def _key(shop_id: UUID, session_id: str) -> str:
        return f"chat:{shop_id}:{session_id}"

    async def load(self, shop_id: UUID, session_id: str) -> list[Turn]:
        items = await self._redis.lrange(self._key(shop_id, session_id), 0, -1)
        return [Turn.model_validate_json(item) for item in items]

    async def append(self, shop_id: UUID, session_id: str, turn: Turn) -> None:
        key = self._key(shop_id, session_id)
        await self._redis.rpush(key, turn.model_dump_json())
        await self._redis.ltrim(key, -MAX_TURNS, -1)
        await self._redis.expire(key, SESSION_TTL_SECONDS)
