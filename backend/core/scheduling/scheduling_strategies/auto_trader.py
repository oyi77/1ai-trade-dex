"""Auto-trader and auto-redeem jobs."""

import asyncio

from loguru import logger
from sqlalchemy import func

from backend.config import settings
from backend.models.database import BotState, Signal, Trade

from ._helpers import _get_bankroll_for_mode


async def auto_trader_job(mode: str):
    """Run AutoTrader against unexecuted signals when AUTO_TRADER_ENABLED."""
    await asyncio.sleep(0)  # yield control to event loop
    from backend.core.scheduling.scheduler import log_event

    if not settings.AUTO_TRADER_ENABLED:
        return

    def _read_auto_trader_signals():
        from backend.db.utils import get_db_session

        with get_db_session() as db:
            state = db.query(BotState).filter_by(mode=mode).first()
            if not state or not state.is_running:
                return None
            bankroll = _get_bankroll_for_mode(state, mode)
            signals = (
                db.query(Signal)
                .filter(
                    Signal.executed.is_(False),
                    Signal.execution_mode == mode,
                )
                .order_by(Signal.timestamp.desc())
                .limit(settings.AUTO_TRADER_BATCH_SIZE)
                .all()
            )
            if not signals:
                return {
                    "bankroll": bankroll,
                    "signal_rows": [],
                    "current_exposure": 0.0,
                }
            current_exposure = float(
                db.query(func.coalesce(func.sum(Trade.size), 0.0))
                .filter(
                    Trade.settled.is_(False),
                    Trade.trading_mode == mode,
                )
                .scalar()
                or 0.0
            )
            signal_rows = [
                {
                    "id": sig.id,
                    "market_ticker": sig.market_ticker,
                    "direction": sig.direction,
                    "confidence": sig.confidence,
                    "edge": sig.edge,
                    "model_probability": sig.model_probability,
                    "token_id": sig.token_id,
                    "track_name": sig.track_name,
                }
                for sig in signals
            ]
            return {
                "bankroll": bankroll,
                "signal_rows": signal_rows,
                "current_exposure": current_exposure,
            }

    try:
        from backend.core.auto_trader import AutoTrader
        from backend.core.risk.risk_manager import RiskManager
        from backend.core.wallet.registry import get_wallet_router
        from backend.data.polymarket_clob import clob_from_settings

        trader = AutoTrader(
            RiskManager(),
            clob_factory=clob_from_settings,
            wallet_router=get_wallet_router(),
        )
        data = await asyncio.to_thread(_read_auto_trader_signals)
        if data is None:
            return
        bankroll = data["bankroll"]
        signal_rows = data["signal_rows"]
        current_exposure = data["current_exposure"]
        signal_ids = [sig["id"] for sig in signal_rows]
        if not signal_rows:
            log_event("info", f"[{mode.upper()}] AutoTrader cycle: no pending signals")
            return

        executed = 0
        queued = 0
        skipped = 0
        processed_signal_ids = []
        for sig in signal_rows:
            token_id = sig["token_id"]
            market_ticker = sig["market_ticker"]
            if (
                mode in ("testnet", "live")
                and not token_id
                and not market_ticker.startswith("KX")
            ):
                processed_signal_ids.append(sig["id"])
                skipped += 1
                continue

            signal_dict = {
                "market_id": market_ticker,
                "market_ticker": market_ticker,
                "side": "BUY" if (sig["direction"] or "yes") == "yes" else "SELL",
                "confidence": sig["confidence"] or 0.0,
                "size": min(
                    settings.MAX_TRADE_SIZE, bankroll * settings.KELLY_FRACTION
                ),
                "price": sig["model_probability"] or 0.5,
                "token_id": token_id,
                "strategy": sig["track_name"] or "unknown",
            }
            result = await trader.execute_signal(
                signal_dict,
                bankroll=bankroll,
                current_exposure=current_exposure,
                mode=mode,
            )
            if result.executed:
                from backend.core.strategy_executor import execute_decision

                trade_size = min(
                    settings.MAX_TRADE_SIZE,
                    (bankroll or 100.0) * settings.KELLY_FRACTION,
                )
                decision = {
                    "market_ticker": market_ticker,
                    "direction": sig["direction"] or "yes",
                    "size": trade_size,
                    "entry_price": sig["model_probability"] or 0.5,
                    "edge": sig["edge"] or 0.0,
                    "confidence": sig["confidence"] or 0.0,
                    "model_probability": sig["model_probability"],
                    "token_id": token_id,
                    "platform": (
                        "kalshi"
                        if market_ticker.startswith("KX")
                        else settings.DEFAULT_VENUE
                    ),
                }
                source_strategy = sig["track_name"]
                if not source_strategy:
                    logger.warning(
                        f"Signal {sig['id']} has no track_name — skipping auto-trader"
                    )
                    skipped += 1
                    processed_signal_ids.append(sig["id"])
                    continue
                exec_result = await execute_decision(
                    decision, source_strategy, mode=mode
                )
                if exec_result is not None:
                    processed_signal_ids.append(sig["id"])
                    executed += 1
                    current_exposure += trade_size
            elif result.pending_approval:
                queued += 1
            else:
                # Mark as processed even when skipped/rejected so we don't
                # re-attempt the same stale signal every cycle.
                processed_signal_ids.append(sig["id"])
                skipped += 1

        if processed_signal_ids:

            def _mark_signals_executed():
                from backend.db.utils import get_db_session

                with get_db_session() as db:
                    db.query(Signal).filter(Signal.id.in_(processed_signal_ids)).update(
                        {Signal.executed: True}, synchronize_session=False
                    )
                    db.commit()

            await asyncio.to_thread(_mark_signals_executed)

        log_event(
            "info",
            f"AutoTrader cycle: executed={executed} queued={queued} skipped={skipped}",
        )
        if len(signal_ids) >= 5 and executed == 0 and queued == 0:
            logger.warning(
                "[ALERT] auto_trader processed %d signals but created 0 trade attempts — check filters",
                len(signal_ids),
            )
    except asyncio.CancelledError:
        logger.info(f"auto_trader_job({mode}) cancelled during shutdown")
        return
    except Exception as e:
        log_event("error", f"auto_trader_job error: {e}")


