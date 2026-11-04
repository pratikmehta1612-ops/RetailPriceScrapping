"""Runtime settings, read from environment variables or a .env file in the project folder."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader so we don't need python-dotenv."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")

# Used when SESSION_SECRET isn't set: logins then last until the app restarts.
_RANDOM_SECRET = secrets.token_urlsafe(32)


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # Search
    serpapi_api_key: str | None = field(default_factory=lambda: os.getenv("SERPAPI_API_KEY") or None)
    search_country: str = field(default_factory=lambda: os.getenv("SEARCH_COUNTRY", "us"))
    search_language: str = field(default_factory=lambda: os.getenv("SEARCH_LANGUAGE", "en"))
    search_location: str | None = field(default_factory=lambda: os.getenv("SEARCH_LOCATION") or None)
    max_queries: int = field(default_factory=lambda: _int("MAX_QUERIES", 3))
    store_link_lookups: int = field(default_factory=lambda: _int("STORE_LINK_LOOKUPS", 10))
    min_results: int = field(default_factory=lambda: _int("MIN_RESULTS", 10))
    max_results: int = field(default_factory=lambda: _int("MAX_RESULTS", 30))

    # Optional AI matching
    anthropic_api_key: str | None = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY") or None)
    claude_model: str = field(default_factory=lambda: os.getenv("CLAUDE_MODEL", "claude-haiku-5-5"))
    use_ai: bool = field(default_factory=lambda: _bool("USE_AI", True))

    # Reading the reference page
    database_path: str = field(default_factory=lambda: os.getenv("DATABASE_PATH", str(ROOT / "data" / "searches.db")))
    user_agent: str = field(
        default_factory=lambda: os.getenv(
            "USER_AGENT",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
        )
    )
    respect_robots: bool = field(default_factory=lambda: _bool("RESPECT_ROBOTS", True))
    min_request_interval: float = field(default_factory=lambda: _float("MIN_REQUEST_INTERVAL", 1))
    request_timeout: float = field(default_factory=lambda: _float("REQUEST_TIMEOUT", 20))
    bestbuy_api_key: str | None = field(default_factory=lambda: os.getenv("BESTBUY_API_KEY") or None)

    # Login and limits
    app_users: str = field(default_factory=lambda: os.getenv("APP_USERS", ""))
    session_secret: str = field(default_factory=lambda: os.getenv("SESSION_SECRET") or _RANDOM_SECRET)
    daily_search_limit: int = field(default_factory=lambda: _int("DAILY_SEARCH_LIMIT", 15))
    # "auto" = secure cookies when the site is opened over https.
    cookie_secure: str = field(default_factory=lambda: os.getenv("COOKIE_SECURE", "auto").lower())
    # Refuse links that point at private or internal network addresses.
    block_private_addresses: bool = field(default_factory=lambda: _bool("BLOCK_PRIVATE_ADDRESSES", True))

    @property
    def secret_is_random(self) -> bool:
        return self.session_secret == _RANDOM_SECRET

    @property
    def ai_enabled(self) -> bool:
        return bool(self.anthropic_api_key) and self.use_ai


def get_settings() -> Settings:
    return Settings()
