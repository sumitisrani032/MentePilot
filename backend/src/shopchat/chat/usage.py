"""Per-store usage figures. Usage is recorded for visibility and never blocks a request."""

from uuid import UUID, uuid4

from shopchat.db.models import UsageEvent
from shopchat.db.session import session_for_shop


async def record_usage(shop_id: UUID, kind: str, quantity: int) -> None:
    async with session_for_shop(shop_id) as session:
        session.add(UsageEvent(id=uuid4(), shop_id=shop_id, kind=kind, quantity=quantity))
