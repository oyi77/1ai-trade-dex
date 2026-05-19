#!/usr/bin/env python3
"""
Import complete Polymarket trade history for the configured wallet.

Fetches ALL activity (trades + redeems) from Polymarket Data API
and imports into local DB. Idempotent — skips already-imported trades.

Usage:
    python scripts/import_full_history.py [--dry-run] [--wallet 0x...]
"""

import sys
import os
import json
import argparse
import logging
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from backend.config import settings
from backend.models.database import SessionLocal, Trade, engine
from sqlalchemy import text


logger = logging.getLogger(__name__)

DATA_API = getattr(settings, "DATA_API_URL", "https://data-api.polymarket.com")
WALLET = getattr(settings, "POLYMARKET_BUILDER_ADDRESS", None) or getattr(
    settings, "POLYMARKET_WALLET_ADDRESS", "0xad85c2f3942561afa448cbbd5811a5f7e2e3c6bd"
)


def fetch_all_activity(wallet: str, page_size: int = 100) -> list[dict]:
    """Fetch ALL activity records from Polymarket /activity endpoint."""
    all_records = []
    offset = 0
    client = httpx.Client(timeout=30)

    while True:
        url = f"{DATA_API}/activity"
        params = {"user": wallet, "limit": page_size, "offset": offset}
        resp = client.get(url, params=params)
        resp.raise_for_status()
        batch = resp.json()

        if not batch:
            break

        all_records.extend(batch)
        print(f"  Fetched {len(all_records)} records so far...")

        if len(batch) < page_size:
            break

        offset += page_size

    client.close()
    return all_records


def fetch_all_trades(wallet: str, page_size: int = 1000) -> list[dict]:
    """Fetch ALL trade records from Polymarket /trades endpoint."""
    all_records = []
    offset = 0
    client = httpx.Client(timeout=30)

    while True:
        url = f"{DATA_API}/trades"
        params = {"user": wallet, "limit": page_size, "offset": offset, "takerOnly": "true"}
        resp = client.get(url, params=params)
        resp.raise_for_status()
        batch = resp.json()

        if not batch:
            break

        all_records.extend(batch)
        print(f"  Fetched {len(all_records)} trades so far...")

        if len(batch) < page_size:
            break

        offset += page_size

    client.close()
    return all_records


def import_to_db(records: list[dict], dry_run: bool = False):
    """Import activity records into Trade table using raw SQL."""
    db = SessionLocal()

    # Check if journal columns exist
    has_journal = False
    try:
        cols = db.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='trades' AND column_name='journal_notes'"
        )).fetchall()
        has_journal = len(cols) > 0
    except Exception as e:
        logger.warning(f"Import error: {e}")

    # Get existing trade hashes to avoid duplicates
    existing = set()
    try:
        rows = db.execute(text("SELECT clob_order_id FROM trades WHERE clob_order_id IS NOT NULL")).fetchall()
        existing = {r[0] for r in rows}
    except Exception as e:
        logger.warning(f"Import error: {e}")

    imported = 0
    skipped = 0
    errors = 0

    # Build column list dynamically
    base_cols = [
        "market_ticker", "platform", "strategy", "trading_mode", "market_type",
        "direction", "entry_price", "size", "timestamp", "source", "role",
        "clob_order_id", "blockchain_verified", "settled", "settlement_time",
        "result", "pnl",
    ]
    if has_journal:
        base_cols.extend(["journal_notes", "journal_tags"])

    col_list = ", ".join(base_cols)
    placeholders = ", ".join([":" + c for c in base_cols])
    insert_sql = f"INSERT INTO trades ({col_list}) VALUES ({placeholders})"

    for rec in records:
        try:
            rec_type = rec.get("type", "").upper()
            if rec_type not in ("TRADE", "REDEEM"):
                continue

            market_slug = rec.get("market_slug", rec.get("slug", ""))
            title = rec.get("title", market_slug)
            side = rec.get("side", "").upper()
            asset_id = rec.get("asset_id", rec.get("assetId", ""))
            size = float(rec.get("size", rec.get("usdcSize", 0)))
            price = float(rec.get("price", 0))
            timestamp_ms = int(rec.get("timestamp", rec.get("createdAt", 0)))
            tx_hash = rec.get("transaction_hash", rec.get("hash", ""))

            if not market_slug and not title:
                skipped += 1
                continue

            dedup_key = f"{tx_hash}_{asset_id}" if tx_hash else f"{market_slug}_{side}_{timestamp_ms}"
            if dedup_key in existing:
                skipped += 1
                continue

            direction = "up" if side == "BUY" else "down"
            if rec_type == "REDEEM":
                direction = "up"

            ts = datetime.fromtimestamp(
                timestamp_ms / 1000 if timestamp_ms > 1e12 else timestamp_ms,
                tz=timezone.utc
            )

            params = {
                "market_ticker": title or market_slug,
                "platform": "polymarket",
                "strategy": "imported",
                "trading_mode": "live",
                "market_type": "polymarket",
                "direction": direction,
                "entry_price": price,
                "size": size / 100 if size > 1000 else size,
                "timestamp": ts,
                "source": "history_import",
                "role": "unknown",
                "clob_order_id": dedup_key,
                "blockchain_verified": False,
                "settled": (rec_type == "REDEEM"),
                "settlement_time": ts if rec_type == "REDEEM" else None,
                "result": "win" if rec_type == "REDEEM" else "pending",
                "pnl": None,
            }
            if has_journal:
                params["journal_notes"] = None
                params["journal_tags"] = None

            if dry_run:
                print(f"  [DRY] Would import: {title} {side} ${size:.2f} @ {price:.4f}")
                imported += 1
                continue

            db.execute(text(insert_sql), params)
            existing.add(dedup_key)
            imported += 1

            if imported % 100 == 0:
                db.commit()

        except Exception as e:
            errors += 1
            if errors < 10:
                print(f"  Error on record: {e}")

    if not dry_run:
        db.commit()

    db.close()
    return imported, skipped, errors


def main():
    parser = argparse.ArgumentParser(description="Import full Polymarket trade history")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing to DB")
    parser.add_argument("--wallet", default=WALLET, help="Wallet address")
    parser.add_argument("--source", choices=["activity", "trades"], default="activity",
                        help="Which API endpoint to use")
    args = parser.parse_args()

    wallet = args.wallet.lower()
    print(f"Wallet: {wallet}")
    print(f"Source: {args.source}")
    print(f"Dry run: {args.dry_run}")
    print()

    print("Fetching history from Polymarket...")
    if args.source == "activity":
        records = fetch_all_activity(wallet)
    else:
        records = fetch_all_trades(wallet)

    print(f"Total records fetched: {len(records)}")

    if not records:
        print("No records found.")
        return

    # Show breakdown
    types = {}
    for r in records:
        t = r.get("type", "unknown")
        types[t] = types.get(t, 0) + 1
    print(f"Record types: {types}")
    print()

    print("Importing to database...")
    imported, skipped, errors = import_to_db(records, dry_run=args.dry_run)

    print()
    print(f"Imported: {imported}")
    print(f"Skipped (duplicate): {skipped}")
    print(f"Errors: {errors}")


if __name__ == "__main__":
    main()
