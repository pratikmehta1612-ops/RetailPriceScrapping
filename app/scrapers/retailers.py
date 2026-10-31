"""Retailer-specific parsing. Each function takes page HTML and returns a ScrapedProduct.

Retailers change their markup often. Every adapter therefore starts from the
generic structured-data parser and only layers site-specific selectors on top,
so a markup change degrades the result instead of breaking it.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from ..extract.structured import clean_text, extract_generic, merge, parse_price, spec_tables
from ..models import ScrapedProduct
from .base import bold_label_specs, build, label_value_specs

# ------------------------------------------------------------------ Amazon


def amazon_asin(url: str) -> str | None:
    match = re.search(r"/(?:dp|gp/product|gp/aw/d|product)/([A-Z0-9]{10})", url)
    return match.group(1) if match else None


def parse_amazon(url: str, html: str) -> ScrapedProduct:
    tree = HTMLParser(html)

    def text(selector: str) -> str | None:
        node = tree.css_first(selector)
        return clean_text(node.text(deep=True)) if node else None

    price = None
    for selector in (
        "#corePrice_feature_div .a-price .a-offscreen",
        "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen",
        "#apex_desktop .a-price .a-offscreen",
        "#priceblock_ourprice",
        "#priceblock_dealprice",
        "#price_inside_buybox",
        ".a-price .a-offscreen",
    ):
        price = parse_price(text(selector))
        if price:
            break

    brand = text("#bylineInfo")
    if brand:
        brand = re.sub(r"^(Visit the|Brand:)\s*", "", brand, flags=re.I)
        brand = re.sub(r"\s*Store$", "", brand).strip()

    specs: dict[str, str] = {}
    for selector in (
        "#productOverview_feature_div table",
        "#productDetails_techSpec_section_1",
        "#productDetails_techSpec_section_2",
        "#technicalSpecifications_section_1",
        "#productDetails_detailBullets_sections1",
        "#poExpander table",
    ):
        specs.update({k: v for k, v in spec_tables(tree, selector).items() if k not in specs})
    for k, v in label_value_specs(tree, "#detailBullets_feature_div li").items():
        specs.setdefault(k, v)

    bullets = [clean_text(li.text(deep=True)) for li in tree.css("#feature-bullets li")]
    image_node = tree.css_first("#landingImage") or tree.css_first("#imgBlkFront")
    image = None
    if image_node is not None:
        image = image_node.attributes.get("data-old-hires") or image_node.attributes.get("src")

    availability = text("#availability")
    site = {
        "title": text("#productTitle"),
        "price": price,
        "brand": brand,
        "image": image,
        "sku": amazon_asin(url),
        "description": " ".join(b for b in bullets if b) or None,
        "availability": availability,
        "specs": specs,
    }
    return build(url, "amazon", merge(site, extract_generic(html)))


# ------------------------------------------------------------------ Walmart


def _find_key(data: Any, key: str, depth: int = 0) -> Any:
    """Depth-first search for the first dict value under `key`."""
    if depth > 12:
        return None
    if isinstance(data, dict):
        if key in data and data[key]:
            return data[key]
        for value in data.values():
            found = _find_key(value, key, depth + 1)
            if found is not None:
                return found
    elif isinstance(data, list):
        for value in data[:50]:
            found = _find_key(value, key, depth + 1)
            if found is not None:
                return found
    return None


def parse_walmart(url: str, html: str) -> ScrapedProduct:
    tree = HTMLParser(html)
    site: dict[str, Any] = {"specs": {}}
    script = tree.css_first("script#__NEXT_DATA__")
    if script is not None:
        try:
            data = json.loads(script.text(deep=True))
        except json.JSONDecodeError:
            data = {}
        product = _find_key(data, "product") or {}
        if isinstance(product, dict):
            price_info = product.get("priceInfo") or {}
            current = price_info.get("currentPrice") or {}
            image_info = product.get("imageInfo") or {}
            brand = product.get("brand")
            site.update(
                title=clean_text(product.get("name")),
                brand=clean_text(brand),
                price=parse_price(current.get("price") or current.get("priceString")),
                currency=current.get("currencyUnit"),
                image=image_info.get("thumbnailUrl"),
                sku=clean_text(product.get("usItemId")),
                mpn=clean_text(product.get("model")),
                gtin=clean_text(product.get("upc")),
                description=clean_text(
                    re.sub(r"<[^>]+>", " ", str(product.get("shortDescription") or ""))
                ),
                availability=clean_text(product.get("availabilityStatus")),
            )
        idml = _find_key(data, "idml") or {}
        for spec in (idml.get("specifications") if isinstance(idml, dict) else None) or []:
            name, value = clean_text(spec.get("name")), clean_text(spec.get("value"))
            if name and value:
                site["specs"][name] = value
    return build(url, "walmart", merge(site, extract_generic(html)))


# ------------------------------------------------------------------ Target


def target_tcin(url: str) -> str | None:
    match = re.search(r"/A-(\d{6,10})", url)
    return match.group(1) if match else None


def parse_target(url: str, html: str) -> ScrapedProduct:
    tree = HTMLParser(html)
    site: dict[str, Any] = {
        "sku": target_tcin(url),
        "specs": label_value_specs(
            tree, '[data-test="item-details-specifications"] div, #specAndDescript div'
        ),
    }
    for k, v in bold_label_specs(tree).items():
        site["specs"].setdefault(k, v)
    title = tree.css_first('h1[data-test="product-title"]')
    if title is not None:
        site["title"] = clean_text(title.text(deep=True))
    price = tree.css_first('[data-test="product-price"]')
    if price is not None:
        site["price"] = parse_price(price.text(deep=True))
    return build(url, "target", merge(site, extract_generic(html)))


# ------------------------------------------------------------------ Best Buy


def bestbuy_sku(url: str) -> str | None:
    query = parse_qs(urlsplit(url).query)
    if "skuId" in query:
        return query["skuId"][0]
    match = re.search(r"/(\d{6,8})\.p\b", url) or re.search(r"/sku/(\d{6,8})", url)
    return match.group(1) if match else None


def parse_bestbuy(url: str, html: str) -> ScrapedProduct:
    tree = HTMLParser(html)
    site: dict[str, Any] = {"sku": bestbuy_sku(url)}
    title = tree.css_first(".sku-title h1") or tree.css_first("h1")
    if title is not None:
        site["title"] = clean_text(title.text(deep=True))
    price = tree.css_first('.priceView-customer-price span[aria-hidden="true"]')
    if price is not None:
        site["price"] = parse_price(price.text(deep=True))
    return build(url, "bestbuy", merge(site, extract_generic(html)))


def bestbuy_from_api(url: str, item: dict) -> ScrapedProduct:
    """Map one product from the official Best Buy Products API."""
    specs = {
        d.get("name"): d.get("value")
        for d in item.get("details") or []
        if d.get("name") and d.get("value")
    }
    data = {
        "title": item.get("name"),
        "price": parse_price(item.get("salePrice") or item.get("regularPrice")),
        "brand": item.get("manufacturer"),
        "image": item.get("image"),
        "sku": str(item.get("sku")) if item.get("sku") else None,
        "mpn": item.get("modelNumber"),
        "gtin": item.get("upc"),
        "description": clean_text(item.get("longDescription") or item.get("shortDescription")),
        "availability": "InStock" if item.get("onlineAvailability") else "OutOfStock",
        "specs": specs,
    }
    return build(item.get("url") or url, "bestbuy", data)
