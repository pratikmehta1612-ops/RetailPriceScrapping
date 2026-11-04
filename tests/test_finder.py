"""End-to-end tests with the network replaced by fakes (store page, SerpApi, Claude)."""

import json
import re
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.auth import hash_password
from app.config import Settings
from app.db import Database
from app.main import create_app

DEMO = Path(__file__).resolve().parent.parent / "app" / "demo"
REF_URL = ("https://www.overtons.com/husky-round-bar-weight-distribution-hitch-with-sway-control-"
           "12k-2-516-ball-no-shank-146894.html?utm_source=bing")
REF_PAGE = """<html><head>
<title>Husky Round Bar Hitch W/ Sway Control, 12K, 2-5/16" Ball, No Shank | Overton's</title>
<meta property="og:title" content='Husky Round Bar Hitch W/ Sway Control, 12K, 2-5/16" Ball, No Shank'>
<script type="application/ld+json">{"@type":"Product","name":"Husky Round Bar Hitch W/ Sway Control, 12K, 2-5/16\\" Ball, No Shank",
 "brand":"Husky","offers":{"price":"529.99","priceCurrency":"USD"}}</script>
</head><body><h1>Husky Round Bar Hitch</h1><p>Tongue weight capacity: 1,200 lbs.</p></body></html>"""


class FakeNet:
    def __init__(self, page_status=200, serp_error=None):
        self.page_status = page_status
        self.serp_error = serp_error
        self.serp_calls = []
        self.claude_calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host == "www.overtons.com":
            if request.url.path == "/robots.txt":
                return httpx.Response(404)
            return httpx.Response(self.page_status, text=REF_PAGE if self.page_status == 200 else "denied")
        if host == "serpapi.com":
            params = dict(request.url.params)
            self.serp_calls.append(params)
            if self.serp_error:
                return httpx.Response(401, json={"error": self.serp_error})
            if params["engine"] == "google_shopping":
                return httpx.Response(200, text=(DEMO / "demo_shopping.json").read_text())
            offers = json.loads((DEMO / "demo_offers.json").read_text())
            return httpx.Response(200, json=offers[params["page_token"]])
        if host == "api.anthropic.com":
            self.claude_calls += 1
            prompt = json.loads(request.content)["messages"][0]["content"]
            if prompt.startswith("You help find products"):
                text = json.dumps({
                    "product_type": "weight distribution hitch",
                    "summary": "Round bar WD hitch with sway control for 12,000 lb trailers.",
                    "attributes": [
                        {"name": "Gross trailer weight", "value": "12,000 lb", "importance": "must"},
                        {"name": "Ball size", "value": "2-5/16 in", "importance": "must"},
                        {"name": "Sway control", "value": "integrated", "importance": "high"},
                    ],
                    "queries": ["Husky round bar hitch 12K", "12000 lb weight distribution hitch sway control 2-5/16 ball"],
                })
            else:
                rows = []
                for m in re.finditer(r"^(\d+)\. (.+?) \|", prompt, re.M):
                    title = m.group(2)
                    good = "12,000" in title or "12K" in title
                    rows.append({"id": int(m.group(1)), "score": 92 if good else 15,
                                 "same_product": False, "differences": [] if good else ["Different rating"],
                                 "reason": "Same specs" if good else "Different rating"})
                text = "Here you go:\n```json\n" + json.dumps(rows) + "\n```"
            return httpx.Response(200, json={"content": [{"type": "text", "text": text}],
                                             "usage": {"input_tokens": 1000, "output_tokens": 200}})
        return httpx.Response(404)


TEST_USERS = f"alice:{hash_password('correct horse battery', iterations=1000)}"


def make_client(net: FakeNet, login: bool = True, **overrides) -> TestClient:
    settings = Settings(**{
        "serpapi_api_key": "test-key", "anthropic_api_key": None, "database_path": ":memory:",
        "min_request_interval": 0, "app_users": TEST_USERS, "session_secret": "test-secret",
        "block_private_addresses": False, **overrides,
    })
    client = TestClient(create_app(settings, Database(":memory:"), transport=httpx.MockTransport(net)))
    if login:
        r = client.post("/api/login", json={"username": "alice", "password": "correct horse battery"})
        assert r.status_code == 200, r.text
    return client


