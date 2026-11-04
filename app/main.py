"""FastAPI app: JSON API under /api and the web page at /."""

from __future__ import annotations

from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .ai import Claude
from .config import Settings, get_settings
from .db import Database
from .fetcher import Fetcher
from .finder import Match, SearchRun, find_similar, resolve_store_link
from .reference import read_reference
from .search.serpapi import DemoSerpApi, SearchError, SerpApi

STATIC = Path(__file__).parent / "static"
DEMO = Path(__file__).parent / "demo"
DEMO_URL = (
    "https://www.overtons.com/husky-round-bar-weight-distribution-hitch-with-sway-control-"
    "12k-2-516-ball-no-shank-146894.html"
)


class FindRequest(BaseModel):
    url: str | None = None
    details: str | None = None
    use_ai: bool = True
    demo: bool = False


def create_app(settings: Settings | None = None, db: Database | None = None,
               transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    """`transport` lets tests replace the network (SerpApi, Claude, store pages)."""
    settings = settings or get_settings()
    database = db or Database(settings.database_path)
    app = FastAPI(title="RetailPriceScrapping", version="0.2.0")

    def http_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=transport, follow_redirects=True, timeout=60)

    def searcher(client: httpx.AsyncClient, demo: bool):
        if demo:
            return DemoSerpApi(DEMO)
        if not settings.serpapi_api_key:
            raise HTTPException(400, "No SerpApi key yet. Add SERPAPI_API_KEY to the .env file, or try the demo.")
        return SerpApi(settings.serpapi_api_key, client, settings.search_country,
                       settings.search_language, settings.search_location)

    @app.get("/api/status")
    def status():
        return {
            "search_ready": bool(settings.serpapi_api_key),
            "ai_ready": settings.ai_enabled,
            "ai_model": settings.claude_model if settings.ai_enabled else None,
            "max_queries": settings.max_queries,
            "store_link_lookups": settings.store_link_lookups,
            "min_results": settings.min_results,
            "country": settings.search_country,
        }

    @app.post("/api/find", response_model=SearchRun)
    async def find(body: FindRequest):
        demo = body.demo
        async with http_client() as client:
            search = searcher(client, demo)
            try:
                if demo:
                    reference = await read_reference(body.url or DEMO_URL, body.details, None)
                    reference.notes.insert(0, "Demo mode: sample products with made-up stores and prices.")
                else:
                    page_client = http_client() if transport is not None else None
                    async with Fetcher(settings, client=page_client) as fetcher:
                        reference = await read_reference(body.url, body.details, fetcher)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc

            claude = None
            if body.use_ai and settings.ai_enabled and not demo:
                claude = Claude(settings.anthropic_api_key, settings.claude_model, client)
            try:
                run = await find_similar(reference, search, settings, claude=claude, demo=demo)
            except SearchError as exc:
                raise HTTPException(502, str(exc)) from exc
        return database.save(run)

    @app.get("/api/searches")
    def searches():
        return database.list()

    @app.get("/api/searches/{search_id}", response_model=SearchRun)
    def get_search(search_id: int):
        run = database.get(search_id)
        if run is None:
            raise HTTPException(404, "Search not found")
        return run

    @app.delete("/api/searches/{search_id}", status_code=204)
    def delete_search(search_id: int):
        if not database.delete(search_id):
            raise HTTPException(404, "Search not found")

    @app.post("/api/searches/{search_id}/matches/{match_id}/store-link", response_model=Match)
    async def store_link(search_id: int, match_id: int):
        """Look up the direct store link (and other stores' prices) for one result. Uses 1 search."""
        run = get_search(search_id)
        match = next((m for m in run.matches if m.id == match_id), None)
        if match is None:
            raise HTTPException(404, "Result not found")
        if not match.page_token:
            raise HTTPException(422, "Google didn't provide store details for this product.")
        async with http_client() as client:
            try:
                await resolve_store_link(match, searcher(client, run.demo))
            except SearchError as exc:
                raise HTTPException(502, str(exc)) from exc
        database.save(run)
        return match

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


app = create_app()
