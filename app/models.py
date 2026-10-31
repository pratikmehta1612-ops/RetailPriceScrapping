"""Data shapes shared by scrapers, storage and the API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ScrapedProduct(BaseModel):
    """What a scraper returns for one product page."""

    url: str
    retailer: str
    title: str
    price: float | None = None
    currency: str = "USD"
    availability: str | None = None
    brand: str | None = None
    image: str | None = None
    sku: str | None = None
    mpn: str | None = None
    gtin: str | None = None
    description: str | None = None
    category_hint: str | None = None
    # Raw spec table rows as shown on the page ("Viscosity" -> "5W-30").
    specs: dict[str, str] = Field(default_factory=dict)


class PricePoint(BaseModel):
    price: float | None
    currency: str
    availability: str | None
    scraped_at: datetime


class Product(BaseModel):
    """A stored product with normalized features."""

    id: int
    url: str
    retailer: str
    title: str
    brand: str | None
    image: str | None
    sku: str | None
    mpn: str | None
    category: str
    features: dict[str, Any]
    specs: dict[str, str]
    price: float | None
    currency: str
    availability: str | None
    unit_price: float | None = None
    unit_label: str | None = None
    updated_at: datetime


class FeatureComparison(BaseModel):
    feature: str
    a: Any
    b: Any
    match: bool


class SimilarProduct(BaseModel):
    product: Product
    score: float
    price_difference: float | None
    comparisons: list[FeatureComparison]
