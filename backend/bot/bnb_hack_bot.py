"""
BNB HACK — Autonomous Onchain Trading Agent.

Runs 24/7 during BNB HACK competition (June 22-28, 2026).
Strategy: SMA trend following on 1h (10/50 crossover) with 3% TP/SL.
  Backtested: +10.78% / 6mo, 43.6% WR, 10.47% DD, Sharpe 0.27, 55 trades.
Executes on BSC via TWAK CLI.

Usage:
    python -m backend.bot.bnb_hack_bot                    # Single cycle
    python -m backend.bot.bnb_hack_bot --loop             # Continuous mode
    python -m backend.bot.bnb_hack_bot --loop --paper     # Paper trade
"""

import argparse
import asyncio
import signal

from loguru import logger

from backend.bot.bnb_hack import BnbHackBot
from backend.config import settings


_shutdown_requested = False


def _handle_signal(signum, frame):
    global _shutdown_requested
    logger.info("Signal {} received — shutting down gracefully", signum)
    _shutdown_requested = True


async def run_once(paper: bool = False):
    bot = BnbHackBot.from_config(paper=paper)
    try:
        price = await bot.feed.get_price("BNBUSDT")
        sig = await bot.signals.evaluate()
        bal = await bot.exchange.balance()
        print()
        print("=" * 60)
        print(f"  Agent:     {settings.bnb_hack.wallet_address}")
        print(f"  Explorer:  https://bscscan.com/address/{settings.bnb_hack.wallet_address}")
        print(f"  Price:     ${price}")
        print(f"  Signal:    {sig['action']} (conf: {sig['confidence']:.2f})")
        print(f"  Reason:    {sig['reason']}")
        if sig.get("indicators"):
            ind = sig["indicators"]
            print(f"  SMA:       {ind.get('sma_cross')} (fast: {ind.get('sma_fast')}, "
                  f"slow: {ind.get('sma_slow')})")
        print("=" * 60)
    finally:
        await bot.close()


async def run_loop(paper: bool = False):
    global _shutdown_requested
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    bot = BnbHackBot.from_config(paper=paper)
    try:
        await bot.run()
    finally:
        await bot.close()


def main():
    parser = argparse.ArgumentParser(
        description="BNB HACK — Autonomous Onchain Trading Agent")
    parser.add_argument("--loop", action="store_true", help="Run continuously")
    parser.add_argument("--paper", action="store_true", help="Paper trade only")
    args = parser.parse_args()

    logger.info("═" * 60)
    logger.info("BNB HACK Bot — SMA({}/{}) {} TP:{}% SL:{}%",
                 settings.bnb_hack.sma_fast, settings.bnb_hack.sma_slow,
                 settings.bnb_hack.timeframe,
                 settings.bnb_hack.take_profit_pct, settings.bnb_hack.stop_loss_pct)
    logger.info("  Capital: $34 | Paper: {} | Chain: bsc", args.paper)
    logger.info("  Competition: {} → {}",
                 settings.bnb_hack.competition_start, settings.bnb_hack.competition_end)
    logger.info("═" * 60)

    if args.paper:
        asyncio.run(run_loop(paper=True))
    elif args.loop:
        asyncio.run(run_loop(paper=False))
    else:
        asyncio.run(run_once(paper=args.paper))


if __name__ == "__main__":
    main()
