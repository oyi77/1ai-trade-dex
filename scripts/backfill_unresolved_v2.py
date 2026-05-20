#!/usr/bin/env python3
"""
Backfill script v2: Resolve unresolved trades via Gamma price extremes.

Gamma API returns prices like [0.0005, 0.9995] even when closed=False.
If a market hasn't closed but prices are extreme (one side ~0.0005, other ~0.9995),
the outcome is effectively determined.

This script:
1. Queries Gamma by slug for each unresolved trade
2. Detects resolved outcomes from price extremes
3. Stores condition_id for future settlement pipeline use
4. Updates trades with correct PnL
5. Reconciles bot_state bankroll
"""

import sys, asyncio, json, httpx
from datetime import datetime, timezone
from typing import Optional, Tuple

sys.path.insert(0, "/home/openclaw/projects/polyedge")

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from backend.config import settings

engine = create_engine(settings.DATABASE_URL)
Session = sessionmaker(bind=engine)
GAMMA = settings.GAMMA_API_URL
CLOB_HOST = settings.CLOB_API_URL

EXTREME_THRESHOLD = 0.005  # Price < this = resolved to NO/YES for that index


def parse_outcome_prices(raw_prices) -> Tuple[Optional[float], Optional[float]]:
    """Parse outcomePrices from Gamma market dict."""
    if not raw_prices:
        return None, None
    if isinstance(raw_prices, str):
        try:
            prices = json.loads(raw_prices)
        except (json.JSONDecodeError, TypeError):
            prices = [p.strip() for p in raw_prices.strip("[]").split(",") if p.strip()]
    elif isinstance(raw_prices, list):
        prices = raw_prices
    else:
        return None, None
    try:
        p0 = float(prices[0]) if prices else None
        p1 = float(prices[1]) if len(prices) > 1 else None
        return p0, p1
    except (ValueError, IndexError):
        return None, None


def calculate_entry_pnl(
    direction: str, entry_price: float, size: float, settlement_value: float
) -> float:
    """Calculate actual PnL for a trade given settlement_value (1.0=YES won, 0.0=NO won)."""
    dir_yes = direction in ("yes", "up")
    is_win = (dir_yes and settlement_value == 1.0) or (
        not dir_yes and settlement_value == 0.0
    )
    if is_win:
        return (1.0 - entry_price) * size
    else:
        return -(entry_price * size)


async def resolve_trade(ticker: str) -> Tuple[bool, Optional[float], Optional[str]]:
    """Resolve a trade by looking up its market on Gamma. Returns (resolved, settlement_value, condition_id)."""
    async with httpx.AsyncClient(timeout=15) as c:
        # Query Gamma by slug
        r = await c.get(f"{GAMMA}/markets", params={"slug": ticker})
        if r.status_code != 200:
            return False, None, None

        data = r.json()
        if not isinstance(data, list) or not data:
            return False, None, None

        market = data[0]
        prices = parse_outcome_prices(market.get("outcomePrices"))
        if not prices or prices[0] is None:
            return False, None, None

        p0, p1 = prices
        condition_id = market.get("conditionId", "")

        # Check if market resolved at price extreme
        if p0 <= EXTREME_THRESHOLD and p1 >= (1.0 - EXTREME_THRESHOLD):
            # YES (index 0) = worthless, NO (index 1) = full payout
            return True, 0.0, condition_id  # Settlement: NO won (outcome 0)
        elif p1 <= EXTREME_THRESHOLD and p0 >= (1.0 - EXTREME_THRESHOLD):
            # NO (index 1) = worthless, YES (index 0) = full payout
            return True, 1.0, condition_id  # Settlement: YES won (outcome 1)

        # Check resolved_outcome field directly
        resolved_outcome = market.get("resolved_outcome")
        if resolved_outcome:
            if resolved_outcome.lower() in ("yes", "1"):
                return True, 1.0, condition_id
            elif resolved_outcome.lower() in ("no", "0"):
                return True, 0.0, condition_id

        return False, None, condition_id


