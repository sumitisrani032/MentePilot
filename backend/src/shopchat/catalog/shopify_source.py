"""Read products from Shopify, as a bulk export or one at a time."""

import json
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from typing import Any

from shopchat.catalog.text import strip_html
from shopchat.catalog.types import NormalizedProduct, NormalizedVariant
from shopchat.shopify.graphql import AdminClient, ShopifyGraphQLError

# Shopify caps one query's cost. Bulk results are trimmed to the same limits, so a product
# hashes the same however it was fetched.
_MAX_MEDIA = 20
# SEO and ad-feed data describes a listing, not the product, so it only misleads search.
_FEED_NAMESPACES = frozenset({"global", "mm-google-shopping"})
_MAX_VARIANTS = 100
_MAX_METAFIELDS = 100

_PRODUCT_FIELDS = """
id publishedAt handle title descriptionHtml vendor productType status tags updatedAt
category { fullName }
media { edges { node { ... on MediaImage { id image { url } } } } }
variants { edges { node {
    id title price compareAtPrice availableForSale
    selectedOptions { name value }
    inventoryItem { id }
} } }
metafields { edges { node { id namespace key value definition { name } } } }
"""

_START_BULK = (
    'mutation { bulkOperationRunQuery(query: """{ products { edges { node { '
    + _PRODUCT_FIELDS
    + ' } } } }""") { bulkOperation { id } userErrors { field message } } }'
)

_SINGLE_PRODUCT_FIELDS = (
    _PRODUCT_FIELDS.replace("media {", f"media(first: {_MAX_MEDIA}) {{")
    .replace("variants {", f"variants(first: {_MAX_VARIANTS}) {{")
    .replace("metafields {", f"metafields(first: {_MAX_METAFIELDS}) {{")
)

PRODUCT_QUERY = (
    "query($id: ID!) { shop { currencyCode } product(id: $id) {" + _SINGLE_PRODUCT_FIELDS + "} }"
)
SHOP_CURRENCY_QUERY = "{ shop { currencyCode } }"
_PRODUCT_IDS_QUERY = (
    "query($cursor: String) { products(first: 250, after: $cursor) "
    "{ pageInfo { hasNextPage endCursor } nodes { id } } }"
)
BULK_RESULT_QUERY = (
    "query($id: ID!) { node(id: $id) { ... on BulkOperation { status url errorCode } } }"
)


class BulkOperationsDenied(ShopifyGraphQLError):
    """Shopify will not let this app start a bulk export."""


async def start_bulk_import(client: AdminClient) -> str:
    try:
        data = await client.query(_START_BULK)
    except ShopifyGraphQLError as error:
        if "ACCESS_DENIED" in str(error):
            raise BulkOperationsDenied(str(error)) from error
        raise
    result = data["bulkOperationRunQuery"]
    if result["userErrors"]:
        raise ShopifyGraphQLError(str(result["userErrors"]))
    return str(result["bulkOperation"]["id"])


async def list_product_ids(client: AdminClient) -> list[str]:
    ids: list[str] = []
    cursor: str | None = None
    while True:
        page = (await client.query(_PRODUCT_IDS_QUERY, {"cursor": cursor}))["products"]
        ids.extend(node["id"] for node in page["nodes"])
        if not page["pageInfo"]["hasNextPage"]:
            return ids
        cursor = page["pageInfo"]["endCursor"]


async def fetch_all_products(client: AdminClient) -> list[NormalizedProduct]:
    """Import without bulk operations: one regular query per product."""
    products: list[NormalizedProduct] = []
    for gid in await list_product_ids(client):
        product = await fetch_product(client, gid)
        if product is not None:
            products.append(product)
    return products


async def fetch_product(client: AdminClient, gid: str) -> NormalizedProduct | None:
    data = await client.query(PRODUCT_QUERY, {"id": gid})
    node = data["product"]
    return product_from_node(node, data["shop"]["currencyCode"]) if node else None


