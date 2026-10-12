#!/usr/bin/env python3
"""WF09 btc_fade paper cycle (cron). Real DB + paper CLOB + live Gamma data. No funds.

Logs to logs/btc_fade_paper.log. Exit 0 always unless infra failure.
"""
import sys, asyncio, traceback
from datetime import datetime, timezone

sys.path.insert(0, "/home/openclaw/projects/1ai-trade-dex")

import os
os.environ.setdefault("TRADING_MODE", "paper")

LOG = "/home/openclaw/projects/1ai-trade-dex/logs/btc_fade_paper.log"

async def main():
    # Import order matters: core.risk imports db.utils first, priming it
    # before models.engine triggers the db.utils↔models circular.
    import backend.core.risk  # noqa: F401 — primes db.utils cleanly
    from backend.config import settings
    from backend.db.utils import get_db_session
    from backend.data.polymarket_clob.client import PolymarketCLOB
    from backend.strategies.btc_fade import BtcFadeStrategy
    from backend.strategies.base import StrategyContext
    from loguru import logger
    logger.remove()  # cron: file only, no stdout spam

    ts = datetime.now(timezone.utc).isoformat()
    with get_db_session() as db:
        clob = PolymarketCLOB(mode="paper")
        ctx = StrategyContext(db=db, clob=clob, settings=settings,
                              logger=logger, params={}, mode="paper", bankroll=100.0)
        s = BtcFadeStrategy()
        r = await s.run_cycle(ctx)
        # record into daily ops: decisions attempted as a heartbeat row
        line = (f"{ts} decisions={r.decisions_recorded} attempted={r.trades_attempted} "
                f"placed={r.trades_placed} scanned={r.markets_scanned} errors={r.errors}\n")
        with open(LOG, "a") as f:
            f.write(line)
        return r

if __name__ == "__main__":
    try:
        r = asyncio.run(main())
        print(f"OK decisions={r.decisions_recorded} attempted={r.trades_attempted} "
              f"placed={r.trades_placed} scanned={r.markets_scanned}")
    except Exception:
        traceback.print_exc()
        sys.exit(1)