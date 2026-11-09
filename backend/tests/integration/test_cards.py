from decimal import Decimal

from shopchat.db.session import session_for_shop
from shopchat.search.cards import load_cards
from tests.conftest import TwoShops
from tests.factories import make_product


async def _add(shop_id, source_id: str, **overrides):
    product = make_product(shop_id, source_id=source_id, **overrides)
    async with session_for_shop(shop_id) as session:
        session.add(product)
    return product.id


async def test_card_price_comes_from_database(two_shops: TwoShops) -> None:
    product_id = await _add(two_shops.a, "a", min_price=Decimal("7.50"))

    [card] = await load_cards(two_shops.a, [product_id], two_shops.domain_a)

    assert card.price == Decimal("7.50")


async def test_card_shows_the_brand(two_shops: TwoShops) -> None:
    product_id = await _add(two_shops.a, "a", vendor="Acme")

    [card] = await load_cards(two_shops.a, [product_id], two_shops.domain_a)

    assert card.vendor == "Acme"


async def test_card_carries_a_trimmed_description(two_shops: TwoShops) -> None:
    product_id = await _add(two_shops.a, "a", description="x" * 900)

    [card] = await load_cards(two_shops.a, [product_id], two_shops.domain_a)

    assert len(card.description) == 500


async def test_card_link_uses_the_shop_and_handle(two_shops: TwoShops) -> None:
    product_id = await _add(two_shops.a, "a", handle="sea-lotion")

    [card] = await load_cards(two_shops.a, [product_id], two_shops.domain_a)

    assert card.url == f"https://{two_shops.domain_a}/products/sea-lotion"


async def test_card_without_image_is_valid(two_shops: TwoShops) -> None:
    product_id = await _add(two_shops.a, "a", image_urls=[])

    [card] = await load_cards(two_shops.a, [product_id], two_shops.domain_a)

    assert card.image_url is None


async def test_sold_out_at_card_time_is_dropped(two_shops: TwoShops) -> None:
    product_id = await _add(two_shops.a, "a", available=False)
    assert await load_cards(two_shops.a, [product_id], two_shops.domain_a) == []


async def test_card_order_follows_the_request(two_shops: TwoShops) -> None:
    first = await _add(two_shops.a, "a")
    second = await _add(two_shops.a, "b")

    cards = await load_cards(two_shops.a, [second, first], two_shops.domain_a)

    assert [card.id for card in cards] == [second, first]


async def test_another_shops_product_cannot_become_a_card(two_shops: TwoShops) -> None:
    product_id = await _add(two_shops.b, "b")
    assert await load_cards(two_shops.a, [product_id], two_shops.domain_a) == []
