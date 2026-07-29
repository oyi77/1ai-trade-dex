# db_sync.py — extracted from scheduler.py
"""Scheduler sub-module: db_sync."""

from backend.models.database import ScheduledJob, Trade
from datetime import datetime, timedelta, timezone
from loguru import logger

async def _sync_db_to_polymarket_job():
    """Periodic 1:1 sync: DB trades ↔ Polymarket reality.

    Fetches Polymarket positions every 5 minutes and ensures DB trade statuses
    match what's actually on Polymarket. Prevents the DB from drifting away
    from reality over hours/days of continuous operation.

    Fixes the root cause of 190+ unsettled trades accumulating over weeks.
    """
    import httpx
    from backend.db.utils import get_db_session
    from backend.models.database import Trade
    from backend.config import settings as _settings

    try:
        wallet = _settings.POLYMARKET_BUILDER_ADDRESS
        if not wallet:
            logger.debug("[db_pm_sync] No wallet address configured, skipping")
            return

        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{_settings.DATA_API_URL}/positions?user={wallet.lower()}"
            )
            if r.status_code != 200:
                logger.warning(f"[db_pm_sync] Positions API returned {r.status_code}")
                return
            positions = r.json()

        # Build token_id → position map
        pm_positions = {}
        for p in positions:
            asset = p.get("asset", "")
            if asset:
                pm_positions[asset] = {
                    "size": float(p.get("size", 0)),
                    "cur_price": float(p.get("curPrice", 0)),
                    "title": p.get("title", ""),
                    "outcome": p.get("outcome", ""),
                    "redeemable": p.get("redeemable", False),
                }

        with get_db_session() as db:
            # 1. Find DB trades marked as filled but position no longer exists
            db_filled = (
                db.query(Trade)
                .filter(
                    Trade.trading_mode == "live",
                    Trade.status == "filled",
                    Trade.settled.is_(False),
                )
                .all()
            )

            marked_closed = 0
            for trade in db_filled:
                tid = str(trade.token_id) if trade.token_id else ""
                if tid and tid not in pm_positions:
                    # Position gone → market resolved, mark closed
                    trade.status = "closed"
                    trade.settlement_time = datetime.now(timezone.utc)
                    trade.settlement_source = "db_pm_sync"
                    marked_closed += 1

            # 2. Find DB trades that should be filled (have matching PM position)
            db_open = (
                db.query(Trade)
                .filter(
                    Trade.trading_mode == "live",
                    Trade.token_id.isnot(None),
                    Trade.settled.is_(False),
                    Trade.status.in_([None, "open", "pending"]),
                )
                .all()
            )

            marked_filled = 0
            pm_assets_found = set()
            for trade in db_open:
                tid = str(trade.token_id) if trade.token_id else ""
                if tid and tid in pm_positions:
                    pos = pm_positions[tid]
                    trade.status = "filled"
                    # Update PnL in real-time
                    direction = (trade.direction or "no").lower()
                    entry = float(trade.entry_price or 0)
                    cur = pos["cur_price"]
                    size = float(trade.size or 0)
                    if direction in ("yes", "up"):
                        trade.pnl = round(size * (cur - entry), 4)
                    else:
                        trade.pnl = round(size * (entry - cur), 4)
                    trade.settlement_time = datetime.now(timezone.utc)
                    marked_filled += 1
                    pm_assets_found.add(tid)

            if marked_closed > 0 or marked_filled > 0:
                db.commit()
                logger.info(
                    f"[db_pm_sync] Synced: {marked_filled} marked filled, "
                    f"{marked_closed} marked closed. "
                    f"PM positions: {len(pm_positions)}, DB filled: {len(db_filled)}, "
                    f"DB open: {len(db_open)}"
                )

            # 3. Update bot_state bankroll from portfolio reality
            if marked_closed > 0 or marked_filled > 0:
                try:
                    total_pos_value = sum(
                        float(p.get("currentValue", 0)) for p in positions
                    )
                    # Use recent wallet_sync value or fallback
                    from backend.models.database import BotState

                    state = db.query(BotState).filter_by(mode="live").first()
                    if state:
                        cash = float(state.bankroll or 0) - total_pos_value
                        from backend.core.wallet.botstate_ledger import BotStateLedger

                        BotStateLedger.sync_to_absolute(
                            db=db,
                            mode="live",
                            target_balance=cash + total_pos_value,
                            source="db_pm_sync",
                        )
                        db.commit()
                except Exception as e:
                    logger.debug(f"[db_pm_sync] bankroll update failed: {e}")

    except Exception as e:
        logger.warning(f"[db_pm_sync] Failed: {e}")

