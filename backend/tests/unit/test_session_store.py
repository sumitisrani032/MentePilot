from dataclasses import dataclass, field
from uuid import uuid4

from shopchat.agents.state import Turn
from shopchat.chat.session_store import SessionStore


@dataclass
class FakeRedis:
    lists: dict[str, list[str]] = field(default_factory=dict)
    ttls: dict[str, int] = field(default_factory=dict)

    async def rpush(self, key: str, value: str) -> None:
        self.lists.setdefault(key, []).append(value)

    async def ltrim(self, key: str, start: int, end: int) -> None:
        self.lists[key] = self.lists[key][start:]

    async def expire(self, key: str, seconds: int) -> None:
        self.ttls[key] = seconds

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        return self.lists.get(key, [])


def _turn(text: str = "hi") -> Turn:
    return Turn(role="customer", text=text)


async def test_history_expires_after_24h() -> None:
    redis = FakeRedis()
    await SessionStore(redis).append(uuid4(), "s", _turn())
    assert list(redis.ttls.values()) == [86400]


async def test_history_keeps_10_turns() -> None:
    store, shop = SessionStore(FakeRedis()), uuid4()
    for i in range(12):
        await store.append(shop, "s", _turn(str(i)))

    turns = await store.load(shop, "s")

    assert len(turns) == 10 and turns[-1].text == "11"


async def test_session_keys_are_per_shop() -> None:
    store = SessionStore(FakeRedis())
    shop_a, shop_b = uuid4(), uuid4()
    await store.append(shop_a, "s", _turn())
    assert await store.load(shop_b, "s") == []
