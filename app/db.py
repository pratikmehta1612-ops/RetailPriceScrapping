"""SQLite storage for past searches, so results can be reopened without using search credits."""

from __future__ import annotations

import sqlite3
import threading
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
"""


class Database:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._lock = threading.Lock()

    def save(self, run: SearchRun) -> SearchRun:
        prices = [m.price for m in run.matches if m.price is not None and m.level in ("same", "strong", "good")]
        with self._lock, self._conn:
            if run.id is None:
                cur = self._conn.execute(
                    "INSERT INTO searches (created_at, title, url, match_count, best_price, demo, payload) "
                    "VALUES (?, ?, ?, ?, ?, ?, '{}')",
                    (run.created_at.isoformat(), run.reference.title, run.reference.url, len(run.matches),
                     min(prices) if prices else None, int(run.demo)),
                )
                run.id = cur.lastrowid
            self._conn.execute(
                "UPDATE searches SET payload = ?, match_count = ?, best_price = ? WHERE id = ?",
                (run.model_dump_json(), len(run.matches), min(prices) if prices else None, run.id),
            )
        return run

    def get(self, search_id: int) -> SearchRun | None:
        with self._lock:
            row = self._conn.execute("SELECT payload FROM searches WHERE id = ?", (search_id,)).fetchone()
        return SearchRun.model_validate_json(row["payload"]) if row else None

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, created_at, title, url, match_count, best_price, demo FROM searches "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) | {"demo": bool(r["demo"])} for r in rows]

    def delete(self, search_id: int) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM searches WHERE id = ?", (search_id,))
        return cur.rowcount > 0
