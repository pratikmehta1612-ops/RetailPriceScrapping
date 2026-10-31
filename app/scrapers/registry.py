"""Pick the right adapter for a URL and run it."""

from __future__ import annotations

from typing import Callable
from urllib.parse import urlsplit

from ..config import get_settings
from ..fetcher import Fetcher
from ..models import ScrapedProduct
from . import retailers
from .base import generic

Parser = Callable[[str, str], ScrapedProduct]

_DOMAINS: dict[str, tuple[str, Parser]] = {
    "amazon.": ("amazon", retailers.parse_amazon),
    "walmart.com": ("walmart", retailers.parse_walmart),
    "target.com": ("target", retailers.parse_target),
    "bestbuy.com": ("bestbuy", retailers.parse_bestbuy),
}

BESTBUY_FIELDS = (
    "sku,name,salePrice,regularPrice,manufacturer,modelNumber,upc,image,url,"
    "longDescription,shortDescription,onlineAvailability,details.name,details.value"
)


def retailer_for(url: str) -> tuple[str, Parser]:
    host = urlsplit(url).netloc.lower()
    for marker, entry in _DOMAINS.items():
        if marker in host:
            return entry
    name = host.removeprefix("www.").split(":")[0] or "other"
    return name, lambda u, h: generic(u, h, name)


def scrape_html(url: str, html: str) -> ScrapedProduct:
    """Parse already-downloaded HTML (used for manual imports and tests)."""
    _, parser = retailer_for(url)
    return parser(url, html)


async def scrape_url(url: str, fetcher: Fetcher) -> ScrapedProduct:
    retailer, parser = retailer_for(url)
    settings = get_settings()
    if retailer == "bestbuy" and settings.bestbuy_api_key:
        sku = retailers.bestbuy_sku(url)
        if sku:
            data = await fetcher.get_json(
                f"https://api.bestbuy.com/v1/products(sku={sku})",
                params={"apiKey": settings.bestbuy_api_key, "format": "json", "show": BESTBUY_FIELDS},
            )
            items = data.get("products") or []
            if items:
                return retailers.bestbuy_from_api(url, items[0])
    html = await fetcher.get_text(url)
    return parser(url, html)