def _nodes(connection: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [edge["node"] for edge in (connection or {}).get("edges", [])]


def _attribute_value(raw: str) -> str | None:
    """Metafields may hold JSON lists. Rich objects carry no usable plain value."""
    text = raw.strip()
    if "gid://shopify/" in text:  # A reference to another record, not a readable value.
        return None
    if not text.startswith(("[", "{")):
        return text or None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(parsed, list) and all(isinstance(item, str) for item in parsed):
        return ", ".join(parsed) or None
    return None


def _attributes(metafields: Iterable[dict[str, Any]]) -> dict[str, str]:
    attributes: dict[str, str] = {}
    for field in metafields:
        if field.get("namespace") in _FEED_NAMESPACES:
            continue
        value = _attribute_value(field["value"])
        if value is not None:
            definition = field.get("definition") or {}
            attributes[definition.get("name") or field["key"]] = value
    return attributes


def _variant(node: dict[str, Any]) -> NormalizedVariant:
    compare_at = node.get("compareAtPrice")
    inventory = node.get("inventoryItem") or {}
    options = {o["name"]: o["value"] for o in node.get("selectedOptions", [])}
    return NormalizedVariant(
        source_id=node["id"],
        inventory_item_id=inventory.get("id"),
        title=node.get("title", ""),
        options=options,
        price=Decimal(node["price"]),
        compare_at_price=Decimal(compare_at) if compare_at else None,
        available=bool(node.get("availableForSale")),
    )


def _images(media: Iterable[dict[str, Any]]) -> list[str]:
    return [m["image"]["url"] for m in media if (m.get("image") or {}).get("url")]


def _storefront_status(node: dict[str, Any]) -> str:
    """An active product not published to the online store has no working page.

    publishedAt is used because Shopify leaves onlineStoreUrl empty on password-protected stores.
    """
    status = str(node["status"]).lower()
    return "unlisted" if status == "active" and not node.get("publishedAt") else status


def _build(
    node: dict[str, Any],
    media: list[dict[str, Any]],
    variants: list[dict[str, Any]],
    metafields: list[dict[str, Any]],
    currency: str,
) -> NormalizedProduct:
    return NormalizedProduct(
        source_id=node["id"],
        handle=node["handle"],
        title=node["title"],
        description=strip_html(node.get("descriptionHtml") or ""),
        vendor=node.get("vendor") or "",
        product_type=node.get("productType") or "",
        category=(node.get("category") or {}).get("fullName", ""),
        tags=list(node.get("tags") or []),
        status=_storefront_status(node),
        image_urls=_images(media[:_MAX_MEDIA]),
        currency=currency,
        source_updated_at=datetime.fromisoformat(node["updatedAt"]),
        variants=[_variant(variant) for variant in variants[:_MAX_VARIANTS]],
        raw_attributes=_attributes(metafields[:_MAX_METAFIELDS]),
    )


def product_from_node(node: dict[str, Any], currency: str) -> NormalizedProduct:
    """Convert one product from a regular GraphQL response."""
    return _build(
        node,
        _nodes(node.get("media")),
        _nodes(node.get("variants")),
        _nodes(node.get("metafields")),
        currency,
    )


def parse_bulk_jsonl(lines: Iterable[str], currency: str) -> list[NormalizedProduct]:
    """Rebuild products from a bulk export, where children point to parents by id."""
    products: dict[str, dict[str, Any]] = {}
    children: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for line in lines:
        if not line.strip():
            continue
        record = json.loads(line)
        parent = record.get("__parentId")
        if parent is None:
            products[record["id"]] = record
            children[record["id"]] = {"media": [], "variants": [], "metafields": []}
        elif parent in children:
            children[parent][_child_kind(record)].append(record)
    return [
        _build(node, kids["media"], kids["variants"], kids["metafields"], currency)
        for product_id, node in products.items()
        for kids in [children[product_id]]
    ]


def _child_kind(record: dict[str, Any]) -> str:
    gid = str(record.get("id", ""))
    if "/ProductVariant/" in gid:
        return "variants"
    if "/Metafield/" in gid:
        return "metafields"
    return "media"
