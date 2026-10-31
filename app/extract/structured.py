"""Pull product data out of the structured markup most retailers embed.

Order of preference: schema.org JSON-LD, then microdata (itemprop), then
OpenGraph / product meta tags. Spec tables (<table>, <dl>) are read generically.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable

from selectolax.lexbor import LexborHTMLParser as HTMLParser, LexborNode as Node

_PRICE_RE = re.compile(r"(\d{1,3}(?:[,\s]\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)")


def parse_price(value: Any) -> float | None:
    """Turn '$1,299.99', '1299.99', 1299.99 or {'price': ...} into a float."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    if isinstance(value, dict):
        for key in ("price", "lowPrice", "value", "amount"):
            if key in value:
                return parse_price(value[key])
        return None
    match = _PRICE_RE.search(str(value).replace("\xa0", " "))
    if not match:
        return None
    try:
        price = float(match.group(1).replace(",", "").replace(" ", ""))
    except ValueError:
        return None
    return price if price > 0 else None


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("name") or value.get("@id")
    if isinstance(value, list):
        value = value[0] if value else None
        return clean_text(value)
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def _walk_jsonld(data: Any) -> Iterable[dict]:
    if isinstance(data, list):
        for item in data:
            yield from _walk_jsonld(item)
    elif isinstance(data, dict):
        yield data
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in data:
                yield from _walk_jsonld(data[key])


def _is_product(node: dict) -> bool:
    types = node.get("@type")
    if isinstance(types, str):
        types = [types]
    return any(str(t).lower() in {"product", "productgroup", "car", "vehicle"} for t in types or [])


