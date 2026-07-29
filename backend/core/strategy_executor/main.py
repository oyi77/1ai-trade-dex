"""Strategy execution orchestrator — routes decisions to the correct execution path."""

import asyncio
from typing import Optional

from loguru import logger

from backend.core.strategy_executor.locks import (
    _ensure_semaphore,
    _get_asset_lock,
    _get_rate_limiter,
)
from backend.core.strategy_executor.helpers import _BotStateLockRetry, _lock_retry_delay

MAX_LOCK_RETRY_ATTEMPTS = 4

# Maker-first execution config (overridable via settings).
MAKER_WAIT_SECONDS = float(getattr(
    __import__("backend.config", fromlist=["settings"]).settings,
    "MAKER_WAIT_SECONDS", 5.0,
))
MAKER_POLL_INTERVAL_SECONDS = float(getattr(
    __import__("backend.config", fromlist=["settings"]).settings,
    "MAKER_POLL_INTERVAL_SECONDS", 2.0,
))
MAKER_FIRST_ENABLED = bool(getattr(
    __import__("backend.config", fromlist=["settings"]).settings,
    "MAKER_FIRST_ENABLED", True,
))


def _hft_enabled() -> bool:
    """Check if HFT fast path is globally enabled."""
    from backend.config import settings
    return getattr(settings, "HFT_ENABLED", True)


async def execute_decision(
    decision: dict, strategy_name: str, mode: str, db=None
) -> Optional[dict]:
    """Execute a single trade decision.

    Acquires async coordination locks, then offloads sync DB-heavy work to
    a thread pool (paper/testnet/Kalshi) or stays on event loop (live CLOB).
    """
    # HFT fast path: bypass standard flow for low-latency strategies
    if _hft_enabled() and (decision.get("hft") or decision.get("hft_candidate")):
        from backend.core import strategy_executor as _se

        return await _se._execute_hft_path(decision, strategy_name, mode, db)

    asset_key = decision.get("condition_id") or decision.get("slug") or strategy_name
    market_id = str(asset_key)

    # LIVE_STRATEGY_ALLOWLIST gate
    if mode == "live":
        from backend.core.strategy_executor import _cfg

        allowed = _cfg("LIVE_STRATEGY_ALLOWLIST", [])
        if allowed and strategy_name not in allowed:
            logger.warning(
                f"[execute_decision] {strategy_name} NOT in LIVE_STRATEGY_ALLOWLIST, "
                f"blocking live execution (paper mode continues)"
            )
            return None

    # Rate limit check
    await _get_rate_limiter().wait_and_acquire(market_id)

    asset_lock = await _get_asset_lock(str(asset_key))
    async with _ensure_semaphore():
        async with asset_lock:
            # Fallback: resolve missing token_id for live CLOB execution
            if mode == "live" and not decision.get("token_id"):
                from backend.core import strategy_executor as _se

                slug = str(decision.get("market_ticker", "") or "")
                resolved = await _se._resolve_token_id_from_gamma(slug)
                if resolved:
                    logger.info(
                        f"[{strategy_name}] Resolved missing token_id={resolved} for "
                        f"slug '{slug}' via Gamma API"
                    )
                    decision["token_id"] = resolved
                else:
                    logger.warning(
                        f"[{strategy_name}] Live mode but no token_id in decision for "
                        f"{slug} — falling back to paper path"
                    )

            is_live_clob = (
                mode == "live"
                and not (
                    decision.get("market_ticker", "").startswith("KX")
                    or decision.get("platform") == "kalshi"
                )
                and decision.get("token_id") is not None
            )

            for lock_attempt in range(MAX_LOCK_RETRY_ATTEMPTS):
                try:
                    if not is_live_clob:
                        from backend.core import strategy_executor as _se

                        if db is not None:
                            return _se._execute_decision_paper_or_kalshi(
                                decision, strategy_name, mode, db,
                            )
                        return await asyncio.to_thread(
                            _se._execute_decision_paper_or_kalshi,
                            decision, strategy_name, mode,
                        )

                    from backend.core import strategy_executor as _se

                    return await _se._execute_decision_live_clob(
                        decision, strategy_name, mode, db,
                    )
                except _BotStateLockRetry:
                    if lock_attempt >= MAX_LOCK_RETRY_ATTEMPTS - 1:
                        logger.opt(exception=True).error(
                            "[strategy_executor.execute_decision] BotState lock "
                            "contention persisted after {} attempts for {}",
                            MAX_LOCK_RETRY_ATTEMPTS,
                            decision.get("market_ticker", ""),
                        )
                        return None

                    delay = _lock_retry_delay(lock_attempt)
                    logger.warning(
                        "[strategy_executor.execute_decision] BotState lock contention "
                        "for {}; retrying in {:.2f}s (attempt {}/{})",
                        decision.get("market_ticker", ""),
                        delay,
                        lock_attempt + 1,
                        MAX_LOCK_RETRY_ATTEMPTS,
                    )
                    await asyncio.sleep(delay)


