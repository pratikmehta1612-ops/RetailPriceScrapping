"""FastAPI app: login, JSON API under /api, and the web pages.

Every page and API call needs a signed-in user except the login page itself
and /healthz. API keys stay on the server: the browser only ever learns
whether search and AI are configured, never the keys.
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .ai import Claude
from .auth import (
    SESSION_COOKIE, SESSION_DAYS, LoginGuard, check_login, make_session, parse_users,
    password_version, read_session,
)
from .config import Settings, get_settings
from .db import Database
from .fetcher import Fetcher
from .finder import Match, SearchRun, find_similar, resolve_store_link
from .reference import read_reference
from .search.serpapi import DemoSerpApi, SearchError, SerpApi

log = logging.getLogger("retailprice")
# httpx logs full request URLs at INFO level, and SerpApi URLs carry the API key.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

STATIC = Path(__file__).parent / "static"
DEMO = Path(__file__).parent / "demo"
DEMO_URL = (
    "https://www.overtons.com/husky-round-bar-weight-distribution-hitch-with-sway-control-"
    "12k-2-516-ball-no-shank-146894.html"
)
PUBLIC_PATHS = {"/login", "/api/login", "/api/login-info", "/healthz", "/favicon.svg",
                "/static/login.js", "/static/base.css"}
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' https: data:; script-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    ),
}


class FindRequest(BaseModel):
    url: str | None = Field(default=None, max_length=2048)
    details: str | None = Field(default=None, max_length=4000)
    use_ai: bool = True
    demo: bool = False


class LoginRequest(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=200)


def create_app(settings: Settings | None = None, db: Database | None = None,
               transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    """`transport` lets tests replace the network (SerpApi, Claude, store pages)."""
    settings = settings or get_settings()
    database = db or Database(settings.database_path)
    users = parse_users(settings.app_users)
    guard = LoginGuard()
    app = FastAPI(title="RetailPriceScrapping", version="0.3.0", docs_url=None, redoc_url=None, openapi_url=None)

    if not users:
        log.warning("No users configured. Add one with: python -m scripts.manage_users add <name>")
    if settings.secret_is_random:
        log.warning("SESSION_SECRET is not set; everyone is signed out when the app restarts.")

    # ---------------------------------------------------------------- auth plumbing

    def current_user(request: Request) -> str | None:
        data = read_session(request.cookies.get(SESSION_COOKIE), settings.session_secret)
        if not data:
            return None
        name = data.get("u")
        stored = users.get(name or "")
        if not stored or data.get("v") != password_version(stored):
            return None  # user removed or password changed
        return name

    def is_https(request: Request) -> bool:
        if settings.cookie_secure in ("true", "1", "yes"):
            return True
        if settings.cookie_secure in ("false", "0", "no"):
            return False
        return request.url.scheme == "https"

    def same_origin(request: Request) -> bool:
        origin = request.headers.get("origin")
        if not origin:
            return True  # same-origin fetches from older browsers, curl, tests
        host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
        return urlsplit(origin).netloc == host

    @app.middleware("http")
    async def protect(request: Request, call_next):
        path = request.url.path
        if request.method not in ("GET", "HEAD", "OPTIONS") and not same_origin(request):
            response: Response = JSONResponse({"detail": "Cross-site request blocked."}, status_code=403)
        elif path in PUBLIC_PATHS:
            response = await call_next(request)
        else:
            user = current_user(request)
            if user is None:
                if path.startswith("/api/"):
                    response = JSONResponse({"detail": "Please sign in."}, status_code=401)
                else:
                    target = "/login" + (f"?next={quote(path)}" if path not in ("/", "") else "")
                    response = RedirectResponse(target, status_code=303)
            else:
                request.state.user = user
                response = await call_next(request)
        for key, value in SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def user_of(request: Request) -> str:
        return request.state.user

    # ---------------------------------------------------------------- login

    @app.get("/login", include_in_schema=False)
    def login_page(request: Request):
        if current_user(request):
            return RedirectResponse("/", status_code=303)
        return FileResponse(STATIC / "login.html")

    @app.get("/api/login-info")
    def login_info():
        return {"users_configured": bool(users)}

    @app.post("/api/login")
    def login(body: LoginRequest, request: Request):
        name = body.username.strip().lower()
        ip = request.client.host if request.client else "unknown"
        keys = (f"ip:{ip}", f"user:{name}")
        wait = guard.locked(*keys)
        if wait:
            minutes = max(1, round(wait / 60))
            raise HTTPException(429, f"Too many failed attempts. Try again in about {minutes} minute{'s' if minutes > 1 else ''}.")
        if not users:
            raise HTTPException(503, "No users are set up yet. Run: python -m scripts.manage_users add <name>")
        if not check_login(users, name, body.password):
            guard.fail(*keys)
            raise HTTPException(401, "Wrong username or password.")
        guard.clear(*keys)
        response = JSONResponse({"username": name})
        response.set_cookie(
            SESSION_COOKIE, make_session(name, settings.session_secret, version=password_version(users[name])),
            max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax", secure=is_https(request), path="/",
        )
        return response

    @app.post("/api/logout")
    def logout():
        response = JSONResponse({"ok": True})
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"ok": True}

    # ---------------------------------------------------------------- search

    def http_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=transport, follow_redirects=True, timeout=60)

    def searcher(client: httpx.AsyncClient, demo: bool):
        if demo:
            return DemoSerpApi(DEMO)
        if not settings.serpapi_api_key:
            raise HTTPException(400, "Searching isn't set up yet: the server has no SerpApi key. Try the demo meanwhile.")
        return SerpApi(settings.serpapi_api_key, client, settings.search_country,
                       settings.search_language, settings.search_location)

    @app.get("/api/status")
    def status(request: Request):
        user = user_of(request)
        return {
            "user": user,
            "search_ready": bool(settings.serpapi_api_key),
            "ai_ready": settings.ai_enabled,
            "searches_today": database.searches_today(user),
            "daily_limit": settings.daily_search_limit,
            "max_queries": settings.max_queries,
            "store_link_lookups": settings.store_link_lookups,
            "min_results": settings.min_results,
            "country": settings.search_country,
        }

    @app.post("/api/find", response_model=SearchRun)
    async def find(body: FindRequest, request: Request):
        user = user_of(request)
        demo = body.demo
        if not demo:
            limit = settings.daily_search_limit
            if limit > 0 and database.searches_today(user) >= limit:
                raise HTTPException(429, f"You've reached today's limit of {limit} searches. It resets 24 hours after each search.")
        async with http_client() as client:
            search = searcher(client, demo)
            if not demo:
                database.record_search(user)
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
        return database.save(run, user)

    @app.get("/api/searches")
    def searches(request: Request):
        return database.list(user_of(request))

    def owned_search(search_id: int, request: Request) -> SearchRun:
        run = database.get(search_id, user_of(request))
        if run is None:
            raise HTTPException(404, "Search not found")
        return run

    @app.get("/api/searches/{search_id}", response_model=SearchRun)
    def get_search(search_id: int, request: Request):
        return owned_search(search_id, request)

    @app.delete("/api/searches/{search_id}", status_code=204)
    def delete_search(search_id: int, request: Request):
        if not database.delete(search_id, user_of(request)):
            raise HTTPException(404, "Search not found")

    @app.post("/api/searches/{search_id}/matches/{match_id}/store-link", response_model=Match)
    async def store_link(search_id: int, match_id: int, request: Request):
        """Look up the direct store link (and other stores' prices) for one result. Uses 1 search."""
        user = user_of(request)
        run = owned_search(search_id, request)
        match = next((m for m in run.matches if m.id == match_id), None)
        if match is None:
            raise HTTPException(404, "Result not found")
        if match.link:
            return match
        if not match.page_token:
            raise HTTPException(422, "Google didn't provide store details for this product.")
        async with http_client() as client:
            try:
                await resolve_store_link(match, searcher(client, run.demo))
            except SearchError as exc:
                raise HTTPException(502, str(exc)) from exc
        database.save(run, user)
        if not run.demo:
            database.add_credits(search_id, user, 1)
        return match

    # ---------------------------------------------------------------- pages

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/favicon.svg", include_in_schema=False)
    def favicon():
        return FileResponse(STATIC / "favicon.svg", media_type="image/svg+xml")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


app = create_app()
