"""SQLite storage for past searches. Each user only sees their own."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .finder import SearchRun

SCHEMA = """
CREATE TABLE IF NOT EXISTS searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT,
    match_count INTEGER NOT NULL,
    best_price REAL,
    demo INTEGER NOT NULL DEFAULT 0,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_owner ON usage(owner, created_at);
"""


class Database:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        columns = {r["name"] for r in self._conn.execute("PRAGMA table_info(searches)")}
        if "owner" not in columns:  # databases from the earlier version
            self._conn.execute("ALTER TABLE searches ADD COLUMN owner TEXT NOT NULL DEFAULT ''")
        if "credits" not in columns:
            self._conn.execute("ALTER TABLE searches ADD COLUMN credits INTEGER NOT NULL DEFAULT 0")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_searches_owner ON searches(owner, id)")
        self._conn.commit()
        self._lock = threading.Lock()

    def save(self, run: SearchRun, owner: str) -> SearchRun:
        prices = [m.price for m in run.matches if m.price is not None and m.level in ("same", "strong", "good")]
        best = min(prices) if prices else None
        with self._lock, self._conn:
            if run.id is None:
                cur = self._conn.execute(
                    "INSERT INTO searches (created_at, title, url, match_count, best_price, demo, payload, owner, credits) "
                    "VALUES (?, ?, ?, ?, ?, ?, '{}', ?, ?)",
                    (run.created_at.isoformat(), run.reference.title, run.reference.url, len(run.matches),
                     best, int(run.demo), owner, 0 if run.demo else run.searches_used),
                )
                run.id = cur.lastrowid
            self._conn.execute(
                "UPDATE searches SET payload = ?, match_count = ?, best_price = ? WHERE id = ? AND owner = ?",
                (run.model_dump_json(), len(run.matches), best, run.id, owner),
            )
        return run

    def add_credits(self, search_id: int, owner: str, credits: int) -> None:
        with self._lock, self._conn:
            self._conn.execute("UPDATE searches SET credits = credits + ? WHERE id = ? AND owner = ?",
                               (credits, search_id, owner))

    def get(self, search_id: int, owner: str) -> SearchRun | None:
        with self._lock:
            row = self._conn.execute("SELECT payload FROM searches WHERE id = ? AND owner = ?",
                                     (search_id, owner)).fetchone()
        return SearchRun.model_validate_json(row["payload"]) if row else None

    def list(self, owner: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, created_at, title, url, match_count, best_price, demo FROM searches "
                "WHERE owner = ? ORDER BY id DESC LIMIT ?",
                (owner, limit),
            ).fetchall()
        return [dict(r) | {"demo": bool(r["demo"])} for r in rows]

    def delete(self, search_id: int, owner: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM searches WHERE id = ? AND owner = ?", (search_id, owner))
        return cur.rowcount > 0

    def record_search(self, owner: str) -> None:
        """Counted separately from saved searches, so deleting one doesn't reset the limit."""
        with self._lock, self._conn:
            self._conn.execute("INSERT INTO usage (owner, created_at) VALUES (?, ?)",
                               (owner, datetime.now(timezone.utc).isoformat()))

    def searches_today(self, owner: str) -> int:
        """Real (non-demo) product searches this user ran in the last 24 hours."""
        since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS n FROM usage WHERE owner = ? AND created_at >= ?",
                                     (owner, since)).fetchone()
        return int(row["n"])
