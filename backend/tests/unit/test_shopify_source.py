import json
from decimal import Decimal

from shopchat.catalog.shopify_source import PRODUCT_QUERY, parse_bulk_jsonl, product_from_node

PRODUCT = "gid://shopify/Product/1"


def _product_record() -> dict:
    return {
        "id": PRODUCT,
        "publishedAt": "2026-10-01T10:00:00Z",
        "handle": "linen-shirt",
        "title": "Linen Shirt",
        "descriptionHtml": "<p>A <b>cool</b> shirt.</p>",
        "vendor": "Acme",
        "productType": "Shirt",
        "status": "ACTIVE",
        "tags": ["summer"],
        "updatedAt": "2026-10-01T10:00:00Z",
        "category": {"fullName": "Apparel > Shirts"},
    }


def _variant_record() -> dict:
    return {
        "id": "gid://shopify/ProductVariant/2",
        "__parentId": PRODUCT,
        "title": "Medium",
        "price": "20.00",
        "compareAtPrice": None,
        "availableForSale": True,
        "selectedOptions": [{"name": "Size", "value": "M"}],
        "inventoryItem": {"id": "gid://shopify/InventoryItem/3"},
    }


def _metafield(key: str, value: str, name: str | None = None) -> dict:
    return {
        "id": f"gid://shopify/Metafield/{key}",
        "__parentId": PRODUCT,
        "key": key,
        "value": value,
        "definition": {"name": name} if name else None,
    }


def _jsonl(*records: dict) -> list[str]:
    return [json.dumps(record) for record in records]


def test_children_attach_through_parent_id() -> None:
    [product] = parse_bulk_jsonl(_jsonl(_product_record(), _variant_record()), "USD")
    assert product.variants[0].price == Decimal("20.00")
    assert product.variants[0].inventory_item_id == "gid://shopify/InventoryItem/3"


def test_metafield_label_uses_definition_name() -> None:
    lines = _jsonl(_product_record(), _metafield("care", "Hand wash", "Care guide"))
    assert parse_bulk_jsonl(lines, "USD")[0].raw_attributes == {"Care guide": "Hand wash"}


def test_metafield_label_uses_key_when_no_definition() -> None:
    lines = _jsonl(_product_record(), _metafield("care", "Hand wash"))
    assert parse_bulk_jsonl(lines, "USD")[0].raw_attributes == {"care": "Hand wash"}


def test_json_list_metafield_is_joined() -> None:
    lines = _jsonl(_product_record(), _metafield("season", '["Summer", "Spring"]'))
    assert parse_bulk_jsonl(lines, "USD")[0].raw_attributes == {"season": "Summer, Spring"}


def test_rich_json_metafield_is_skipped() -> None:
    lines = _jsonl(_product_record(), _metafield("notes", '{"type": "root"}'))
    assert parse_bulk_jsonl(lines, "USD")[0].raw_attributes == {}


def test_seo_and_ad_feed_fields_are_ignored() -> None:
    seo = {**_metafield("title_tag", "Buy now"), "namespace": "global"}
    feed = {**_metafield("gender", "Unisex"), "namespace": "mm-google-shopping"}
    custom = {**_metafield("fit", "Slim"), "namespace": "custom"}
    lines = _jsonl(_product_record(), seo, feed, custom)
    assert parse_bulk_jsonl(lines, "USD")[0].raw_attributes == {"fit": "Slim"}


def test_reference_metafield_is_skipped() -> None:
    lines = _jsonl(_product_record(), _metafield("color", '["gid://shopify/Metaobject/1"]'))
    assert parse_bulk_jsonl(lines, "USD")[0].raw_attributes == {}


def test_product_not_on_the_online_store_is_unlisted() -> None:
    record = {**_product_record(), "publishedAt": None}
    assert parse_bulk_jsonl(_jsonl(record), "USD")[0].status == "unlisted"


def test_single_product_query_stays_within_shopify_cost_limits() -> None:
    assert "variants(first: 100)" in PRODUCT_QUERY and "metafields(first: 100)" in PRODUCT_QUERY


def test_bulk_variants_are_trimmed_like_a_single_fetch() -> None:
    variants = [
        {**_variant_record(), "id": f"gid://shopify/ProductVariant/{i}"} for i in range(120)
    ]
    assert len(parse_bulk_jsonl(_jsonl(_product_record(), *variants), "USD")[0].variants) == 100


def test_html_description_is_stripped() -> None:
    assert parse_bulk_jsonl(_jsonl(_product_record()), "USD")[0].description == "A cool shirt."


def test_status_is_lowercased_and_image_is_read() -> None:
    media = {
        "id": "gid://shopify/MediaImage/9",
        "__parentId": PRODUCT,
        "image": {"url": "https://cdn.example.test/a.jpg"},
    }
    [product] = parse_bulk_jsonl(_jsonl(_product_record(), media), "USD")
    assert product.status == "active" and product.image_urls == ["https://cdn.example.test/a.jpg"]


def test_non_image_media_is_ignored() -> None:
    media = {"__parentId": PRODUCT}
    assert parse_bulk_jsonl(_jsonl(_product_record(), media), "USD")[0].image_urls == []


def test_single_product_response_is_understood() -> None:
    node = {
        **_product_record(),
        "media": {"edges": []},
        "variants": {"edges": [{"node": _variant_record()}]},
        "metafields": {"edges": [{"node": _metafield("care", "Hand wash")}]},
    }

    product = product_from_node(node, "EUR")

    assert product.currency == "EUR" and len(product.variants) == 1
    assert product.raw_attributes == {"care": "Hand wash"}