def test_find_rules_only():
    net = FakeNet()
    with make_client(net) as client:
        r = client.post("/api/find", json={"url": REF_URL})
        assert r.status_code == 200, r.text
        run = r.json()

    ref = run["reference"]
    assert ref["title"] == 'Husky Round Bar Hitch W/ Sway Control, 12K, 2-5/16" Ball, No Shank'
    assert ref["price"] == 529.99 and ref["brand"] == "Husky"
    assert ref["attributes"]["tongue_weight_lb"] == 1200  # from the page text
    assert not run["ai_used"]

    matches = run["matches"]
    assert len(matches) >= 10
    top = matches[:10]
    # Every one of the top 10 has the same rating and ball size as the reference.
    for m in top:
        cmp = {c["feature"]: c["match"] for c in m["comparisons"]}
        assert cmp.get("weight_rating_lb") == "yes", m["title"]
        assert cmp.get("ball_diameter_in") == "yes", m["title"]
    assert matches[0]["level"] == "same"
    # Wrong ball size or rating never ranks above a real match.
    wrong = [m for m in matches if "2\" Ball" in m["title"] or "10,000" in m["title"]]
    assert all(m["score"] <= 0.3 for m in wrong)

    # 3 shopping searches + 10 store-link lookups; top 10 have direct links.
    engines = [c["engine"] for c in net.serp_calls]
    assert engines.count("google_shopping") == 3
    assert engines.count("google_immersive_product") == 10
    assert run["searches_used"] == 13
    assert all(m["link"].startswith("https://example.") for m in top)
    assert top[0]["price_vs_reference"] == pytest.approx(top[0]["price"] - 529.99)


def test_find_with_ai():
    net = FakeNet()
    with make_client(net, anthropic_api_key="sk-test", store_link_lookups=0) as client:
        run = client.post("/api/find", json={"url": REF_URL, "use_ai": True}).json()
    assert run["ai_used"] and net.claude_calls == 2
    assert run["key_attributes"][0] == {"name": "Gross trailer weight", "value": "12,000 lb", "importance": "must"}
    assert run["queries"][1] == "Husky round bar hitch 12K"
    best = run["matches"][0]
    assert best["ai_score"] == pytest.approx(0.92)
    assert best["reason"] == "Same specs"


def test_ai_can_be_switched_off_per_search():
    net = FakeNet()
    with make_client(net, anthropic_api_key="sk-test", store_link_lookups=0) as client:
        run = client.post("/api/find", json={"url": REF_URL, "use_ai": False}).json()
    assert not run["ai_used"] and net.claude_calls == 0


def test_blocked_page_falls_back_to_link_words():
    net = FakeNet(page_status=403)
    with make_client(net, store_link_lookups=0) as client:
        run = client.post("/api/find", json={"url": REF_URL}).json()
    ref = run["reference"]
    assert ref["title"].lower().startswith("husky round bar weight distribution hitch")
    assert ref["attributes"]["ball_diameter_in"] == pytest.approx(2.3125)
    assert any("Couldn't read the product page" in n for n in ref["notes"])
    assert len(run["matches"]) >= 10


def test_details_only():
    net = FakeNet()
    with make_client(net, store_link_lookups=0) as client:
        run = client.post("/api/find", json={"details": 'Husky Round Bar Hitch W/ Sway Control, 12K, 2-5/16" Ball'}).json()
    assert run["reference"]["category"] == "weight_distribution_hitch"
    assert len(run["matches"]) >= 10


def test_store_link_on_demand_and_history():
    net = FakeNet()
    with make_client(net, store_link_lookups=0) as client:
        run = client.post("/api/find", json={"url": REF_URL}).json()
        first = run["matches"][0]
        assert first["link"] is None
        r = client.post(f"/api/searches/{run['id']}/matches/{first['id']}/store-link")
        assert r.status_code == 200
        assert r.json()["link"].startswith("https://example.")
        saved = client.get(f"/api/searches/{run['id']}").json()
        assert saved["matches"][0]["link"] == r.json()["link"]
        history = client.get("/api/searches").json()
        assert history[0]["id"] == run["id"] and history[0]["match_count"] == len(run["matches"])
        assert client.delete(f"/api/searches/{run['id']}").status_code == 204
        assert client.get(f"/api/searches/{run['id']}").status_code == 404


def test_serpapi_error_is_reported():
    net = FakeNet(serp_error="Invalid API key. Your API key should be here: https://serpapi.com/manage-api-key")
    with make_client(net) as client:
        r = client.post("/api/find", json={"url": REF_URL})
    assert r.status_code == 502 and "Invalid API key" in r.json()["detail"]


def test_without_key_demo_still_works():
    net = FakeNet()
    with make_client(net, serpapi_api_key=None) as client:
        assert client.get("/api/status").json()["search_ready"] is False
        assert client.post("/api/find", json={"url": REF_URL}).status_code == 400
        run = client.post("/api/find", json={"demo": True}).json()
        assert run["demo"] and len(run["matches"]) >= 10
        assert run["reference"]["notes"][0].startswith("Demo mode")
        assert not net.serp_calls
        assert client.get("/").status_code == 200