async def auto_redeem_job() -> None:
    """Automatically redeem resolved Polymarket positions when explicitly enabled."""
    await asyncio.sleep(0)  # yield control to event loop
    from backend.core.scheduling.scheduler import log_event

    if not getattr(settings, "AUTO_REDEEM_ENABLED", False):
        return

    wallet = (
        getattr(settings, "POLYMARKET_BUILDER_ADDRESS", None)
        or getattr(settings, "POLYMARKET_WALLET_ADDRESS", None)
        or ""
    )
    private_key = getattr(settings, "POLYMARKET_PRIVATE_KEY", None) or ""

    if not wallet or not private_key:
        log_event(
            "warning",
            "Auto-redeem skipped: POLYMARKET_BUILDER_ADDRESS/POLYMARKET_WALLET_ADDRESS or POLYMARKET_PRIVATE_KEY not set",
        )
        return

    dry_run = bool(getattr(settings, "AUTO_REDEEM_DRY_RUN", True))
    db_scan = bool(getattr(settings, "AUTO_REDEEM_DB_SCAN_ENABLED", True))
    timeout_seconds = float(getattr(settings, "AUTO_REDEEM_TIMEOUT_SECONDS", 120.0))

    try:
        from backend.core.settlement.auto_redeem import redeem_all_redeemable

        result = await asyncio.wait_for(
            asyncio.to_thread(
                redeem_all_redeemable,
                wallet=wallet,
                private_key=private_key,
                builder_api_key=getattr(settings, "POLYMARKET_BUILDER_API_KEY", None),
                builder_secret=getattr(settings, "POLYMARKET_BUILDER_SECRET", None),
                builder_passphrase=getattr(
                    settings, "POLYMARKET_BUILDER_PASSPHRASE", None
                ),
                dry_run=dry_run,
                db_scan=db_scan,
            ),
            timeout=timeout_seconds,
        )
        status = "dry-run" if dry_run else "executed"
        log_event(
            "info",
            f"Auto-redeem {status}: attempted={result.total_attempted} redeemed={result.total_redeemed} failed={result.total_failed}",
            {
                "attempted": result.total_attempted,
                "redeemed": result.total_redeemed,
                "failed": result.total_failed,
                "dry_run": dry_run,
                "errors": result.errors,
            },
        )
    except TimeoutError:
        log_event("error", f"Auto-redeem timed out after {timeout_seconds:.0f}s")
    except Exception as e:
        log_event("error", f"Auto-redeem failed: {e}")
        logger.exception("auto_redeem_job failed")
