import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Database
from app.main import create_app
from tests.conftest import PAGES, page


@pytest.fixture
def client():
    app = create_app(Settings(database_path=":memory:"), Database(":memory:"))
    with TestClient(app) as c:
        for name in PAGES:
            url, html = page(name)
            if len(html) < 200:
                html = html + " " * 200
            r = c.post("/api/products/import", json={"url": url, "html": html})
            assert r.status_code == 201, r.text
        yield c


def by_title(c, fragment):
    return next(p for p in c.get("/api/products").json() if fragment in p["title"])


def test_list_and_categories(client):
    products = client.get("/api/products").json()
    assert len(products) == len(PAGES)
    cats = {c["category"]: c["count"] for c in client.get("/api/categories").json()}
    assert cats == {"motor_oil": 4, "tire": 3, "battery": 2, "wiper_blade": 1}
    oils = client.get("/api/products", params={"category": "motor_oil"}).json()
    assert all(p["unit_label"] == "quart" for p in oils)


def test_similar_oil_matches_viscosity(client):
    mobil = by_title(client, "Mobil 1")
    sims = client.get(f"/api/products/{mobil['id']}/similar").json()
    titles = [s["product"]["title"] for s in sims]
    assert any("Castrol" in t for t in titles)
    assert any("Valvoline" in t for t in titles)
    assert not any("0W-20" in t for t in titles)  # wrong viscosity is filtered out
    castrol = next(s for s in sims if "Castrol" in s["product"]["title"])
    # Castrol $27.48/5qt vs Mobil 1 $28.97/5qt -> per-quart difference
    assert castrol["price_difference"] == pytest.approx(5.50 - 5.79, abs=0.01)
    assert {"feature": "viscosity", "a": "5W-30", "b": "5W-30", "match": True} in castrol["comparisons"]


def test_similar_tire_requires_same_size(client):
    michelin = by_title(client, "225/65R17 102H All-Season")
    sims = client.get(f"/api/products/{michelin['id']}/similar").json()
    assert [s["product"]["title"] for s in sims] == [
        "Goodyear Assurance WeatherReady All-Weather 225/65R17 102H Tire"
    ]
    everything = client.get(f"/api/products/{michelin['id']}/similar", params={"min_score": 0}).json()
    wrong = next(s for s in everything if "235/60R18" in s["product"]["title"])
    assert wrong["score"] <= 0.25


def test_battery_match(client):
    optima = by_title(client, "Optima")
    sims = client.get(f"/api/products/{optima['id']}/similar").json()
    assert sims and "EverStart" in sims[0]["product"]["title"]
    assert sims[0]["price_difference"] == pytest.approx(199.84 - 289.99, abs=0.01)


def test_history_and_reimport(client):
    url, html = page("walmart_oil_5w30.html")
    client.post("/api/products/import", json={"url": url, "html": html.replace("27.48", "24.97")})
    castrol = by_title(client, "Castrol")
    history = client.get(f"/api/products/{castrol['id']}/history").json()
    assert [h["price"] for h in history] == [27.48, 24.97]
    assert castrol["price"] == 24.97
    assert len(client.get("/api/products").json()) == len(PAGES)


def test_delete_and_404(client):
    wiper = by_title(client, "Bosch")
    assert client.delete(f"/api/products/{wiper['id']}").status_code == 204
    assert client.get(f"/api/products/{wiper['id']}").status_code == 404


def test_import_rejects_non_product(client):
    r = client.post("/api/products/import", json={"url": "https://example.com/a", "html": "<html>" + "x" * 300 + "</html>"})
    assert r.status_code == 422


def test_dashboard_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "Retail Price Compare" in r.text
    assert client.get("/static/app.js").status_code == 200
