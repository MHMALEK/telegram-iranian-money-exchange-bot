"""Seed demo users and sell offers for the buyer catalog (synthetic telegram_id values).

Uses stdlib sqlite3 only (no aiosqlite).

Run from project root:
  python scripts/seed_demo_offers.py

Database path: SEED_SQLITE_PATH env var, or default data/app.db
(with DATABASE_URL=sqlite+aiosqlite:///./data/app.db in .env, that is the same data/app.db).

Each run deletes and recreates the demo users and their offers.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Synthetic telegram_ids for demo rows
DEMO_IDS = (8123456001, 8123456002)

DEMO_ROWS: list[tuple[int, str | None, str, list[tuple[int, str]]]] = [
    (
        8123456001,
        "demo_seller_usd",
        "فروشندهٔ تست دلار",
        [(500, "USD"), (1200, "USD"), (250, "USD")],
    ),
    (
        8123456002,
        "demo_seller_eur",
        "فروشندهٔ تست یورو",
        [(300, "EUR"), (750, "EUR")],
    ),
]


def _default_db_path() -> Path:
    env_path = os.environ.get("SEED_SQLITE_PATH", "").strip()
    if env_path:
        return Path(env_path).expanduser()
    env_file = ROOT / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DATABASE_URL=") and "aiosqlite" in line:
                # sqlite+aiosqlite:///./data/app.db
                rest = line.split("=", 1)[1].strip().strip('"').strip("'")
                if rest.startswith("sqlite+aiosqlite:///"):
                    raw = rest.removeprefix("sqlite+aiosqlite:///")
                    if raw.startswith("./"):
                        return (ROOT / raw[2:]).resolve()
                    if not raw.startswith("/"):
                        return (ROOT / raw).resolve()
                    return Path(raw)
    return (ROOT / "data" / "app.db").resolve()


def main() -> None:
    db_path = _default_db_path()
    if not db_path.is_file():
        print(f"Database file not found: {db_path}", file=sys.stderr)
        print("Run the bot once (or init_db) so tables exist, then retry.", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        for tid in DEMO_IDS:
            conn.execute("DELETE FROM users WHERE telegram_id = ?", (tid,))
        conn.commit()

        for tid, username, first_name, offers in DEMO_ROWS:
            cur = conn.execute(
                "INSERT INTO users (telegram_id, username, first_name) VALUES (?, ?, ?)",
                (tid, username, first_name),
            )
            uid = cur.lastrowid
            demo_pay = json.dumps(["cash_in_person", "bank"])
            for amount, currency in offers:
                conn.execute(
                    """
                    INSERT INTO sell_offers (
                        user_id, telegram_id, telegram_username,
                        seller_display_name, amount, currency, description, payment_methods
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (uid, tid, username, first_name, amount, currency, None, demo_pay),
                )
        conn.commit()
    finally:
        conn.close()

    print(f"OK: seeded demo offers in {db_path}")
    for tid, un, name, offers in DEMO_ROWS:
        print(f"  telegram_id={tid} @{un or '—'} — {len(offers)} offers")


if __name__ == "__main__":
    main()