async def execute_quote(
    decision: dict, strategy_name: str, mode: str, db=None
) -> dict | None:
    """Execute a QUOTE decision from market_maker — places GTC limit orders on both sides."""
    from backend.models.database import Trade as QT, BotState as QBS
    from backend.db.utils import get_db_session
    from backend.config import settings as s
    from contextlib import nullcontext

    if not getattr(s, "HFT_ENABLED", False):
        logger.debug("[execute_quote] HFT_ENABLED=false, skipping quote")
        return None

    market_ticker = decision.get("market_ticker", "")
    bid_price = decision.get("bid_price")
    ask_price = decision.get("ask_price")
    bid_size = decision.get("bid_size", 0)
    ask_size = decision.get("ask_size", 0)

    if not bid_price or not ask_price or bid_size <= 0 or ask_size <= 0:
        logger.warning(
            "[execute_quote] Invalid quote: bid=%s/%s ask=%s/%s",
            bid_price, bid_size, ask_price, ask_size,
        )
        return None

    owns_db = db is None
    ctx = get_db_session() if owns_db else nullcontext(db)

    with ctx as db:
        try:
            asset_key = (
                decision.get("condition_id") or decision.get("slug") or strategy_name
            )
            asset_lock = await _get_asset_lock(str(asset_key))
            async with _ensure_semaphore():
                async with asset_lock:
                    state = db.query(QBS).filter_by(mode=mode).first()
                    if not state or not state.is_running:
                        return None

                    results = []
                    for side, price, size, direction in [
                        ("bid", bid_price, bid_size, "YES"),
                        ("ask", ask_price, ask_size, "NO"),
                    ]:
                        trade = QT(
                            market_ticker=market_ticker,
                            strategy=strategy_name,
                            trading_mode=mode,
                            direction=direction,
                            entry_price=price,
                            size=size,
                            role="maker",
                            status="open",
                            confidence=decision.get("confidence", 0.5),
                        )
                        db.add(trade)
                        results.append({
                            "side": side,
                            "direction": direction,
                            "price": price,
                            "size": size,
                            "role": "maker",
                        })
                        logger.info(
                            "[execute_quote] %s %s %s $%.2f @ %.3f (maker)",
                            strategy_name, side, direction, size, price,
                        )

                    db.commit()
                    return {"quote_placed": True, "orders": results}

        except Exception as e:
            logger.opt(exception=True).error("[execute_quote] Failed: %s", e)
            try:
                db.rollback()
            except Exception:
                logger.exception(
                    "[execute_quote] db.rollback failed after quote execution failure"
                )
            return None


async def execute_decisions(
    decisions: list[dict], strategy_name: str, mode: str, db=None
) -> list[dict]:
    """Execute multiple decisions, respecting per-scan limits."""
    MAX_TRADES_PER_CYCLE = 6
    results = []
    for d in decisions[:MAX_TRADES_PER_CYCLE]:
        if d.get("decision") == "QUOTE":
            result = await execute_quote(d, strategy_name, mode, db=db)
        else:
            result = await execute_decision(d, strategy_name, mode, db=db)
        if result:
            results.append(result)
    return results


class StrategyExecutor:
    """Namespace for execute_decision / execute_decisions."""

    execute_decision = staticmethod(execute_decision)
    execute_decisions = staticmethod(execute_decisions)
    execute_quote = staticmethod(execute_quote)