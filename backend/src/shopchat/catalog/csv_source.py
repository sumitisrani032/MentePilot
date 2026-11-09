"""Read a Shopify product CSV export. Used for development and tests only."""

import csv
import re
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

from shopchat.catalog.text import strip_html
from shopchat.catalog.types import NormalizedProduct, NormalizedVariant

_METAFIELD_COLUMN = re.compile(r"^(?P<label>.+) \(product\.metafields\.[^.]+\.[^)]+\)$")
_OPTION_SLOTS = (1, 2, 3)


def read_csv(path: Path, currency: str) -> list[NormalizedProduct]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    groups: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        groups.setdefault(row["URL handle"], []).append(row)
    return [_product(handle, group, currency) for handle, group in groups.items()]


def _product(handle: str, rows: Sequence[dict[str, str]], currency: str) -> NormalizedProduct:
    first = rows[0]
    option_names = {slot: first.get(f"Option{slot} name", "") for slot in _OPTION_SLOTS}
    return NormalizedProduct(
        source_id=handle,
        handle=handle,
        title=first["Title"],
        description=strip_html(first["Description"]),
        vendor=first["Vendor"],
        product_type=first["Type"],
        category=first["Product category"],
        tags=[tag.strip() for tag in first["Tags"].split(",") if tag.strip()],
        status=first["Status"].lower(),
        image_urls=_images(rows),
        currency=currency,
        variants=[_variant(row, option_names) for row in rows if row["SKU"].strip()],
        raw_attributes=_attributes(first),
    )


def _images(rows: Sequence[dict[str, str]]) -> list[str]:
    positioned = [
        (int(row["Image position"] or 0), row["Product image URL"])
        for row in rows
        if row["Product image URL"].strip()
    ]
    return [url for _, url in sorted(positioned, key=lambda item: item[0])]


def _attributes(row: dict[str, str]) -> dict[str, str]:
    attributes: dict[str, str] = {}
    for column, value in row.items():
        match = _METAFIELD_COLUMN.match(column)
        if match and value.strip():
            attributes[match["label"]] = value.strip()
    return attributes


def _variant(row: dict[str, str], option_names: dict[int, str]) -> NormalizedVariant:
    options = {
        name: row[f"Option{slot} value"]
        for slot, name in option_names.items()
        if name and row.get(f"Option{slot} value", "").strip()
    }
    compare_at = row["Compare-at price"].strip()
    in_stock = int(row["Inventory quantity"] or 0) > 0
    return NormalizedVariant(
        source_id=row["SKU"],
        title=" / ".join(options.values()),
        options=options,
        price=Decimal(row["Price"]),
        compare_at_price=Decimal(compare_at) if compare_at else None,
        available=in_stock or row["Continue selling when out of stock"].upper() == "CONTINUE",
    )
