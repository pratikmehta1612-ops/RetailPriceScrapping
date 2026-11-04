"""Polite HTTP fetching: robots.txt, per-domain rate limiting, retries, block detection.

This module never tries to get around CAPTCHAs or bot protection. If a site blocks
the request we raise BlockedError so the user can import the page HTML manually
or use an official API instead.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from .config import Settings, get_settings


class FetchError(Exception):
    """The page could not be downloaded."""


class BlockedError(FetchError):
    """The site refused automated access (robots.txt, CAPTCHA, 403...)."""


_BLOCK_MARKERS = (
    "captcha",
    "robot check",
    "are you a robot",
    "px-captcha",
    "access denied",
    "request blocked",
    "verify you are a human",
)


def _is_public_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


async def ensure_public_host(host: str, port: int | None = None) -> None:
    """Refuse hosts that are, or resolve to, private/internal addresses.

    Stops a visitor from using the hosted app to reach the server's own network
    (cloud metadata services, databases, admin panels...).
    """
    host = (host or "").strip("[]").lower()
    if not host or host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise BlockedError("That link points to a private or internal address, so it can't be opened.")
    try:
        if not _is_public_ip(host):
            raise BlockedError("That link points to a private or internal address, so it can't be opened.")
        return
    except ValueError:
        pass  # not an IP literal; resolve the name below
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise FetchError(f"Couldn't find the website {host}.") from exc
    if not infos or not all(_is_public_ip(info[4][0]) for info in infos):
        raise BlockedError("That link points to a private or internal address, so it can't be opened.")


async def _guard_request(request: httpx.Request) -> None:
    if request.url.scheme not in ("http", "https"):
        raise BlockedError("Only http and https links can be opened.")
    await ensure_public_host(request.url.host, request.url.port)


class Fetcher:
    def __init__(self, settings: Settings | None = None, client: httpx.AsyncClient | None = None):
        self.settings = settings or get_settings()
        self._client = client
        self._robots: dict[str, RobotFileParser | None] = {}
        self._last_hit: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def __aenter__(self) -> "Fetcher":
        if self._client is None:
            self._client = httpx.AsyncClient(
                follow_redirects=True,
                max_redirects=5,
                timeout=self.settings.request_timeout,
                headers={
                    "User-Agent": self.settings.user_agent,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
        if self.settings.block_private_addresses:
            # Runs before every request, including each redirect hop.
            hooks = dict(self._client.event_hooks)
            hooks["request"] = list(hooks.get("request", [])) + [_guard_request]
            self._client.event_hooks = hooks
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("Use Fetcher inside 'async with'.")
        return self._client

    async def _allowed(self, url: str) -> bool:
        if not self.settings.respect_robots:
            return True
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser: RobotFileParser | None = RobotFileParser()
            try:
                resp = await self.client.get(f"{origin}/robots.txt")
                if resp.status_code >= 400:
                    parser = None  # no robots.txt -> everything allowed
                else:
                    parser.parse(resp.text.splitlines())
            except httpx.HTTPError:
                parser = None
            self._robots[origin] = parser
        parser = self._robots[origin]
        return True if parser is None else parser.can_fetch(self.settings.user_agent, url)

    async def _throttle(self, domain: str) -> None:
        lock = self._locks.setdefault(domain, asyncio.Lock())
        async with lock:
            wait = self._last_hit.get(domain, 0) + self.settings.min_request_interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_hit[domain] = time.monotonic()

    async def get_text(self, url: str, *, check_robots: bool = True, retries: int = 2) -> str:
        if check_robots and not await self._allowed(url):
            raise BlockedError(f"robots.txt for {urlsplit(url).netloc} disallows this page.")
        domain = urlsplit(url).netloc
        delay = 2.0
        for attempt in range(retries + 1):
            await self._throttle(domain)
            try:
                resp = await self.client.get(url)
            except httpx.HTTPError as exc:
                if attempt == retries:
                    raise FetchError(f"Could not reach {domain}: {exc}") from exc
            else:
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                if resp.status_code in (401, 403):
                    raise BlockedError(f"{domain} refused the request (HTTP {resp.status_code}).")
                if resp.status_code >= 400:
                    raise FetchError(f"{domain} returned HTTP {resp.status_code}.")
                text = resp.text
                if looks_blocked(text):
                    raise BlockedError(f"{domain} served a bot check instead of the product page.")
                return text
            await asyncio.sleep(delay)
            delay *= 2
        raise FetchError(f"Could not fetch {url}")

    async def get_json(self, url: str, params: dict | None = None) -> dict:
        domain = urlsplit(url).netloc
        await self._throttle(domain)
        try:
            resp = await self.client.get(url, params=params, headers={"Accept": "application/json"})
        except httpx.HTTPError as exc:
            raise FetchError(f"Could not reach {domain}: {exc}") from exc
        if resp.status_code >= 400:
            raise FetchError(f"{domain} API returned HTTP {resp.status_code}.")
        return resp.json()


def looks_blocked(html: str) -> bool:
    """Heuristic: a short page mentioning a bot check is a block page, not a product."""
    head = html[:20000].lower()
    if len(html) > 150_000:
        return False  # real product pages are big; markers may appear in scripts
    return any(marker in head for marker in _BLOCK_MARKERS)
