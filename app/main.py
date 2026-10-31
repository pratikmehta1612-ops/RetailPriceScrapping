"""FastAPI app: JSON API under /api and the dashboard at /."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl

from . import service
from .config import Settings, get_settings
from .db import Database
from .fetcher import BlockedError, FetchError, Fetcher
from .models import PricePoint, Product, SimilarProduct

log = logging.getLogger("retailprice")
STATIC = Path(__file__).parent / "static"


class AddProduct(BaseModel):
    url: HttpUrl


class ImportHtml(BaseModel):
    url: HttpUrl
    html: str = Field(min_length=200, description="Full HTML of the product page (File > Save Page As).")


def create_app(settings: Settings | None = None, db: Database | None = None) -> FastAPI:
    settings = settings or get_settings()
    database = db or Database(settings.database_path)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        task = None
        if settings.refresh_interval_hours > 0:
            task = asyncio.create_task(_refresh_loop(database, settings))
        yield
        if task:
            task.cancel()

    app = FastAPI(title="RetailPriceScrapping", version="0.1.0", lifespan=lifespan)
    app.state.db = database
    app.state.settings = settings

    def fetch_error(exc: Exception) -> HTTPException:
        if isinstance(exc, BlockedError):
            return HTTPException(
                status_code=422,
                detail=f"{exc} Save the page from your browser and use 'Import HTML' instead.",
            )
        return HTTPException(status_code=422, detail=str(exc))

    @app.get("/api/products", response_model=list[Product])
    def list_products(category: str | None = None, q: str | None = None):
        return database.list_products(category=category, query=q)

    @app.post("/api/products", response_model=Product, status_code=201)
    async def add_product(body: AddProduct):
        try:
            async with Fetcher(settings) as fetcher:
                return await service.add_from_url(database, str(body.url), fetcher)
        except (FetchError, ValueError) as exc:
            raise fetch_error(exc) from exc

    @app.post("/api/products/import", response_model=Product, status_code=201)
    def import_html(body: ImportHtml):
        try:
            return service.add_from_html(database, str(body.url), body.html)
        except ValueError as exc:
            raise fetch_error(exc) from exc

    @app.get("/api/products/{product_id}", response_model=Product)
    def get_product(product_id: int):
        product = database.get_product(product_id)
        if product is None:
            raise HTTPException(404, "Product not found")
        return product

    @app.delete("/api/products/{product_id}", status_code=204)
    def delete_product(product_id: int):
        if not database.delete_product(product_id):
            raise HTTPException(404, "Product not found")

    @app.post("/api/products/{product_id}/refresh", response_model=Product)
    async def refresh_product(product_id: int):
        product = get_product(product_id)
        try:
            async with Fetcher(settings) as fetcher:
                return await service.add_from_url(database, product.url, fetcher)
        except (FetchError, ValueError) as exc:
            raise fetch_error(exc) from exc

    @app.post("/api/refresh")
    async def refresh_all():
        async with Fetcher(settings) as fetcher:
            return await service.refresh_all(database, fetcher)

    @app.get("/api/products/{product_id}/history", response_model=list[PricePoint])
    def history(product_id: int):
        get_product(product_id)
        return database.price_history(product_id)

    @app.get("/api/products/{product_id}/similar", response_model=list[SimilarProduct])
    def similar(product_id: int, min_score: float = Query(0.4, ge=0, le=1)):
        return service.find_similar(database, get_product(product_id), min_score=min_score)

    @app.get("/api/categories")
    def categories():
        return database.categories()

    @app.get("/api/search")
    async def search(q: str = Query(min_length=2)):
        """Find candidate products to add. Uses the Best Buy Products API when a key is set."""
        if not settings.bestbuy_api_key:
            return {"source": None, "results": [], "note": "Set BESTBUY_API_KEY to enable search."}
        terms = "&".join(f"search={t}" for t in q.split() if t.isalnum())
        if not terms:
            return {"source": "bestbuy", "results": []}
        async with Fetcher(settings) as fetcher:
            try:
                data = await fetcher.get_json(
                    f"https://api.bestbuy.com/v1/products({terms})",
                    params={
                        "apiKey": settings.bestbuy_api_key,
                        "format": "json",
                        "pageSize": 20,
                        "show": "sku,name,salePrice,url,image,manufacturer",
                    },
                )
            except FetchError as exc:
                raise fetch_error(exc) from exc
        return {"source": "bestbuy", "results": data.get("products", [])}

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


async def _refresh_loop(db: Database, settings: Settings) -> None:
    while True:
        await asyncio.sleep(settings.refresh_interval_hours * 3600)
        try:
            async with Fetcher(settings) as fetcher:
                result = await service.refresh_all(db, fetcher)
            log.info("Scheduled refresh: %d ok, %d failed", len(result["refreshed"]), len(result["failed"]))
        except Exception:  # keep the loop alive
            log.exception("Scheduled refresh crashed")


app = create_app()
