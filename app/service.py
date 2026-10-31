"""Glue between scrapers, feature extraction, storage and matching."""

from __future__ import annotations

import logging

from .db import Database
from .extract.automotive import extract_features
from .fetcher import FetchError, Fetcher
from .matching import similarity
from .models import Product, ScrapedProduct, SimilarProduct
from .scrapers import scrape_html, scrape_url

log = logging.getLogger(__name__)


def store(db: Database, scraped: ScrapedProduct) -> Product:
    category, features = extract_features(
        scraped.title,
        scraped.description,
        scraped.specs,
        brand=scraped.brand,
        category_hint=scraped.category_hint,
    )
    if scraped.gtin:
        features["gtin"] = scraped.gtin
    if scraped.mpn and "part_number" not in features:
        features["part_number"] = scraped.mpn.upper()
    product_id = db.upsert_product(
        url=scraped.url,
        retailer=scraped.retailer,
        title=scraped.title,
        brand=scraped.brand,
        image=scraped.image,
        sku=scraped.sku,
        mpn=scraped.mpn,
        gtin=scraped.gtin,
        category=category,
        features=features,
        specs=scraped.specs,
    )
    db.add_price(product_id, scraped.price, scraped.currency, scraped.availability)
    product = db.get_product(product_id)
    assert product is not None
    return product


async def add_from_url(db: Database, url: str, fetcher: Fetcher) -> Product:
    scraped = await scrape_url(url, fetcher)
    return store(db, scraped)


def add_from_html(db: Database, url: str, html: str) -> Product:
    return store(db, scrape_html(url, html))


async def refresh_all(db: Database, fetcher: Fetcher) -> dict[str, list]:
    ok, failed = [], []
    for product in db.list_products():
        try:
            await add_from_url(db, product.url, fetcher)
            ok.append(product.id)
        except (FetchError, ValueError) as exc:
            log.warning("Refresh failed for %s: %s", product.url, exc)
            failed.append({"id": product.id, "url": product.url, "error": str(exc)})
    return {"refreshed": ok, "failed": failed}


def find_similar(db: Database, product: Product, min_score: float = 0.4, limit: int = 25) -> list[SimilarProduct]:
    results: list[SimilarProduct] = []
    for other in db.list_products(category=product.category):
        if other.id == product.id:
            continue
        score, comparisons = similarity(
            product.category, product.features, product.title,
            other.category, other.features, other.title,
        )
        if score < min_score:
            continue
        diff = None
        if product.unit_price is not None and other.unit_price is not None and product.unit_label == other.unit_label:
            diff = round(other.unit_price - product.unit_price, 2)
        elif product.price is not None and other.price is not None:
            diff = round(other.price - product.price, 2)
        results.append(SimilarProduct(product=other, score=score, price_difference=diff, comparisons=comparisons))
    results.sort(key=lambda r: (-r.score, r.product.unit_price or r.product.price or float("inf")))
    return results[:limit]
