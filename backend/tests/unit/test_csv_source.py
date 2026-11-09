from decimal import Decimal
from pathlib import Path

from shopchat.catalog.csv_source import read_csv
from shopchat.catalog.types import NormalizedProduct

MINI = Path(__file__).parent.parent / "fixtures" / "mini_catalog.csv"


def _by_handle() -> dict[str, NormalizedProduct]:
    return {product.handle: product for product in read_csv(MINI, "USD")}


def test_groups_rows_by_url_handle() -> None:
    assert len(read_csv(MINI, "USD")) == 5


def test_description_html_is_stripped() -> None:
    assert _by_handle()["day-cream"].description == "A light daily cream."


def test_metafield_columns_become_raw_attributes() -> None:
    attributes = _by_handle()["day-cream"].raw_attributes
    assert attributes["Water and sweat resistance"] == "Not waterproof"


def test_blank_metafields_are_omitted() -> None:
    assert _by_handle()["plain-soap"].raw_attributes == {}


def test_cost_is_never_read() -> None:
    assert "Cost per item" not in _by_handle()["day-cream"].raw_attributes


def test_variants_are_grouped_with_option_names_from_first_row() -> None:
    variants = _by_handle()["day-cream"].variants
    assert [v.options for v in variants] == [{"Size": "30 ml"}, {"Size": "50 ml"}]
    assert variants[1].price == Decimal("19.99")


def test_images_are_collected_in_position_order() -> None:
    assert _by_handle()["day-cream"].image_urls == [
        "https://cdn.example.test/day-1.jpg",
        "https://cdn.example.test/day-2.jpg",
    ]


def test_sold_out_with_deny_is_unavailable() -> None:
    assert _by_handle()["sold-out-serum"].variants[0].available is False


def test_zero_stock_with_continue_selling_is_available() -> None:
    assert _by_handle()["backorder-balm"].variants[0].available is True


def test_product_without_image_or_description_is_kept() -> None:
    soap = _by_handle()["plain-soap"]
    assert soap.image_urls == [] and soap.description == ""


def test_status_is_lowercased_and_currency_applied() -> None:
    cream = _by_handle()["day-cream"]
    assert cream.status == "active" and cream.currency == "USD"


def test_tags_are_split_and_trimmed() -> None:
    assert _by_handle()["day-cream"].tags == ["Skincare", "Daily"]
