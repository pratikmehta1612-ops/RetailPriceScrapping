"""SQLite storage: products and their price history."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .extract.automotive import unit_price
from .models import PricePoint, Product

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    retailer TEXT NOT NULL,
    title TEXT NOT NULL,
    brand TEXT,
    image TEXT,
    sku TEXT,
    mpn TEXT,
    gtin TEXT,
    category TEXT NOT NULL,
    features TEXT NOT NULL DEFAULT '{}',
    specs TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    price REAL,
    currency TEXT NOT NULL DEFAULT 'USD',
    availability TEXT,
    scraped_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_prices_product ON prices(product_id, scraped_at);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)
        self._lock = threading.Lock()

    def close(self) -> None:
        self._conn.close()

    # ---------------------------------------------------------------- writes

    def upsert_product(
        self,
        *,
        url: str,
        retailer: str,
        title: str,
        brand: str | None,
        image: str | None,
        sku: str | None,
        mpn: str | None,
        gtin: str | None,
        category: str,
        features: dict[str, Any],
        specs: dict[str, str],
    ) -> int:
        now = _now()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO products (url, retailer, title, brand, image, sku, mpn, gtin, category,
                                      features, specs, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    retailer=excluded.retailer, title=excluded.title, brand=excluded.brand,
                    image=excluded.image, sku=excluded.sku, mpn=excluded.mpn, gtin=excluded.gtin,
                    category=excluded.category, features=excluded.features, specs=excluded.specs,
                    updated_at=excluded.updated_at
                """,
                (url, retailer, title, brand, image, sku, mpn, gtin, category,
                 json.dumps(features), json.dumps(specs), now, now),
            )
            row = self._conn.execute("SELECT id FROM products WHERE url = ?", (url,)).fetchone()
        return int(row["id"])

    def add_price(self, product_id: int, price: float | None, currency: str, availability: str | None) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO prices (product_id, price, currency, availability, scraped_at) VALUES (?, ?, ?, ?, ?)",
                (product_id, price, currency, availability, _now()),
            )

    def delete_product(self, product_id: int) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
        return cur.rowcount > 0

    # ---------------------------------------------------------------- reads

    _SELECT = """
        SELECT p.*, lp.price, lp.currency, lp.availability
        FROM products p
        LEFT JOIN prices lp ON lp.id = (
            SELECT id FROM prices WHERE product_id = p.id ORDER BY scraped_at DESC, id DESC LIMIT 1
        )
    """

    def _row_to_product(self, row: sqlite3.Row) -> Product:
        features = json.loads(row["features"])
        if row["gtin"]:
            features.setdefault("gtin", row["gtin"])
        per_unit, unit = unit_price(row["category"], features, row["price"])
        return Product(
            id=row["id"],
            url=row["url"],
            retailer=row["retailer"],
            title=row["title"],
            brand=row["brand"],
            image=row["image"],
            sku=row["sku"],
            mpn=row["mpn"],
            category=row["category"],
            features=features,
            specs=json.loads(row["specs"]),
            price=row["price"],
            currency=row["currency"] or "USD",
            availability=row["availability"],
            unit_price=per_unit,
            unit_label=unit,
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def get_product(self, product_id: int) -> Product | None:
        with self._lock:
            row = self._conn.execute(self._SELECT + " WHERE p.id = ?", (product_id,)).fetchone()
        return self._row_to_product(row) if row else None

    def list_products(self, category: str | None = None, query: str | None = None) -> list[Product]:
        sql, params = self._SELECT + " WHERE 1=1", []
        if category:
            sql += " AND p.category = ?"
            params.append(category)
        if query:
            sql += " AND (p.title LIKE ? OR p.brand LIKE ?)"
            params += [f"%{query}%", f"%{query}%"]
        sql += " ORDER BY p.category, p.title"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_product(r) for r in rows]

    def price_history(self, product_id: int) -> list[PricePoint]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT price, currency, availability, scraped_at FROM prices "
                "WHERE product_id = ? ORDER BY scraped_at, id",
                (product_id,),
            ).fetchall()
        return [
            PricePoint(
                price=r["price"],
                currency=r["currency"],
                availability=r["availability"],
                scraped_at=datetime.fromisoformat(r["scraped_at"]),
            )
            for r in rows
        ]

    def categories(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT category, COUNT(*) AS n FROM products GROUP BY category ORDER BY n DESC"
            ).fetchall()
        return [{"category": r["category"], "count": r["n"]} for r in rows]
