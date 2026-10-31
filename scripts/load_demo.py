"""Load the sample product pages from tests/fixtures into the database.

Usage:  python -m scripts.load_demo
These are synthetic pages (made-up prices) for trying the dashboard offline.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.db import Database  # noqa: E402
from app.service import add_from_html  # noqa: E402
from tests.conftest import FIXTURES, PAGES  # noqa: E402


def main() -> None:
    settings = get_settings()
    db = Database(settings.database_path)
    for name, url in PAGES.items():
        product = add_from_html(db, url, (FIXTURES / name).read_text(encoding="utf-8"))
        print(f"{product.category:<12} {product.retailer:<20} ${product.price or 0:>8.2f}  {product.title}")
    print(f"\nLoaded {len(PAGES)} demo products into {settings.database_path}")


if __name__ == "__main__":
    main()
