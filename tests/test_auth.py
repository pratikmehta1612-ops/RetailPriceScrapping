"""Login, privacy and key-safety tests."""

import asyncio
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.auth import (
    LoginGuard, check_login, hash_password, make_session, parse_users, read_session, verify_password,
)
from app.config import Settings
from app.db import Database
from app.fetcher import BlockedError, ensure_public_host
from app.main import create_app
from scripts import manage_users
from tests.test_finder import REF_URL, FakeNet

PW = "correct horse battery"
SERP_KEY = "serp-SECRET-123"
AI_KEY = "sk-ant-SECRET-456"


def users(*names):
    return ";".join(f"{n}:{hash_password(PW, iterations=1000)}" for n in names)


def app_client(net=None, **overrides):
    settings = Settings(**{
        "serpapi_api_key": SERP_KEY, "anthropic_api_key": AI_KEY, "database_path": ":memory:",
        "app_users": users("alice", "bob"), "session_secret": "s3cret", "min_request_interval": 0,
        "block_private_addresses": False, "store_link_lookups": 0, **overrides,
    })
    return TestClient(create_app(settings, Database(":memory:"), transport=httpx.MockTransport(net or FakeNet())))


def login(client, name="alice", password=PW):
    return client.post("/api/login", json={"username": name, "password": password})


# ---------------------------------------------------------------- unit


def test_password_hashing():
    h = hash_password("hunter2hunter2")
    assert h.startswith("pbkdf2_sha256$600000$") and "hunter2" not in h
    assert verify_password("hunter2hunter2", h)
    assert not verify_password("hunter2hunter3", h)
    assert not verify_password("x", "garbage")
    assert hash_password("same") != hash_password("same")  # random salt


def test_parse_users_ignores_junk():
    h = hash_password("pw", iterations=1000)
    parsed = parse_users(f" Alice:{h} ; bob:plaintext ; ;nocolon")
    assert list(parsed) == ["alice"]
    assert check_login(parsed, "ALICE", "pw") and not check_login(parsed, "bob", "plaintext")


def test_session_tamper_and_expiry():
    token = make_session("alice", "k")
    assert read_session(token, "k")["u"] == "alice"
    assert read_session(token, "other-key") is None
    payload, sig = token.rsplit(".", 1)
    assert read_session(payload + "x." + sig, "k") is None
    assert read_session(make_session("alice", "k", days=-1), "k") is None


def test_login_guard_locks_after_five_failures():
    g = LoginGuard()
    for _ in range(5):
        g.fail("ip:1")
    assert g.locked("ip:1") > 0
    assert g.locked("ip:2") == 0


@pytest.mark.parametrize("host", ["127.0.0.1", "10.1.2.3", "192.168.0.10", "169.254.169.254", "::1", "localhost",
                                  "metadata.google.internal", "0.0.0.0", "[::ffff:127.0.0.1]"])
def test_private_addresses_blocked(host):
    with pytest.raises(BlockedError):
        asyncio.run(ensure_public_host(host))


def test_public_ip_allowed():
    asyncio.run(ensure_public_host("93.184.215.14"))


# ---------------------------------------------------------------- app


def test_everything_requires_login():
    with app_client() as c:
        assert c.get("/", follow_redirects=False).headers["location"] == "/login"
        assert c.get("/api/status").status_code == 401
        assert c.post("/api/find", json={"demo": True}).status_code == 401
        assert c.get("/api/searches").status_code == 401
        for path in ("/static/app.js", "/static/app.css", "/docs", "/openapi.json"):
            r = c.get(path, follow_redirects=False)
            assert r.status_code == 303 and r.headers["location"].startswith("/login"), path
        # Public pieces
        assert c.get("/login").status_code == 200
        assert c.get("/static/login.js").status_code == 200
        assert c.get("/healthz").json() == {"ok": True}


def test_login_flow_and_cookie_flags():
    with app_client() as c:
        assert login(c, password="wrong password").status_code == 401
        assert login(c, name="nobody").status_code == 401
        r = login(c, name="  Alice ")
        assert r.status_code == 200 and r.json() == {"username": "alice"}
        cookie = r.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=lax" in cookie
        assert c.get("/api/status").json()["user"] == "alice"
        assert c.get("/login", follow_redirects=False).status_code == 303  # already signed in
        c.post("/api/logout")
        assert c.get("/api/status").status_code == 401


def test_secure_cookie_over_https():
    with app_client() as c:
        c.base_url = "https://testserver"
        r = c.post("https://testserver/api/login", json={"username": "alice", "password": PW})
        assert "secure" in r.headers["set-cookie"].lower()


def test_lockout_after_repeated_failures():
    with app_client() as c:
        for _ in range(5):
            assert login(c, password="nope nope nope").status_code == 401
        r = login(c)  # even the right password is refused while locked
        assert r.status_code == 429 and "Too many failed attempts" in r.json()["detail"]


def test_password_change_or_removal_signs_out():
    with app_client() as c:
        login(c)
        assert c.get("/api/status").status_code == 200
    # Same secret, but alice's hash changed -> old cookie no longer valid.
    with app_client(app_users=users("bob")) as c2:
        c2.cookies = c.cookies
        assert c2.get("/api/status").status_code == 401