async def backfill(dry_run: bool = True):
    """Main backfill logic."""
    db = Session()

    unresolved = db.execute(
        text(
            """
        SELECT id, market_ticker, direction, entry_price, size, 
               strategy, timestamp, event_slug, token_id, condition_id
        FROM trades 
        WHERE result = 'closed_unresolved' AND settled = true AND trading_mode = 'live'
        ORDER BY timestamp DESC
    """
        )
    ).fetchall()

    print(f"\n{'='*60}")
    print(f"BACKFILL V2: {len(unresolved)} unresolved trades")
    print(f"MODE: {'DRY RUN' if dry_run else 'LIVE UPDATE'}")
    print(f"{'='*60}\n")

    resolved_count = 0
    loss_count = 0
    win_count = 0
    total_pnl = 0.0
    no_data = 0
    still_open = 0

    for i, trade in enumerate(unresolved):
        (
            tid,
            ticker,
            direction,
            entry_price,
            size,
            strategy,
            ts,
            event_slug,
            token_id,
            cond_id,
        ) = trade

        progress = f"[{i+1}/{len(unresolved)}]"

        if entry_price is not None and entry_price >= 1.0:
            print(f"  {progress} #{tid} {ticker} ⏭️ entry >= 1.0 (sample)")
            continue

        if entry_price is None:
            entry_price = 0.0

        print(
            f"  {progress} #{tid} {ticker} {direction} @ {entry_price:.4f} sz={size:.2f}",
            end="",
        )

        resolved, settlement_value, gamma_cond_id = await resolve_trade(ticker)

        if resolved and settlement_value is not None:
            pnl = round(
                calculate_entry_pnl(direction, entry_price, size, settlement_value), 2
            )
            result_str = "win" if pnl > 0 else "loss"

            if pnl > 0:
                win_count += 1
            else:
                loss_count += 1
            total_pnl += pnl

            print(f" → {'🟢' if pnl>0 else '🔴'} {result_str} PnL={pnl:+.2f}", end="")

            if not dry_run:
                db.execute(
                    text(
                        """
                    UPDATE trades 
                    SET result = :result, pnl = :pnl, 
                        settlement_value = :sv, condition_id = :cond_id,
                        settlement_source = 'backfill_v2',
                        settlement_time = NOW()
                    WHERE id = :tid
                """
                    ),
                    {
                        "result": result_str,
                        "pnl": pnl,
                        "sv": settlement_value,
                        "cond_id": gamma_cond_id or cond_id,
                        "tid": tid,
                    },
                )
            resolved_count += 1
        elif gamma_cond_id and not resolved:
            # Market still open / not yet resolved — store condition_id
            print(f" → ⏳ still open, storing condition_id", end="")
            still_open += 1
            if not dry_run:
                db.execute(
                    text("UPDATE trades SET condition_id=:cid WHERE id=:tid"),
                    {"cid": gamma_cond_id, "tid": tid},
                )
        else:
            print(f" → ❌ no data", end="")
            no_data += 1

        print()

        # Commit batch after every 50 trades
        if not dry_run and (i + 1) % 50 == 0:
            db.commit()

    if not dry_run:
        db.commit()

    print(f"\n{'='*60}")
    print(f"BACKFILL V2 SUMMARY:")
    print(f"  Total processed: {len(unresolved)}")
    print(f"  Resolved: {resolved_count}")
    print(f"    Wins: {win_count}")
    print(f"    Losses: {loss_count}")
    print(f"  Net PnL adjustment: ${total_pnl:.2f}")
    print(f"  Still open (cond_id stored): {still_open}")
    print(f"  No data on Gamma: {no_data}")
    print(f"  Dry run: {dry_run}")
    print(f"{'='*60}")

    # After updating trades, reconcile bot_state
    if not dry_run and resolved_count > 0:
        print(f"\n🔄 Re-calculating bot_state live bankroll...")
        new_pnl = (
            db.execute(
                text(
                    """
            SELECT SUM(pnl) FROM trades 
            WHERE trading_mode = 'live' AND pnl IS NOT NULL AND settled = true
        """
                )
            ).scalar()
            or 0
        )
        new_bankroll = 100.0 + new_pnl
        db.execute(
            text(
                """
            UPDATE bot_state SET bankroll = :br, total_pnl = :pnl, 
                last_sync_at = NOW()
            WHERE mode = 'live'
        """
            ),
            {"br": round(new_bankroll, 2), "pnl": round(new_pnl, 2)},
        )
        db.commit()
        print(f"  Live bankroll: ${new_bankroll:.2f}")
        print(f"  Live PnL: ${new_pnl:.2f}")

    db.close()


if __name__ == "__main__":
    dry_run = "--live" not in sys.argv
    if "--live" in sys.argv:
        dry_run = False
    limit = None
    for arg in sys.argv:
        if arg.startswith("--limit="):
            limit = int(arg.split("=")[1])

    asyncio.run(backfill(dry_run=dry_run))
