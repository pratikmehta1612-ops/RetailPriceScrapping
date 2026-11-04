"""Google Shopping search through SerpApi (https://serpapi.com).

Two endpoints are used:
- engine=google_shopping: about 40 products per query with price and store.
- engine=google_immersive_product: the store offers for one product, with
  direct links to the retailer's page. Each call uses one search credit, so
  the app only resolves links for the top results (STORE_LINK_LOOKUPS).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
from pydantic import BaseModel, Field

from ..extract.structured import parse_price

ENDPOINT = "https://serpapi.com/search.json"


class SearchError(Exception):
    pass


class Offer(BaseModel):
    store: str
    price: float | None = None
    total: float | None = None
    link: str | None = None
    shipping: str | None = None
    condition: str | None = None


class Candidate(BaseModel):
    title: str
    price: float | None = None
    price_text: str | None = None
    currency: str = "USD"
    old_price: float | None = None
    store: str | None = None
    link: str | None = None          # direct link to the store's product page
    google_link: str | None = None   # Google Shopping page for the product
    thumbnail: str | None = None
    rating: float | None = None
    reviews: int | None = None
    delivery: str | None = None
    snippet: str | None = None
    extensions: list[str] = Field(default_factory=list)
    condition: str | None = None
    product_id: str | None = None
    page_token: str | None = None
    query: str | None = None
    offers: list[Offer] = Field(default_factory=list)

    def text(self) -> str:
        return " ".join(filter(None, [self.snippet, " ".join(self.extensions)]))


_CURRENCY = {"$": "USD", "£": "GBP", "€": "EUR", "₹": "INR", "C$": "CAD", "CA$": "CAD", "A$": "AUD"}


def _currency(price_text: str | None) -> str:
    if not price_text:
        return "USD"
    for symbol in sorted(_CURRENCY, key=len, reverse=True):
        if symbol in price_text:
            return _CURRENCY[symbol]
    return "USD"


def _token(item: dict) -> str | None:
    token = item.get("immersive_product_page_token")
    if token:
        return token
    api = item.get("serpapi_immersive_product_api")
    if api:
        values = parse_qs(urlsplit(api).query).get("page_token")
        return values[0] if values else None
    return None


def to_candidate(item: dict, query: str | None = None) -> Candidate | None:
    title = (item.get("title") or "").strip()
    if not title:
        return None
    price_text = item.get("price")
    price = item.get("extracted_price")
    if price is None:
        price = parse_price(price_text)
    old = item.get("extracted_old_price")
    if old is None and item.get("old_price"):
        old = parse_price(item.get("old_price"))
    reviews = item.get("reviews")
    try:
        reviews = int(str(reviews).replace(",", "")) if reviews is not None else None
    except ValueError:
        reviews = None
    extensions = item.get("extensions") or []
    return Candidate(
        title=title,
        price=float(price) if price is not None else None,
        price_text=price_text,
        currency=_currency(price_text),
        old_price=float(old) if old is not None else None,
        store=item.get("source") or item.get("seller"),
        link=item.get("link"),
        google_link=item.get("product_link"),
        thumbnail=item.get("thumbnail") or item.get("serpapi_thumbnail"),
        rating=item.get("rating"),
        reviews=reviews,
        delivery=item.get("delivery"),
        snippet=item.get("snippet"),
        extensions=[str(e) for e in extensions if isinstance(e, (str, int, float))],
        condition=item.get("second_hand_condition"),
        product_id=item.get("product_id"),
        page_token=_token(item),
        query=query,
    )


def candidates_from(payload: dict, query: str | None = None) -> list[Candidate]:
    items: list[dict] = list(payload.get("shopping_results") or [])
    for group in payload.get("categorized_shopping_results") or []:
        items.extend(group.get("shopping_results") or [])
    items.extend(payload.get("inline_shopping_results") or [])
    out = []
    for item in items:
        cand = to_candidate(item, query)
        if cand:
            out.append(cand)
    return out


def offers_from(payload: dict) -> list[Offer]:
    stores = (payload.get("product_results") or {}).get("stores") or []
    offers = []
    for s in stores:
        name = s.get("name")
        if not name:
            continue
        price = s.get("extracted_price")
        total = s.get("extracted_total")
        offers.append(Offer(
            store=name,
            price=float(price) if price is not None else parse_price(s.get("price")),
            total=float(total) if total is not None else None,
            link=s.get("link"),
            shipping=s.get("shipping") if isinstance(s.get("shipping"), str) else None,
            condition=s.get("tag") if isinstance(s.get("tag"), str) else None,
        ))
    return offers


class SerpApi:
    def __init__(self, api_key: str, client: httpx.AsyncClient, country: str = "us",
                 language: str = "en", location: str | None = None):
        self.api_key = api_key
        self.client = client
        self.country = country
        self.language = language
        self.location = location
        self.calls = 0

    async def _get(self, params: dict[str, Any]) -> dict:
        params = {**params, "api_key": self.api_key}
        self.calls += 1
        try:
            resp = await self.client.get(ENDPOINT, params=params, timeout=60)
        except httpx.HTTPError as exc:
            raise SearchError(f"Couldn't reach SerpApi: {exc}") from exc
        try:
            data = resp.json()
        except json.JSONDecodeError as exc:
            raise SearchError(f"SerpApi returned HTTP {resp.status_code}.") from exc
        error = data.get("error")
        if error and "hasn't returned any results" not in error:
            raise SearchError(f"SerpApi: {error}")
        if resp.status_code >= 400 and not error:
            raise SearchError(f"SerpApi returned HTTP {resp.status_code}.")
        return data

    async def shopping(self, query: str) -> list[Candidate]:
        params = {"engine": "google_shopping", "q": query, "gl": self.country, "hl": self.language}
        if self.location:
            params["location"] = self.location
        return candidates_from(await self._get(params), query)

    async def offers(self, page_token: str) -> list[Offer]:
        data = await self._get({"engine": "google_immersive_product", "page_token": page_token, "more_stores": "true"})
        return offers_from(data)


class DemoSerpApi:
    """Serves saved sample responses so the app can be tried without an API key."""

    def __init__(self, folder: Path):
        self.folder = folder
        self.calls = 0

    async def shopping(self, query: str) -> list[Candidate]:
        self.calls += 1
        data = json.loads((self.folder / "demo_shopping.json").read_text(encoding="utf-8"))
        return candidates_from(data, query)

    async def offers(self, page_token: str) -> list[Offer]:
        self.calls += 1
        data = json.loads((self.folder / "demo_offers.json").read_text(encoding="utf-8"))
        payload = data.get(page_token) or data.get("default") or {}
        return offers_from(payload)
