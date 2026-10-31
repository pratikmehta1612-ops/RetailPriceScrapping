from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

# Fixture file -> the product URL it stands in for.
PAGES = {
    "amazon_oil_5w30.html": "https://www.amazon.com/Mobil-Extended-Performance-Synthetic/dp/B07KQ5V7MB",
    "amazon_oil_0w20.html": "https://www.amazon.com/Pennzoil-Platinum/dp/B00X2WS1AI",
    "walmart_oil_5w30.html": "https://www.walmart.com/ip/Castrol-EDGE-5W-30/10294317",
    "target_oil_5w30.html": "https://www.target.com/p/valvoline-5w-30/-/A-14769201",
    "store_tire_michelin.html": "https://www.tirestore.example/michelin-defender2-225-65r17",
    "walmart_tire_goodyear.html": "https://www.walmart.com/ip/Goodyear-Assurance/55512345",
    "store_tire_wrongsize.html": "https://www.tirestore.example/michelin-defender2-235-60r18",
    "amazon_battery_h6.html": "https://www.amazon.com/Optima-YellowTop/dp/B00M9AK3RI",
    "store_battery_h6.html": "https://www.autoparts.example/everstart-platinum-h6",
    "bestbuy_wiper.html": "https://www.bestbuy.com/site/bosch-icon-22a/6401234.p?skuId=6401234",
}


def page(name: str) -> tuple[str, str]:
    return PAGES[name], (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def load_page():
    return page
