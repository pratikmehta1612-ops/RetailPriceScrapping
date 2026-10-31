"""Shared scraper plumbing."""

from __future__ import annotations

import re
from typing import Any

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from ..extract.structured import clean_text, extract_generic, merge
from ..models import ScrapedProduct

_LABEL_VALUE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 /&().'-]{1,50}?)\s*:\s*(.{1,200})$")


def label_value_specs(tree: HTMLParser, selector: str) -> dict[str, str]:
    """Read 'Label: value' lines, e.g. <div><b>Size:</b> 5 Quart</div> or <li>Key : Value</li>."""
    specs: dict[str, str] = {}
    for node in tree.css(selector):
        text = clean_text(node.text(deep=True, separator=" "))
        if not text or len(text) > 260:
            continue
        match = _LABEL_VALUE.match(text.replace("‎", "").replace("‏", ""))
        if match:
            key, value = match.group(1).strip(), match.group(2).strip()
            specs.setdefault(key, value)
    return specs


def bold_label_specs(tree: HTMLParser) -> dict[str, str]:
    """Read <div><b>Size:</b> 5 Quart</div> style specs via the label's parent."""
    specs: dict[str, str] = {}
    for label in tree.css("b, strong"):
        label_text = clean_text(label.text(deep=True))
        if not label_text or not label_text.endswith(":") or label.parent is None:
            continue
        parent_text = clean_text(label.parent.text(deep=True, separator=" "))
        if not parent_text or len(parent_text) > 260:
            continue
        value = parent_text.split(":", 1)[-1].strip()
        key = label_text.rstrip(":").strip()
        if key and value and len(key) <= 50:
            specs.setdefault(key, value)
    return specs


def build(url: str, retailer: str, data: dict[str, Any]) -> ScrapedProduct:
    if not data.get("title"):
        raise ValueError("No product title found on the page; it may not be a product page.")
    return ScrapedProduct(
        url=url,
        retailer=retailer,
        title=data["title"],
        price=data.get("price"),
        currency=data.get("currency") or "USD",
        availability=data.get("availability"),
        brand=data.get("brand"),
        image=data.get("image"),
        sku=data.get("sku"),
        mpn=data.get("mpn"),
        gtin=data.get("gtin"),
        description=data.get("description"),
        category_hint=data.get("category_hint"),
        specs=data.get("specs") or {},
    )


def generic(url: str, html: str, retailer: str = "other") -> ScrapedProduct:
    tree = HTMLParser(html)
    data = merge(
        extract_generic(html),
        {"specs": bold_label_specs(tree)},
        {"specs": label_value_specs(tree, "li")},
    )
    return build(url, retailer, data)