def test_users_only_see_their_own_searches():
    db = Database(":memory:")
    settings = dict(serpapi_api_key=SERP_KEY, anthropic_api_key=None, database_path=":memory:",
                    app_users=users("alice", "bob"), session_secret="s", store_link_lookups=0,
                    block_private_addresses=False)
    app = create_app(Settings(**settings), db, transport=httpx.MockTransport(FakeNet()))
    with TestClient(app) as a, TestClient(app) as b:
        login(a)
        login(b, name="bob")
        run = a.post("/api/find", json={"demo": True}).json()
        assert [s["id"] for s in a.get("/api/searches").json()] == [run["id"]]
        assert b.get("/api/searches").json() == []
        assert b.get(f"/api/searches/{run['id']}").status_code == 404
        assert b.delete(f"/api/searches/{run['id']}").status_code == 404
        assert b.post(f"/api/searches/{run['id']}/matches/0/store-link").status_code == 404


def test_daily_limit_and_demo_is_free():
    with app_client(daily_search_limit=2, anthropic_api_key=None) as c:
        login(c)
        for _ in range(3):
            assert c.post("/api/find", json={"demo": True}).status_code == 200
        assert c.post("/api/find", json={"url": REF_URL}).status_code == 200
        second = c.post("/api/find", json={"url": REF_URL})
        assert second.status_code == 200
        # Deleting a search doesn't give the credit back.
        c.delete(f"/api/searches/{second.json()['id']}")
        r = c.post("/api/find", json={"url": REF_URL})
        assert r.status_code == 429 and "limit of 2" in r.json()["detail"]
        assert c.get("/api/status").json()["searches_today"] == 2


def test_cross_site_post_blocked():
    with app_client() as c:
        login(c)
        r = c.post("/api/find", json={"demo": True}, headers={"Origin": "https://evil.example"})
        assert r.status_code == 403
        r = c.post("/api/find", json={"demo": True}, headers={"Origin": "http://testserver"})
        assert r.status_code == 200


def test_keys_never_reach_the_browser():
    net = FakeNet()
    with app_client(net) as c:
        bodies = [c.get("/login").text, c.get("/api/login-info").text]
        login(c)
        bodies += [
            c.get("/").text, c.get("/static/app.js").text, c.get("/api/status").text,
            c.post("/api/find", json={"url": REF_URL}).text, c.get("/api/searches").text,
        ]
        # The key really was used server-side...
        assert any(call.get("api_key") == SERP_KEY for call in net.serp_calls)
    # ...but never appears in anything sent to the browser.
    for body in bodies:
        assert SERP_KEY not in body and AI_KEY not in body


def test_serpapi_error_never_echoes_key():
    net = FakeNet(serp_error=f"Invalid API key {SERP_KEY}")
    with app_client(net) as c:
        login(c)
        r = c.post("/api/find", json={"url": REF_URL})
    assert r.status_code == 502 and SERP_KEY not in r.text and "***" in r.text


def test_security_headers():
    with app_client() as c:
        r = c.get("/login")
        assert r.headers["x-frame-options"] == "DENY"
        assert "script-src 'self'" in r.headers["content-security-policy"]


def test_private_link_is_refused_when_hosted():
    with app_client(block_private_addresses=True) as c:
        login(c)
        r = c.post("/api/find", json={"url": "http://169.254.169.254/latest/meta-data/hitch-ball-2-5-16-ball"})
        notes = r.json()["reference"]["notes"]
        assert any("private or internal address" in n for n in notes)


# ---------------------------------------------------------------- manage_users script


def test_manage_users_script(tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env"
    env.write_text("SERPAPI_API_KEY=abc\n# APP_USERS=\n", encoding="utf-8")
    monkeypatch.setattr(manage_users, "ENV", env)
    monkeypatch.setattr(manage_users, "EXAMPLE", tmp_path / "missing")

    assert manage_users.main(["add", "Pratik", "--password", "a-long-password"]) == 0
    assert manage_users.main(["add", "sam", "--password", "another-long-one"]) == 0
    assert manage_users.main(["add", "sam", "--password", "another-long-one"]) == 1  # exists
    assert manage_users.main(["add", "x y", "--password", "another-long-one"]) == 1  # bad name
    assert manage_users.main(["add", "kim", "--password", "short"]) == 1

    text = env.read_text()
    assert "SERPAPI_API_KEY=abc" in text and "a-long-password" not in text
    assert text.count("APP_USERS=") == 1 and "SESSION_SECRET=" in text
    parsed = parse_users(manage_users.get_env_value(text, "APP_USERS"))
    assert set(parsed) == {"pratik", "sam"} and check_login(parsed, "pratik", "a-long-password")

    assert manage_users.main(["passwd", "sam", "--password", "a-brand-new-pass"]) == 0
    parsed = parse_users(manage_users.get_env_value(env.read_text(), "APP_USERS"))
    assert check_login(parsed, "sam", "a-brand-new-pass") and not check_login(parsed, "sam", "another-long-one")

    assert manage_users.main(["remove", "sam"]) == 0
    capsys.readouterr()
    manage_users.main(["list"])
    assert capsys.readouterr().out.strip() == "pratik"
