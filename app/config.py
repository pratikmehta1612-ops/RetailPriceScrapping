"""Runtime settings, read from environment variables (or a .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


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


_load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_path: str = field(default_factory=lambda: os.getenv("DATABASE_PATH", "data/prices.db"))
    user_agent: str = field(
        default_factory=lambda: os.getenv(
            "USER_AGENT",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/130.0 Safari/537.36 RetailPriceScrapping/0.1",
        )
    )
    respect_robots: bool = field(default_factory=lambda: _bool("RESPECT_ROBOTS", True))
    # Minimum seconds between two requests to the same domain.
    min_request_interval: float = field(
        default_factory=lambda: float(os.getenv("MIN_REQUEST_INTERVAL", "3"))
    )
    request_timeout: float = field(default_factory=lambda: float(os.getenv("REQUEST_TIMEOUT", "20")))
    # 0 disables the background refresh loop.
    refresh_interval_hours: float = field(
        default_factory=lambda: float(os.getenv("REFRESH_INTERVAL_HOURS", "0"))
    )
    bestbuy_api_key: str | None = field(default_factory=lambda: os.getenv("BESTBUY_API_KEY") or None)


def get_settings() -> Settings:
    return Settings()
