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
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from backend.config import settings
from backend.models.database import SessionLocal, Trade, engine
from sqlalchemy import text


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
    """Import activity records into Trade table."""
    db = SessionLocal()

    # Get existing trade hashes to avoid duplicates
    existing = set()
    try:
        rows = db.execute(text("SELECT clob_order_id FROM trades WHERE clob_order_id IS NOT NULL")).fetchall()
        existing = {r[0] for r in rows}
    except Exception:
        pass

    imported = 0
    skipped = 0
    errors = 0

    for rec in records:
        try:
            rec_type = rec.get("type", "").upper()
            if rec_type not in ("TRADE", "REDEEM"):
                continue

            # Extract fields
            market_slug = rec.get("market_slug", rec.get("slug", ""))
            title = rec.get("title", rec.get("market_slug", ""))
            side = rec.get("side", "").upper()  # BUY or SELL
            asset_id = rec.get("asset_id", rec.get("assetId", ""))
            condition_id = rec.get("condition_id", rec.get("conditionId", ""))
            size = float(rec.get("size", rec.get("usdcSize", 0)))
            price = float(rec.get("price", 0))
            timestamp_ms = int(rec.get("timestamp", rec.get("createdAt", 0)))
            tx_hash = rec.get("transaction_hash", rec.get("hash", ""))
            outcome = rec.get("outcome", "")
            title = rec.get("title", market_slug)

            if not market_slug and not title:
                skipped += 1
                continue

            # Dedup by tx_hash + asset_id
            dedup_key = f"{tx_hash}_{asset_id}" if tx_hash else f"{market_slug}_{side}_{timestamp_ms}"
            if dedup_key in existing:
                skipped += 1
                continue

            if dry_run:
                print(f"  [DRY] Would import: {title} {side} ${size:.2f} @ {price:.4f}")
                imported += 1
                continue

            # Determine direction
            direction = "up" if side == "BUY" else "down"
            if rec_type == "REDEEM":
                direction = "up"  # redeems are wins

            # Create trade
            trade = Trade(
                market_ticker=title or market_slug,
                platform="polymarket",
                direction=direction,
                entry_price=price,
                size=size / 100 if size > 1000 else size,  # normalize USDC units
                trading_mode="live",
                market_type="polymarket",
                strategy="imported",
                source="history_import",
                clob_order_id=dedup_key,
                settled=(rec_type == "REDEEM"),
                timestamp=datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc) if timestamp_ms > 1e12 else datetime.fromtimestamp(timestamp_ms, tz=timezone.utc),
            )

            if rec_type == "REDEEM":
                trade.result = "win"
                trade.settlement_time = trade.timestamp

            db.add(trade)
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