def jsonld_products(tree: HTMLParser) -> list[dict]:
    found: list[dict] = []
    for script in tree.css('script[type="application/ld+json"]'):
        raw = script.text(deep=True, strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Some sites put several objects or trailing commas in one block.
            try:
                data = json.loads(re.sub(r",\s*([}\]])", r"\1", raw))
            except json.JSONDecodeError:
                continue
        found.extend(node for node in _walk_jsonld(data) if _is_product(node))
    return found


def _offer_fields(offers: Any) -> tuple[float | None, str | None, str | None]:
    if isinstance(offers, list):
        prices = [_offer_fields(o) for o in offers]
        prices = [p for p in prices if p[0] is not None]
        return min(prices, key=lambda p: p[0]) if prices else (None, None, None)
    if not isinstance(offers, dict):
        return None, None, None
    if "offers" in offers and offers.get("@type") == "AggregateOffer" and "lowPrice" not in offers:
        return _offer_fields(offers["offers"])
    price = parse_price(offers.get("price") or offers.get("lowPrice") or offers.get("priceSpecification"))
    currency = offers.get("priceCurrency")
    availability = clean_text(offers.get("availability"))
    if availability:
        availability = availability.rsplit("/", 1)[-1]
    return price, currency, availability


def _props_to_specs(props: Any) -> dict[str, str]:
    specs: dict[str, str] = {}
    if isinstance(props, dict):
        props = [props]
    for prop in props or []:
        if isinstance(prop, dict):
            name, value = clean_text(prop.get("name")), clean_text(prop.get("value"))
            if name and value:
                specs[name] = value
    return specs


def from_jsonld(node: dict) -> dict[str, Any]:
    price, currency, availability = _offer_fields(node.get("offers"))
    image = node.get("image")
    if isinstance(image, list):
        image = image[0] if image else None
    if isinstance(image, dict):
        image = image.get("url")
    specs = _props_to_specs(node.get("additionalProperty"))
    for key in ("color", "material", "size", "model", "weight", "width", "height", "depth"):
        if node.get(key) and isinstance(node[key], (str, int, float)):
            specs.setdefault(key.title(), str(node[key]))
    return {
        "title": clean_text(node.get("name")),
        "brand": clean_text(node.get("brand")),
        "price": price,
        "currency": currency,
        "availability": availability,
        "image": clean_text(image),
        "sku": clean_text(node.get("sku") or node.get("productID")),
        "mpn": clean_text(node.get("mpn")),
        "gtin": clean_text(
            node.get("gtin13") or node.get("gtin12") or node.get("gtin") or node.get("gtin14")
        ),
        "description": clean_text(node.get("description")),
        "category_hint": clean_text(node.get("category")),
        "specs": specs,
    }


def _itemprop(tree: HTMLParser | Node, name: str) -> str | None:
    node = tree.css_first(f'[itemprop="{name}"]')
    if node is None:
        return None
    return clean_text(
        node.attributes.get("content") or node.attributes.get("src") or node.text(deep=True)
    )


def from_microdata(tree: HTMLParser) -> dict[str, Any]:
    scope = tree.css_first('[itemtype*="schema.org/Product"]')
    if scope is None:
        return {}
    return {
        "title": _itemprop(scope, "name"),
        "brand": _itemprop(scope, "brand"),
        "price": parse_price(_itemprop(scope, "price")),
        "currency": _itemprop(scope, "priceCurrency"),
        "image": _itemprop(scope, "image"),
        "sku": _itemprop(scope, "sku"),
        "mpn": _itemprop(scope, "mpn"),
        "description": _itemprop(scope, "description"),
    }


def _meta(tree: HTMLParser, *names: str) -> str | None:
    for name in names:
        node = tree.css_first(f'meta[property="{name}"]') or tree.css_first(f'meta[name="{name}"]')
        if node is not None and node.attributes.get("content"):
            return clean_text(node.attributes["content"])
    return None


def from_meta(tree: HTMLParser) -> dict[str, Any]:
    title_node = tree.css_first("title")
    return {
        "title": _meta(tree, "og:title", "twitter:title")
        or (clean_text(title_node.text()) if title_node else None),
        "price": parse_price(_meta(tree, "product:price:amount", "og:price:amount")),
        "currency": _meta(tree, "product:price:currency", "og:price:currency"),
        "image": _meta(tree, "og:image", "twitter:image"),
        "brand": _meta(tree, "product:brand", "og:brand"),
        "description": _meta(tree, "og:description", "description"),
    }


def spec_tables(tree: HTMLParser | Node, selector: str = "table, dl") -> dict[str, str]:
    """Read 2-column spec tables and definition lists into a dict."""
    specs: dict[str, str] = {}
    for container in tree.css(selector):
        if container.tag == "dl":
            terms = container.css("dt")
            values = container.css("dd")
            for term, value in zip(terms, values):
                _add_spec(specs, term.text(deep=True), value.text(deep=True))
            continue
        for row in container.css("tr"):
            cells = row.css("th, td")
            if len(cells) == 2:
                _add_spec(specs, cells[0].text(deep=True), cells[1].text(deep=True))
    return specs


def _add_spec(specs: dict[str, str], key: str | None, value: str | None) -> None:
    key, value = clean_text(key), clean_text(value)
    if not key or not value:
        return
    key = key.strip(" :‎‏")
    value = value.strip(" ‎‏")
    if 0 < len(key) <= 60 and 0 < len(value) <= 300:
        specs.setdefault(key, value)


def merge(*sources: dict[str, Any]) -> dict[str, Any]:
    """First non-empty value wins; spec dicts are combined."""
    result: dict[str, Any] = {"specs": {}}
    for source in sources:
        for key, value in source.items():
            if key == "specs":
                for sk, sv in (value or {}).items():
                    result["specs"].setdefault(sk, sv)
            elif value not in (None, "", []) and result.get(key) in (None, "", []):
                result[key] = value
    return result


def extract_generic(html: str) -> dict[str, Any]:
    tree = HTMLParser(html)
    products = jsonld_products(tree)
    jsonld = from_jsonld(products[0]) if products else {}
    return merge(jsonld, from_microdata(tree), from_meta(tree), {"specs": spec_tables(tree)})