async def _cleanup_stale_trades_job():
    """Settle trades older than 12h that are still open. Prevents stale accumulation.

    Handles BOTH live and paper modes. For paper trades, first attempts Gamma
    resolution before force-settling (fixes the 1990+ paper trades stuck as
    status=None forever bug).
    """
    from backend.db.utils import get_db_session
    from backend.models.database import Trade

    try:
        with get_db_session() as db:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=12)
            from sqlalchemy import or_
            stale_live = (
                db.query(Trade)
                .filter(
                    Trade.settled.is_(False),
                    Trade.trading_mode == "live",
                    Trade.timestamp < cutoff,
                    or_(Trade.filled_size == 0.0, Trade.filled_size.is_(None)),
                )
                .all()
            )
            if stale_live:
                for t in stale_live:
                    t.settled = True
                    t.result = "expired"
                    t.pnl = 0.0
                    t.settlement_value = 0.0
                    t.settlement_time = datetime.now(timezone.utc)
                    t.settlement_source = "stale_live_force_close"
                db.commit()
                logger.info(
                    f"[stale_trade_cleanup] Expired {len(stale_live)} unfilled stale LIVE trades (>12h)"
                )

            # Paper trades: mark settled=True with pnl=None to let
            # resolve_paper_trades pick them up for Gamma resolution.
            # Previously: paper trades were NEVER cleaned (query had no
            # mode filter but the pnl=0.0 assignment blocked Gamma resolution).
            stale_paper = (
                db.query(Trade)
                .filter(
                    Trade.settled.is_(False),
                    Trade.trading_mode == "paper",
                    Trade.timestamp < cutoff,
                )
                .all()
            )
            if stale_paper:
                for t in stale_paper:
                    t.settled = True
                    t.pnl = None  # signal to resolve_paper_trades: resolve me
                    t.settlement_value = None
                    t.settlement_time = datetime.now(timezone.utc)
                db.commit()
                logger.info(
                    f"[stale_trade_cleanup] Marked {len(stale_paper)} stale PAPER trades "
                    f"for Gamma resolution (>12h)"
                )

                # Immediately resolve them via Gamma
                try:
                    from backend.core.settlement.settlement_helpers import (
                        resolve_paper_trades,
                    )

                    paper_settled = await resolve_paper_trades(db)
                    if paper_settled:
                        wins = sum(1 for t in paper_settled if getattr(t, "result", "") == "win")
                        losses = len(paper_settled) - wins
                        total_pnl = sum(
                            getattr(t, "pnl", 0.0) or 0.0 for t in paper_settled
                        )
                        logger.info(
                            f"[stale_trade_cleanup] Gamma-resolved {len(paper_settled)} "
                            f"paper trades: {wins}W/{losses}L, PnL=${total_pnl:+.2f}"
                        )
                except Exception as e:
                    logger.warning(f"[stale_trade_cleanup] Paper Gamma resolution failed: {e}")
                    db.rollback()

            # Force-settle paper trades that were marked for Gamma but couldn't
            # resolve (e.g. weather/event markets where Gamma returns '[').
            # These are stuck at settled=True, pnl=NULL. After 5 days, force as loss.
            stuck_cutoff = datetime.now(timezone.utc) - timedelta(days=5)
            stuck_paper = (
                db.query(Trade)
                .filter(
                    Trade.trading_mode == "paper",
                    Trade.settled.is_(True),
                    Trade.pnl.is_(None),
                    Trade.timestamp < stuck_cutoff,
                )
                .all()
            )
            if stuck_paper:
                from backend.core.settlement.settlement_helpers import (
                    calculate_pnl,
                    total_loss_settlement_value,
                )

                for t in stuck_paper:
                    loss_settlement_value = total_loss_settlement_value(t.direction)
                    try:
                        t.pnl = calculate_pnl(t, loss_settlement_value)
                    except Exception:
                        t.pnl = round(
                            -(float(t.entry_price or 0.0) * float(t.size or 0.0)), 2
                        )
                    t.result = "loss"
                    t.settlement_value = loss_settlement_value
                    t.settlement_time = datetime.now(timezone.utc)
                    t.settlement_source = "force_closed_unresolved"
                db.commit()
                logger.info(
                    f"[stale_trade_cleanup] Force-settled {len(stuck_paper)} "
                    f"stuck paper trades as loss (>5 days, market never resolved), "
                    f"total pnl=${sum(t.pnl or 0.0 for t in stuck_paper):+.2f}"
                )
    except Exception as e:
        logger.warning(f"[stale_trade_cleanup] Failed: {e}")

    # --- 5-min binary trade cleanup (1h threshold) ---
    # These strategies trade short-duration binaries (5-min windows) but the
    # main settlement loop waits 12-72h before force-settling. The duplicate
    # guard blocks new entries until old ones are settled.
    _BINARY_5M_STRATEGIES = frozenset({
        "crypto_oracle", "cex_pm_leadlag",
        "crypto_micro", "hft_scalper", "probability_arb",
    })
    try:
        with get_db_session() as db:
            now = datetime.now(timezone.utc)
            cutoff_1h = now - timedelta(hours=1)
            stale_binaries = (
                db.query(Trade)
                .filter(
                    Trade.settled.is_(False),
                    Trade.timestamp < cutoff_1h,
                    Trade.strategy.in_(list(_BINARY_5M_STRATEGIES)),
                )
                .all()
            )
            if stale_binaries:
                for t in stale_binaries:
                    t.settled = True
                    t.result = "expired_unresolved"
                    t.pnl = 0.0
                    t.settlement_value = 0.0
                    t.settlement_time = now
                    t.settlement_source = "5min_binary_cleanup"
                db.commit()
                logger.warning(
                    "[stale_trade_cleanup] Auto-settled {} stale 5-min binary trades (>1h) "
                    "from strategies: {}",
                    len(stale_binaries),
                    {t.strategy for t in stale_binaries},
                )
    except Exception as e:
        logger.warning(f"[stale_trade_cleanup] 5-min binary cleanup failed: {e}")