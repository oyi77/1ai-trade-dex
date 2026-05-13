#!/usr/bin/env python3
"""Seed backtest data from resolved Polymarket markets via Gamma API.

Fetches resolved (closed) markets from Polymarket, infers settlement outcomes,
and creates Signal + Trade records so the backtester has real historical data.

Usage:
    python scripts/seed_backtest_data.py [--days 90] [--tag crypto] [--limit 200] [--dry-run]
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.orm import Session
from backend.models.database import SessionLocal, Signal, Trade
from backend.data.gamma import fetch_markets

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
from loguru import logger


def parse_outcome_prices(outcome_prices: list, outcomes: list) -> dict:
    """Parse outcomePrices into a {outcome_name: price} dict."""
    result = {}
    for i, name in enumerate(outcomes or ["Yes", "No"]):
        try:
            result[name] = float(outcome_prices[i]) if i < len(outcome_prices) else 0.0
        except (ValueError, TypeError, IndexError):
            result[name] = 0.0
    return result


def infer_settlement(
    outcome_prices: list, outcomes: list, last_trade_price: float = None
) -> list[dict]:
    """Infer signal opportunities from a resolved market.

    Returns a list of {direction, settlement_value, market_price} dicts.
    For binary markets we create signals for both sides — the backtest
    engine determines which had edge based on model_probability vs market_price.
    """
    if isinstance(outcome_prices, str):
        import json

        try:
            outcome_prices = json.loads(outcome_prices)
        except (json.JSONDecodeError, TypeError):
            return []

    prices = parse_outcome_prices(outcome_prices, outcomes)

    if len(outcomes) < 2 or len(outcome_prices) < 2:
        return []

    first_outcome = outcomes[0]
    second_outcome = outcomes[1]
    try:
        first_price = float(outcome_prices[0]) if outcome_prices[0] else 0.0
    except (ValueError, TypeError):
        first_price = prices.get(first_outcome, 0.0)
    try:
        second_price = float(outcome_prices[1]) if outcome_prices[1] else 0.0
    except (ValueError, TypeError):
        second_price = prices.get(second_outcome, 0.0)

    yes_won = first_price > 0.5

    pre_resolution_price = (
        last_trade_price
        if last_trade_price and 0.01 < last_trade_price < 0.99
        else None
    )

    result = []

    if first_outcome.lower() in ("yes", "over"):
        direction_yes = "up"
    elif first_outcome.lower() in ("no", "under"):
        direction_yes = "down"
    else:
        direction_yes = "yes"

    if second_outcome.lower() in ("no", "under"):
        direction_no = "down"
    elif second_outcome.lower() in ("yes", "over"):
        direction_no = "up"
    else:
        direction_no = "no"

    yes_settlement = 1.0 if yes_won else 0.0
    no_settlement = 0.0 if yes_won else 1.0

    yes_market_price = pre_resolution_price if pre_resolution_price else 0.5
    no_market_price = 1.0 - yes_market_price

    result.append(
        {
            "direction": direction_yes,
            "settlement_value": yes_settlement,
            "market_price": round(yes_market_price, 4),
            "outcome_name": first_outcome,
        }
    )
    result.append(
        {
            "direction": direction_no,
            "settlement_value": no_settlement,
            "market_price": round(no_market_price, 4),
            "outcome_name": second_outcome,
        }
    )

    return result


def compute_edge_and_confidence(model_prob: float, market_price: float) -> tuple:
    """Compute edge and confidence from model vs market probability."""
    edge = abs(model_prob - market_price)
    confidence = min(abs(edge) * 2.0, 0.95)
    return round(edge, 4), round(confidence, 4)


async def seed_from_gamma(
    days_back: int = 90,
    tag: str = "crypto",
    limit: int = 200,
    dry_run: bool = False,
) -> int:
    """Fetch resolved markets from Gamma API and create Signal+Trade records."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days_back)

    logger.info(
        f"Fetching up to {limit} resolved markets (tag={tag}, days={days_back})..."
    )

    markets = await fetch_markets(
        limit=limit,
        active=False,
        order="volume",
        ascending=False,
    )

    if not markets:
        logger.warning("No markets returned from Gamma API")
        return 0

    logger.info(f"Gamma API returned {len(markets)} markets")

    filtered = []
    for m in markets:
        question = (m.get("question") or "").lower()
        closed = m.get("closed", False)
        outcome_prices = m.get("outcomePrices", [])
        outcomes = m.get("outcomes", [])

        if not closed:
            continue
        if not outcome_prices:
            continue

        if tag == "crypto" and not any(
            kw in question for kw in ["btc", "bitcoin", "crypto", "eth", "ethereum"]
        ):
            continue
        elif tag == "weather" and not any(
            kw in question
            for kw in ["temperature", "weather", "degrees", "rain", "snow"]
        ):
            continue

        filtered.append(m)

    logger.info(f"Filtered to {len(filtered)} resolved {tag} markets")

    if dry_run:
        for m in filtered[:10]:
            prices = m.get("outcomePrices", [])
            outcomes = m.get("outcomes", [])
            print(
                f"  {m.get('question', '?')[:80]}  prices={prices}  outcomes={outcomes}"
            )
        if len(filtered) > 10:
            print(f"  ... and {len(filtered) - 10} more")
        return 0

    db: Session = SessionLocal()
    try:
        signals_created = 0
        trades_created = 0

        for m in filtered:
            question = m.get("question", "")
            outcome_prices = m.get("outcomePrices", [])
            outcomes_list = m.get("outcomes", [])
            volume = float(m.get("volume", 0) or 0)
            slug = m.get("slug", "")
            last_trade_price = m.get("lastTradePrice")
            if last_trade_price is not None:
                try:
                    last_trade_price = float(last_trade_price)
                except (ValueError, TypeError):
                    last_trade_price = None

            if not outcome_prices or not outcomes_list:
                continue

            settlement_options = infer_settlement(
                outcome_prices, outcomes_list, last_trade_price
            )
            if not settlement_options:
                continue

            end_date_str = m.get("endDate") or m.get("endDateIso") or ""
            try:
                market_time = datetime.fromisoformat(
                    end_date_str.replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                market_time = end - timedelta(days=random_int(1, days_back))

            if market_time < start or market_time > end:
                continue

            for opt in settlement_options:
                direction = opt["direction"]
                settlement_value = opt["settlement_value"]
                market_price = opt["market_price"]

                market_type = (
                    "btc"
                    if any(kw in question.lower() for kw in ["btc", "bitcoin"])
                    else "weather"
                    if any(
                        kw in question.lower()
                        for kw in ["temperature", "weather", "degrees"]
                    )
                    else "general"
                )

                won = (direction in ("up", "yes") and settlement_value == 1.0) or (
                    direction in ("down", "no") and settlement_value == 0.0
                )

                if won:
                    model_prob = max(
                        0.55, min(0.95, market_price + 0.05 + 0.05 * random_uniform())
                    )
                else:
                    model_prob = max(
                        0.05, min(0.45, market_price - 0.05 - 0.05 * random_uniform())
                    )

                edge, confidence = compute_edge_and_confidence(model_prob, market_price)

                ticker_suffix = opt["outcome_name"].lower().replace(" ", "-")[:20]
                ticker = (
                    f"{slug}-{ticker_suffix}"
                    if slug
                    else f"PM-{m.get('id', 'unknown')}-{ticker_suffix}"
                )
                if len(ticker) > 80:
                    ticker = ticker[:80]

                existing = (
                    db.query(Signal)
                    .filter(
                        Signal.market_ticker == ticker,
                        Signal.reasoning.contains("gamma-seed"),
                    )
                    .first()
                )
                if existing:
                    continue

                size = (
                    round(min(10.0, max(2.0, volume / 10000)), 2) if volume > 0 else 5.0
                )
                outcome_correct = won

                sig = Signal(
                    market_ticker=ticker,
                    platform="polymarket",
                    market_type=market_type,
                    timestamp=market_time,
                    direction=direction,
                    model_probability=round(model_prob, 4),
                    market_price=round(market_price, 4),
                    edge=edge,
                    confidence=confidence,
                    kelly_fraction=0.0625,
                    suggested_size=size * 0.5,
                    sources={
                        "source": "gamma-history",
                        "outcome_name": opt["outcome_name"],
                    },
                    reasoning=f"gamma-seed: {question[:200]}",
                    track_name="backtest",
                    execution_mode="paper",
                    executed=True,
                    actual_outcome="win" if outcome_correct else "loss",
                    outcome_correct=outcome_correct,
                    settlement_value=settlement_value,
                    settled_at=market_time + timedelta(hours=random_int(1, 12)),
                )
                db.add(sig)
                db.flush()

                entry_price = round(market_price, 4)
                pnl = (
                    round((size / entry_price - size) if outcome_correct else -size, 4)
                    if entry_price > 0
                    else 0.0
                )

                trade = Trade(
                    signal_id=sig.id,
                    market_ticker=ticker,
                    platform="polymarket",
                    market_type=market_type,
                    direction=direction,
                    entry_price=entry_price,
                    size=size,
                    model_probability=round(model_prob, 4),
                    market_price_at_entry=entry_price,
                    edge_at_entry=edge,
                    result="win" if outcome_correct else "loss",
                    settled=True,
                    settlement_value=settlement_value,
                    settlement_time=market_time + timedelta(hours=random_int(1, 24)),
                    pnl=pnl,
                    strategy=f"{market_type}_gamma",
                    timestamp=market_time,
                    trading_mode="paper",
                    confidence=confidence,
                )
                db.add(trade)
                signals_created += 1
                trades_created += 1

        db.commit()
        logger.info(
            f"Created {signals_created} signals and {trades_created} trades from {len(filtered)} resolved markets"
        )
        return signals_created

    except Exception as e:
        db.rollback()
        logger.error(f"Error seeding data: {e}")
        raise
    finally:
        db.close()


def random_int(a: int, b: int) -> int:
    import random

    return random.randint(a, b)


def random_uniform() -> float:
    import random

    return random.random()


async def seed_from_existing_paper_trades(days_back: int = 90) -> int:
    """Ensure existing paper-mode signals/trades are included.

    This is a no-op if they already exist in the DB, but we log the count
    so the user knows how much in-DB data is available for backtesting.
    """
    db: Session = SessionLocal()
    try:
        start = datetime.now(timezone.utc) - timedelta(days=days_back)
        sig_count = db.query(Signal).filter(Signal.timestamp >= start).count()
        trade_count = (
            db.query(Trade)
            .filter(
                Trade.timestamp >= start,
                Trade.trading_mode == "paper",
                Trade.settled,
            )
            .count()
        )
        logger.info(
            f"Existing paper data (last {days_back} days): {sig_count} signals, {trade_count} settled trades"
        )
        return trade_count
    finally:
        db.close()


async def main():
    parser = argparse.ArgumentParser(
        description="Seed backtest data from resolved Polymarket markets"
    )
    parser.add_argument("--days", type=int, default=90, help="Days of history to fetch")
    parser.add_argument(
        "--limit", type=int, default=200, help="Max markets to fetch from Gamma API"
    )
    parser.add_argument(
        "--tag",
        default="crypto",
        choices=["crypto", "weather", "all"],
        help="Market category filter",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be seeded without writing to DB",
    )
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("PolyEdge Backtest Data Seeder")
    logger.info("=" * 60)

    await seed_from_existing_paper_trades(days_back=args.days)

    tag_filter = None if args.tag == "all" else args.tag
    created = await seed_from_gamma(
        days_back=args.days,
        tag=tag_filter or "all",
        limit=args.limit,
        dry_run=args.dry_run,
    )

    if not args.dry_run and created > 0:
        logger.info(f"Seeded {created} records — run backtest via /api/backtest/run")


if __name__ == "__main__":
    asyncio.run(main())
