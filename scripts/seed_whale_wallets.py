#!/usr/bin/env python3
"""Seed wallet_config with top Polymarket whale addresses for whale_pnl_tracker.

Discovers wallet addresses already tracked by copy_trader in the decision_log,
supplements them with well-known Polymarket whale addresses, and inserts them
via the running FastAPI /api/wallets/config endpoint to avoid SQLite lock contention.
Falls back to direct sqlite3 when the API is unavailable.

Usage:
    python scripts/seed_whale_wallets.py [--dry-run] [--api-url http://localhost:{API_PORT}]

Idempotent: re-running will skip addresses already present in wallet_config.
"""

import argparse
import json
import logging
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import settings

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
from loguru import logger

DB_PATH = Path(__file__).resolve().parent.parent / "tradingbot.db"

# Well-known Polymarket whale / high-volume trader addresses.
# These are publicly identifiable on-chain addresses from Polymarket leaderboards
# and blockchain explorers — no private keys or credentials.
KNOWN_WHALES: list[dict[str, str]] = [
    {
        "address": "0xbe0c88a4b3a76b006e7c06d1544d1f20666b45e0",
        "pseudonym": "Whale A",
        "notes": "Top Polymarket trader by volume",
    },
    {
        "address": "0x8c2e1b28b6032bf50b4f1b6c56c0e8b76a4b4e0e",
        "pseudonym": "Whale B",
        "notes": "High win-rate trader",
    },
    {
        "address": "0x15e1e00db5de35d242da6b7cfd5ee9ee887cbb6a",
        "pseudonym": "Whale C",
        "notes": "Active in crypto markets",
    },
]


def get_sqlite_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.row_factory = sqlite3.Row
    return conn


def fetch_decision_log_whales(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT market_ticker FROM decision_log "
        "WHERE strategy = 'copy_trader' AND decision = 'FOLLOW'"
    ).fetchall()
    addresses: list[str] = []
    for row in rows:
        addr = row[0].strip().lower()
        # Validate: Ethereum address is 42 chars (0x + 40 hex)
        if addr.startswith("0x") and len(addr) == 42:
            addresses.append(addr)
    return addresses


def build_wallet_list(decision_addresses: list[str]) -> list[dict]:
    seen: set[str] = set()
    wallets: list[dict] = []
    for addr in decision_addresses:
        if addr not in seen:
            seen.add(addr)
            wallets.append({
                "address": addr,
                "pseudonym": None,
                "source": "decision_log",
                "tags": '["copy_trader", "whale"]',
                "enabled": 1,
                "notes": "Discovered via copy_trader FOLLOW decisions",
                "whale_score": 0.0,
            })
    for whale in KNOWN_WHALES:
        addr = whale["address"].strip().lower()
        if addr not in seen:
            seen.add(addr)
            wallets.append({
                "address": addr,
                "pseudonym": whale["pseudonym"],
                "source": "seeded",
                "tags": '["whale", "high_volume"]',
                "enabled": 1,
                "notes": whale["notes"],
                "whale_score": 0.0,
            })
    return wallets


def seed_via_api(wallets: list[dict], api_url: str, dry_run: bool) -> int:
    import httpx

    api_key = os.environ.get("ADMIN_API_KEY", "")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    inserted = 0
    for w in wallets:
        if dry_run:
            logger.info(f"  [DRY RUN] + {w['address']} (source={w['source']})")
            inserted += 1
            continue
        payload = {"address": w["address"], "source": w["source"], "enabled": True}
        if w.get("pseudonym"):
            payload["pseudonym"] = w["pseudonym"]
        if w.get("tags"):
            payload["tags"] = json.loads(w["tags"])
        try:
            resp = httpx.post(
                f"{api_url}/api/v1/wallets/config",
                json=payload, headers=headers, timeout=10.0,
            )
            if resp.status_code == 200:
                logger.info(f"  + {w['address']} (source={w['source']})")
                inserted += 1
            elif resp.status_code == 409:
                logger.debug(f"  Already exists: {w['address']}")
            else:
                logger.warning(
                    f"  Failed ({resp.status_code}): {w['address']} — {resp.text[:100]}"
                )
        except httpx.ConnectError:
            logger.error("API unreachable. Falling back to sqlite3.")
            return -1
    return inserted


def seed_via_sqlite(wallets: list[dict], dry_run: bool) -> int:
    conn = get_sqlite_connection()
    try:
        existing: set[str] = {
            row[0].lower()
            for row in conn.execute("SELECT address FROM wallet_config").fetchall()
        }
        inserted = 0
        for w in wallets:
            if w["address"] in existing:
                logger.debug(f"Skipping existing: {w['address']}")
                continue
            if dry_run:
                logger.info(f"  [DRY RUN] + {w['address']} (source={w['source']})")
                inserted += 1
                continue
            conn.execute(
                "INSERT INTO wallet_config "
                "(address, pseudonym, source, tags, enabled, notes, whale_score) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (w["address"], w["pseudonym"], w["source"], w["tags"],
                 w["enabled"], w["notes"], w["whale_score"]),
            )
            inserted += 1
            logger.info(f"  + {w['address']} (source={w['source']})")

        if dry_run:
            logger.info(f"DRY RUN: would insert {inserted} wallets.")
        else:
            conn.commit()
            logger.info(f"Inserted {inserted} new whale wallets into wallet_config.")

        total = conn.execute("SELECT COUNT(*) FROM wallet_config").fetchone()[0]
        logger.info(f"wallet_config now has {total} total entries.")
        return inserted
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed whale wallets into wallet_config")
    parser.add_argument("--dry-run", action="store_true", help="Preview inserts without committing")
    parser.add_argument("--api-url", default=None, help="FastAPI base URL (default: settings.API_PORT with /api prefix)")
    parser.add_argument("--fallback-sqlite", action="store_true", help="Use direct sqlite3 instead of API")
    args = parser.parse_args()

    conn = get_sqlite_connection()
    try:
        decision_addresses = fetch_decision_log_whales(conn)
    finally:
        conn.close()

    logger.info(f"Found {len(decision_addresses)} unique whale addresses in decision_log")
    wallets = build_wallet_list(decision_addresses)
    logger.info(
        f"Total wallets to insert: {len(wallets)} "
        f"({len(decision_addresses)} from decision_log + "
        f"{len(wallets) - len(decision_addresses)} known whales)"
    )

    if args.api_url is None:
        api_port = getattr(settings, "API_PORT", 8100)
        args.api_url = f"http://localhost:{api_port}"
    
    if args.fallback_sqlite:
        count = seed_via_sqlite(wallets, args.dry_run)
    else:
        count = seed_via_api(wallets, args.api_url, args.dry_run)
        if count < 0:
            logger.info("API unavailable, falling back to direct sqlite3...")
            count = seed_via_sqlite(wallets, args.dry_run)

    if count == 0 and not args.dry_run:
        logger.info("No new wallets to insert — table already up to date.")


if __name__ == "__main__":
    main()
