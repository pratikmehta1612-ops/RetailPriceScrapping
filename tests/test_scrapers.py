import pytest

from app.fetcher import looks_blocked
from app.scrapers import retailer_for, scrape_html
from app.scrapers.retailers import amazon_asin, bestbuy_sku, target_tcin
from tests.conftest import FIXTURES


def test_amazon(load_page):
    url, html = load_page("amazon_oil_5w30.html")
    p = scrape_html(url, html)
    assert p.retailer == "amazon"
    assert p.title.startswith("Mobil 1 Extended Performance")
    assert p.price == 28.97
    assert p.brand == "Mobil 1"
    assert p.sku == "B07KQ5V7MB"
    assert p.image == "https://example.com/m1.jpg"
    assert p.specs["Viscosity"] == "5W-30"
    assert p.specs["Manufacturer Part Number"] == "124186"


def test_walmart_next_data(load_page):
    p = scrape_html(*load_page("walmart_oil_5w30.html"))
    assert p.retailer == "walmart"
    assert p.title == "Castrol EDGE Full Synthetic Motor Oil 5W-30, 5 Quarts"
    assert p.price == 27.48
    assert p.brand == "Castrol"
    assert p.gtin == "079191234567"
    assert p.specs["Viscosity"] == "5W-30"
    assert "Fluid TITANIUM" in p.description


def test_target_jsonld_and_bold_specs(load_page):
    p = scrape_html(*load_page("target_oil_5w30.html"))
    assert p.retailer == "target"
    assert p.price == 26.99
    assert p.brand == "Valvoline"
    assert p.availability == "InStock"
    assert p.specs["Viscosity"] == "5W-30"
    assert p.specs["Capacity (Volume)"] == "5 Quart"


def test_generic_jsonld_lowest_offer_and_properties(load_page):
    p = scrape_html(*load_page("store_tire_michelin.html"))
    assert p.retailer == "tirestore.example"
    assert p.price == 189.99
    assert p.mpn == "28123"
    assert p.specs["Load Index"] == "102"


def test_bestbuy_aggregate_offer(load_page):
    p = scrape_html(*load_page("bestbuy_wiper.html"))
    assert p.retailer == "bestbuy"
    assert p.price == 27.99
    assert p.brand == "Bosch"


def test_non_product_page_raises():
    with pytest.raises(ValueError):
        scrape_html("https://example.com/x", "<html><body>nothing</body></html>")


def test_url_helpers():
    assert amazon_asin("https://www.amazon.com/gp/product/B000ABC123?th=1") == "B000ABC123"
    assert bestbuy_sku("https://www.bestbuy.com/site/x/6401234.p?skuId=6401234") == "6401234"
    assert target_tcin("https://www.target.com/p/x/-/A-14769201#lnk") == "14769201"
    assert retailer_for("https://www.amazon.co.uk/dp/B000ABC123")[0] == "amazon"
    assert retailer_for("https://shop.autozone.com/p/1")[0] == "shop.autozone.com"


def test_block_detection():
    assert looks_blocked((FIXTURES / "blocked.html").read_text())
    assert not looks_blocked((FIXTURES / "amazon_oil_5w30.html").read_text())
