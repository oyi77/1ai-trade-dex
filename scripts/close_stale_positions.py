#!/usr/bin/env python3
"""Close stale positions script — recover capital from zombie open positions.

Usage:
    python scripts/close_stale_positions.py                  # dry-run, 48h threshold
    python scripts/close_stale_positions.py --hours 24       # dry-run, 24h threshold
    python scripts/close_stale_positions.py --execute       # preview only (needs --force)
    python scripts/close_stale_positions.py --execute --force  # actually execute closes

Environment:
    SHADOW_MODE=true  — execute without placing real orders
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Allow standalone execution (add project root to path)
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger

# Configure logging: timestamp + level + message, no colour in CI
logger.configure(
    handlers=[
        {
            "sink": sys.stderr,
            "format": "<level>{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}</level>",
            "colorize": False,
        }
    ]
)

from backend.db.utils import get_db_session
from backend.models.database import Trade
from backend.config import settings

# ── constants ────────────────────────────────────────────────────────────────

DEFAULT_HOURS = 48
TABLE_FMT = "{:<8} {:<30} {:>12} {:>12} {:>12} {:>12} {}"
SEP = "-" * 105


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── core logic ───────────────────────────────────────────────────────────────

def _get_stale_trades(db, *, hours: int) -> list[Trade]:
    """Return open (unsettled) trades older than `hours`."""
    cutoff = _now() - timedelta(hours=hours)
    return (
        db.query(Trade)
        .filter(Trade.settled.is_(False))
        .filter(Trade.timestamp <= cutoff)
        .order_by(Trade.timestamp.asc())
        .all()
    )


def _estimate_pnl(trade: Trade, current_price: float | None) -> float | None:
    """Rough PnL estimate given the current market price.

    Returns None if we can't compute it (missing entry_price or direction).
    """
    if trade.direction is None or trade.entry_price is None:
        return None

    if current_price is None:
        return None

    if trade.direction == "up":
        # Polymarket binary: payout = size * settlement_value (1.0 or 0.0)
        # PnL from entry: (exit - entry) * size / entry_price (normalized)
        # Approximate: (current - entry) * size
        raw = (current_price - trade.entry_price) * trade.size
        return round(raw, 2)
    elif trade.direction == "down":
        raw = (trade.entry_price - current_price) * trade.size
        return round(raw, 2)
    return None


def _determine_action(trade: Trade, edge_pp: float | None) -> str:
    """Classify what we would do with this position."""
    if edge_pp is not None and edge_pp > 5:
        return "hold"      # still has edge, don't exit
    if trade.result in ("win", "loss"):
        return "resolve"   # outcome known, just need settlement
    return "exit"


def _fetch_current_price(market_ticker: str | None) -> float | None:
    """Attempt to get the current mid price for a market.

    Returns None if unavailable — the table will show N/A for price.
    Falls back to existing trade fields if CLOB call fails.
    """
    if not market_ticker:
        return None

    try:
        # Lazy-import CLOB to avoid startup errors in headless envs
        from backend.data.polymarket_clob import PolymarketCLOB

        clob = PolymarketCLOB(
            private_key=None,   # paper / read-only
            api_key=getattr(settings, "CLOB_API_KEY", None),
            base_url=getattr(settings, "CLOB_API_URL", None),
        )
        # get_mid_price is the sync entry point
        import asyncio
        price = asyncio.get_event_loop().run_until_complete(
            clob.get_mid_price(market_ticker)
        )
        return price
    except Exception:
        # If market lookup fails (token not found, network error), return None
        return None


def _dry_run_report(trades: list[Trade], hours: int, show_prices: bool) -> tuple[int, float]:
    """Print the dry-run table and return (count, estimated_recovery)."""
    total_recovery = 0.0

    print(f"\n{'=' * 105}")
    print(f"  STALE POSITIONS — DRY RUN  (threshold: {hours}h, as of {_now().strftime('%Y-%m-%d %H:%M UTC')})")
    print(f"{'=' * 105}")
    print()
    print(TABLE_FMT.format(
        "trade_id", "market_ticker", "age_hours", "entry_px", "current_px", "pnl_est", "action"
    ))
    print(SEP)

    for trade in trades:
        age = (_now() - trade.timestamp).total_seconds() / 3600
        current_px = None
        pnl_est = None
        edge_pp = getattr(trade, "edge_at_entry", None)

        if show_prices:
            current_px = _fetch_current_price(trade.market_ticker)

        if current_px is not None and trade.entry_price is not None:
            pnl_est = _estimate_pnl(trade, current_px)
            if pnl_est is not None:
                total_recovery += pnl_est

        action = _determine_action(trade, edge_pp)
        age_str = f"{age:.2f}"
        entry_str = f"{trade.entry_price:.4f}" if trade.entry_price else "N/A"
        curr_str = f"{current_px:.4f}" if current_px else "N/A"
        pnl_str = f"${pnl_est:.2f}" if pnl_est is not None else "N/A"
        market = trade.market_ticker or "unknown"

        print(TABLE_FMT.format(
            str(trade.id),
            market[:30],
            age_str,
            entry_str,
            curr_str,
            pnl_str,
            action,
        ))

    print(SEP)
    print(f"  Total positions: {len(trades)}")
    exit_count = sum(1 for t in trades if _determine_action(t, getattr(t, 'edge_at_entry', None)) == "exit")
    print(f"  Would close:    {exit_count}")
    print(f"  Estimated recovery: ${total_recovery:.2f}")
    print()
    return exit_count, total_recovery


def _execute_closes(trades: list[Trade], dry_run: bool = False) -> tuple[int, float]:
    """Place exit orders for stale positions.

    Returns (closed_count, actual_recovery).
    """
    shadow = os.environ.get("SHADOW_MODE", "").lower() == "true"

    if shadow:
        logger.warning("SHADOW_MODE=true — no real orders will be placed")

    total_recovery = 0.0
    closed_count = 0

    if dry_run:
        print("\n  [DRY RUN] Would attempt to close the following positions:")
    else:
        print("\n  Executing close orders...")

    for trade in trades:
        action = _determine_action(trade, getattr(trade, "edge_at_entry", None))
        if action == "hold":
            continue

        current_px = _fetch_current_price(trade.market_ticker)
        if current_px is not None:
            est_pnl = _estimate_pnl(trade, current_px)
        else:
            est_pnl = None

        if dry_run:
            print(f"    trade_id={trade.id} market={trade.market_ticker} "
                  f"direction={trade.direction} size={trade.size} "
                  f"(est_pnl={est_pnl})")
        else:
            try:
                from backend.data.polymarket_clob import PolymarketCLOB

                clob = PolymarketCLOB(
                    private_key=getattr(settings, "CLOB_PRIVATE_KEY", None),
                    api_key=getattr(settings, "CLOB_API_KEY", None),
                    base_url=getattr(settings, "CLOB_API_URL", None),
                )

                import asyncio
                # Determine the opposing side for closing
                close_side = "SELL" if trade.direction == "up" else "BUY"
                size = trade.filled_size or trade.size or 1.0

                # Use current mid as exit price (accepting whatever fill we get)
                exit_price = current_px or 0.5

                if shadow:
                    logger.info(
                        f"[SHADOW] Would {close_side} trade_id={trade.id} "
                        f"size={size} price={exit_price}"
                    )
                else:
                    result = asyncio.get_event_loop().run_until_complete(
                        clob.place_limit_order(
                            token_id=trade.market_ticker,
                            side=close_side,
                            size=size,
                            price=exit_price,
                        )
                    )
                    logger.info(f"Closed trade_id={trade.id} result={result}")

                if est_pnl is not None:
                    total_recovery += est_pnl
                closed_count += 1

            except Exception as exc:
                logger.error(f"Failed to close trade_id={trade.id}: {exc}")

    print(f"\n  Closed {closed_count} positions (est recovery: ${total_recovery:.2f})")
    return closed_count, total_recovery


# ── CLI ──────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Close stale open positions to recover locked capital.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/close_stale_positions.py
  python scripts/close_stale_positions.py --hours 72
  python scripts/close_stale_positions.py --execute
  python scripts/close_stale_positions.py --execute --force
  SHADOW_MODE=true python scripts/close_stale_positions.py --execute --force

The --execute flag alone does NOT place orders — you must also pass --force
to confirm you want to actually execute closes. This safety gate prevents
accidental execution.
        """,
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=DEFAULT_HOURS,
        help=f"Flag positions older than N hours (default: {DEFAULT_HOURS})",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually execute close orders (requires --force to proceed)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Must be combined with --execute to actually place orders",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Explicit dry-run mode (default)",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # Validate flags
    if args.execute and not args.force:
        print("ERROR: --execute requires --force to confirm. Refusing to proceed.\n"
              "  Example: python scripts/close_stale_positions.py --execute --force")
        return 1

    dry_run = not args.execute or args.dry_run  # dry-run unless both --execute AND --force
    if args.dry_run:
        dry_run = True

    hours = args.hours
    print(f"[INFO] Scanning for open positions older than {hours}h ...")

    with get_db_session() as db:
        stale_trades = _get_stale_trades(db, hours=hours)

    if not stale_trades:
        print(f"[INFO] No stale positions found (threshold: {hours}h). Exiting cleanly.")
        return 0

    if dry_run:
        exit_count, recovery = _dry_run_report(stale_trades, hours, show_prices=True)
        print(f"\n  To close {exit_count} positions (est. recovery ${recovery:.2f}):")
        print(f"    python scripts/close_stale_positions.py --execute --force --hours {hours}")
    else:
        exit_count, recovery = _execute_closes(stale_trades, dry_run=False)

    return 0


if __name__ == "__main__":
    sys.exit(main())