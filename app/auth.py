"""Login: users, password hashing, signed session cookies and brute-force protection.

Users live in the APP_USERS setting as `name:hash` pairs separated by `;`.
Only password *hashes* are stored (PBKDF2-SHA256, 600,000 rounds, random salt),
so the settings file never contains a readable password. Add or change users
with:  python -m scripts.manage_users add <name>
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, field

ITERATIONS = 600_000
SESSION_COOKIE = "rps_session"
SESSION_DAYS = 7
MAX_FAILURES = 5
LOCKOUT_SECONDS = 15 * 60


# ------------------------------------------------------------------ passwords


def hash_password(password: str, *, iterations: int = ITERATIONS) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), iterations).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt, digest = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        check = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations)).hex()
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(check, digest)


# A real hash to compare against when the username doesn't exist, so a wrong
# username takes as long as a wrong password (no username guessing by timing).
_DUMMY_HASH = hash_password(secrets.token_hex(8), iterations=ITERATIONS)


def parse_users(value: str | None) -> dict[str, str]:
    users: dict[str, str] = {}
    for entry in (value or "").replace("\n", ";").split(";"):
        entry = entry.strip()
        if not entry or ":" not in entry:
            continue
        name, _, hashed = entry.partition(":")
        name, hashed = name.strip().lower(), hashed.strip()
        if name and hashed.startswith("pbkdf2_sha256$"):
            users[name] = hashed
    return users


def format_users(users: dict[str, str]) -> str:
    return ";".join(f"{name}:{hashed}" for name, hashed in sorted(users.items()))


def valid_username(name: str) -> bool:
    return 2 <= len(name) <= 40 and all(c.isalnum() or c in "._-@" for c in name)


# ------------------------------------------------------------------ sessions


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def make_session(username: str, secret: str, days: int = SESSION_DAYS, version: str = "") -> str:
    payload = _b64(json.dumps({"u": username, "exp": int(time.time()) + days * 86400, "v": version}).encode())
    sig = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def read_session(token: str | None, secret: str) -> dict | None:
    if not token or "." not in token:
        return None
    payload, sig = token.rsplit(".", 1)
    expected = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        data = json.loads(_unb64(payload))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("exp", 0) < time.time():
        return None
    return data


def password_version(stored_hash: str) -> str:
    """Changes when the password changes, which signs out that user's old sessions."""
    return hashlib.sha256(stored_hash.encode()).hexdigest()[:12]


# ------------------------------------------------------------------ brute-force protection


@dataclass
class LoginGuard:
    failures: dict[str, list[float]] = field(default_factory=dict)

    def _recent(self, key: str) -> list[float]:
        cutoff = time.time() - LOCKOUT_SECONDS
        recent = [t for t in self.failures.get(key, []) if t > cutoff]
        self.failures[key] = recent
        return recent

    def locked(self, *keys: str) -> int:
        """Seconds until login is allowed again, or 0."""
        wait = 0
        for key in keys:
            recent = self._recent(key)
            if len(recent) >= MAX_FAILURES:
                wait = max(wait, int(recent[0] + LOCKOUT_SECONDS - time.time()) + 1)
        return wait

    def fail(self, *keys: str) -> None:
        for key in keys:
            self._recent(key).append(time.time())

    def clear(self, *keys: str) -> None:
        for key in keys:
            self.failures.pop(key, None)


def check_login(users: dict[str, str], username: str, password: str) -> bool:
    stored = users.get(username.strip().lower())
    ok = verify_password(password, stored or _DUMMY_HASH)
    return ok and stored is not None
