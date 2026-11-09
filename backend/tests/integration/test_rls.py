"""Store isolation is enforced by Postgres, not by application filters."""

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from shopchat.db.models import Product
from shopchat.db.session import session_for_shop
from tests.conftest import TwoShops
from tests.factories import make_product


async def test_shop_cannot_read_another_shops_products(two_shops: TwoShops) -> None:
    async with session_for_shop(two_shops.a) as session:
        session.add(make_product(two_shops.a, source_id="a-1"))

    async with session_for_shop(two_shops.b) as session:
        rows = (await session.execute(select(Product))).scalars().all()

    assert rows == []


async def test_shop_can_read_its_own_products(two_shops: TwoShops) -> None:
    async with session_for_shop(two_shops.a) as session:
        session.add(make_product(two_shops.a, source_id="a-1"))

    async with session_for_shop(two_shops.a) as session:
        count = (await session.execute(select(func.count()).select_from(Product))).scalar_one()

    assert count == 1


async def test_app_role_cannot_bypass_rls(two_shops: TwoShops, db_app_conn) -> None:
    async with session_for_shop(two_shops.a) as session:
        session.add(make_product(two_shops.a, source_id="a-1"))

    # No app.shop_id is set on this connection, so the policy matches nothing.
    count = (await db_app_conn.execute(text("SELECT count(*) FROM products"))).scalar_one()

    assert count == 0


async def test_app_role_is_not_a_superuser_and_cannot_bypass(db_app_conn) -> None:
    row = (
        await db_app_conn.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        )
    ).one()

    assert tuple(row) == (False, False)


async def test_insert_for_other_shop_is_rejected(two_shops: TwoShops) -> None:
    with pytest.raises(DBAPIError, match="row-level security"):
        async with session_for_shop(two_shops.a) as session:
            session.add(make_product(two_shops.b, source_id="b-1"))
