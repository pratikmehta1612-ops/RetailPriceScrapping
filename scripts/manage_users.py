"""Add, change, remove or list app users.

Usage (from the project folder):
    python -m scripts.manage_users add alice        # asks for a password
    python -m scripts.manage_users passwd alice     # change a password
    python -m scripts.manage_users remove alice
    python -m scripts.manage_users list
    python -m scripts.manage_users export           # print the APP_USERS value for a hosting service

Users are saved in the APP_USERS line of the .env file, as hashed passwords only.
Restart the app after a change. When hosted (e.g. Render), paste the value from
`export` into the APP_USERS environment variable there.
"""

from __future__ import annotations

import argparse
import getpass
import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.auth import format_users, hash_password, parse_users, valid_username  # noqa: E402

ENV = ROOT / ".env"
EXAMPLE = ROOT / ".env.example"
MIN_LENGTH = 10


def read_env() -> str:
    if ENV.exists():
        return ENV.read_text(encoding="utf-8")
    if EXAMPLE.exists():
        return EXAMPLE.read_text(encoding="utf-8")
    return ""


def set_env_value(text: str, key: str, value: str) -> str:
    line = f"{key}={value}"
    pattern = re.compile(rf"^\s*#?\s*{re.escape(key)}\s*=.*$", re.M)
    if pattern.search(text):
        return pattern.sub(lambda _: line, text, count=1)
    return text.rstrip("\n") + f"\n{line}\n"


def get_env_value(text: str, key: str) -> str:
    m = re.search(rf"^\s*{re.escape(key)}\s*=(.*)$", text, re.M)
    return m.group(1).strip().strip('"').strip("'") if m else ""


def ask_password(name: str) -> str:
    while True:
        first = getpass.getpass(f"Password for {name} (min {MIN_LENGTH} characters, typing is hidden): ")
        if len(first) < MIN_LENGTH:
            print(f"Too short. Use at least {MIN_LENGTH} characters.")
            continue
        if getpass.getpass("Type it again: ") != first:
            print("The two passwords don't match. Try again.")
            continue
        return first


def save(text: str, users: dict[str, str]) -> None:
    text = set_env_value(text, "APP_USERS", format_users(users))
    if not get_env_value(text, "SESSION_SECRET"):
        text = set_env_value(text, "SESSION_SECRET", secrets.token_urlsafe(32))
    ENV.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage login users for the Similar Product Finder.")
    sub = parser.add_subparsers(dest="command", required=True)
    for cmd in ("add", "passwd", "remove"):
        p = sub.add_parser(cmd)
        p.add_argument("username")
        if cmd != "remove":
            p.add_argument("--password", help=argparse.SUPPRESS)  # for scripts/tests; avoid on shared machines
    sub.add_parser("list")
    sub.add_parser("export")
    args = parser.parse_args(argv)

    text = read_env()
    users = parse_users(get_env_value(text, "APP_USERS"))

    if args.command == "list":
        print("\n".join(sorted(users)) if users else "No users yet. Add one with: python -m scripts.manage_users add <name>")
        return 0
    if args.command == "export":
        print(f"APP_USERS={format_users(users)}")
        print(f"SESSION_SECRET={get_env_value(text, 'SESSION_SECRET') or secrets.token_urlsafe(32)}")
        return 0

    name = args.username.strip().lower()
    if not valid_username(name):
        print("Usernames are 2-40 characters: letters, numbers, dot, dash, underscore or @.")
        return 1

    if args.command == "remove":
        if name not in users:
            print(f"No user named {name}.")
            return 1
        del users[name]
        save(text, users)
        print(f"Removed {name}. Restart the app for this to take effect.")
        return 0

    if args.command == "add" and name in users:
        print(f"{name} already exists. Use: python -m scripts.manage_users passwd {name}")
        return 1
    if args.command == "passwd" and name not in users:
        print(f"No user named {name}. Use: python -m scripts.manage_users add {name}")
        return 1

    password = args.password or ask_password(name)
    if len(password) < MIN_LENGTH:
        print(f"Password must be at least {MIN_LENGTH} characters.")
        return 1
    users[name] = hash_password(password)
    save(text, users)
    verb = "Added" if args.command == "add" else "Changed the password for"
    print(f"{verb} {name}. Restart the app for this to take effect.")
    print("Hosting online? Run `python -m scripts.manage_users export` and copy APP_USERS to your host's settings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
