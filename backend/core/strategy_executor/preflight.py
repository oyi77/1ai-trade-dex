"""Pre-trade preflight checks — shared by paper and live execution paths."""

import math
from datetime import datetime, timedelta, timezone
from typing import Optional

from loguru import logger
from sqlalchemy import func, and_, or_

from backend.models.database import Trade, BotState, StrategyConfig


def _fetch_live_pusd_balance_sync() -> float:
    """Fetch real PUSD balance from Polymarket CLOB for live mode."""
    try:
        from py_clob_client_v2 import BalanceAllowanceParams, AssetType
        from backend.data.polymarket_clob import clob_from_settings

        clob = clob_from_settings(mode="live")
        if not clob._clob_client:
            logger.warning("[strategy_executor] _fetch_live_pusd_balance_sync: ClobClient not initialised")
            return 0.0
        params = BalanceAllowanceParams(
            asset_type=AssetType.COLLATERAL,
            signature_type=clob.signature_type if clob.signature_type else None,
        )
        result = clob._clob_client.get_balance_allowance(params)
        pusd_balance = int(result.get("balance", 0)) / 1e6
        logger.debug(f"[strategy_executor] Live PUSD balance: ${pusd_balance:.2f}")
        return pusd_balance
    except Exception as e:
        logger.warning(f"[strategy_executor] Failed to fetch live PUSD balance: {e}")
        return 0.0


def _get_current_exposure(db, trading_mode: str = None) -> float:
    """Sum of open (unsettled) trade sizes for current trading mode."""
    mode = trading_mode or _cfg("TRADING_MODE", "paper")
    result = (
        db.query(func.coalesce(func.sum(Trade.size), 0.0))
        .filter(Trade.settled.is_(False), Trade.trading_mode == mode)
        .scalar()
    )
    return float(result or 0.0)


def _fetch_orderbook_depth(token_id: str | None) -> float:
    """Sync read of orderbook depth from the in-memory cache."""
    if not token_id:
        return 0.0
    try:
        from backend.data.orderbook_cache import get_orderbook_cache

        cache = get_orderbook_cache()
        book = cache._cache.get(token_id)
        max_age = getattr(cache, "_max_age", 30.0)
        if book and book.age_seconds < max_age:
            bid_depth = sum(
                float(b.get("price", 0)) * float(b.get("size", 0)) for b in book.bids
            )
            ask_depth = sum(
                float(a.get("price", 0)) * float(a.get("size", 0)) for a in book.asks
            )
            return bid_depth + ask_depth
    except Exception as e:
        logger.debug("orderbook depth fetch failed for %s: %s", token_id, e)
    return 0.0


def _pre_trade_safety_checks(
    db, strategy_name: str, mode: str, bankroll: float, size: float
) -> Optional[str]:
    """Run hard safety guards before any trade executes.

    Returns None if all checks pass, or a rejection reason string.
    """

    from backend.core.strategy_executor import _cfg

    # 1. Per-trade max loss
    max_trade_pct = float(_cfg("PER_TRADE_MAX_LOSS_PCT", 0.05))
    clob_min_order = float(_cfg("MIN_ORDER_USDC", 5.0))
    pct_limit = bankroll * max_trade_pct
    effective_floor = max(pct_limit, clob_min_order) if bankroll > 0 else pct_limit
    hard_cap = bankroll * 0.20 if bankroll > 0 else float("inf")
    effective_limit = min(effective_floor, hard_cap)
    if bankroll > 0 and size > effective_limit:
        return (
            f"per-trade size ${size:.2f} > limit ${effective_limit:.2f} "
            f"(5% floor=${pct_limit:.2f}, CLOB min=${clob_min_order:.2f}, "
            f"20% hard cap=${hard_cap:.2f})"
        )

    # 2. Daily max trades per strategy
    max_daily_trades = int(_cfg("MAX_DAILY_TRADES_PER_STRATEGY", 50))
    if max_daily_trades > 0:
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        daily_count = (
            db.query(func.count(Trade.id))
            .filter(
                Trade.strategy == strategy_name,
                Trade.trading_mode == mode,
                Trade.timestamp >= today_start,
            )
            .scalar()
            or 0
        )
        if daily_count >= max_daily_trades:
            return (
                f"daily trade limit reached: {daily_count}/{max_daily_trades} "
                f"trades today for {strategy_name}"
            )

    # 3. Portfolio circuit breaker
    max_portfolio_dd = float(_cfg("PORTFOLIO_CIRCUIT_BREAKER_PCT", 0.20))
    if max_portfolio_dd > 0:
        state = db.query(BotState).filter_by(mode=mode).first()
        if state:
            try:
                initial = (
                    getattr(state, f"{mode}_initial_bankroll", None)
                    or getattr(state, "paper_initial_bankroll", None)
                    or float(_cfg("INITIAL_BANKROLL", 1000.0))
                )
            except (TypeError, ValueError):
                initial = bankroll
            current = bankroll
            if mode == "live":
                pusd = _fetch_live_pusd_balance_sync()
                if pusd > 0:
                    current = pusd
            if initial and initial > 0:
                dd_pct = (initial - current) / initial
                if dd_pct > max_portfolio_dd:
                    logger.critical(
                        f"[CIRCUIT BREAKER] Portfolio down {dd_pct * 100:.1f}% "
                        f"from initial ${initial:.2f} (current ${current:.2f}). "
                        f"Disabling ALL {mode} strategies."
                    )
                    from backend.core.strategy_health import disable_for_rehab

                    all_configs = (
                        db.query(StrategyConfig)
                        .filter(StrategyConfig.enabled.is_(True))
                        .all()
                    )
                    for cfg in all_configs:
                        disable_for_rehab(cfg)
                    db.commit()
                    return (
                        f"PORTFOLIO CIRCUIT BREAKER: down {dd_pct:.1%} from "
                        f"${initial:.2f} (current ${current:.2f}) — all strategies disabled"
                    )
    return None


def _preflight_checks(
    db,
    decision: dict,
    strategy_name: str,
    mode: str,
    attempt_recorder,
) -> Optional[object]:
    """All pre-execution checks shared by paper and live paths.

    Returns _PreflightResult if approved, None if blocked/rejected.
    """
    from backend.core.strategy_executor import _cfg
    import dataclasses as _dc


    @_dc.dataclass
    class _PreflightResult:
        adjusted_size: float
        bankroll: float
        risk_reason: str
        market_end_date: Optional[datetime]
        fee: Optional[float]
        context: object
        attempt_recorder: object

    from backend.core.mode_context import get_context

    market_ticker = decision.get("market_ticker", "")
    direction = decision.get("direction", "")
    order_side = str(decision.get("side") or decision.get("decision") or "BUY").upper()
    force_unwind = bool(decision.get("force_unwind"))
    size = float(decision.get("size", 0.0))
    confidence = float(decision.get("confidence", 0.0))
    market_end_date_str = decision.get("market_end_date")
    entry_price = float(decision.get("entry_price", 0.5))
    model_probability = float(decision.get("model_probability", confidence))

    market_end_date = None
    if market_end_date_str:
        try:
            market_end_date = datetime.fromisoformat(
                market_end_date_str.replace("Z", "+00:00")
            )
        except (ValueError, TypeError):
            logger.exception(
                f"[{strategy_name}] failed to parse market_end_date: {market_ticker}"
            )

    # 1. Execution context
    try:
        context = get_context(mode)
    except KeyError:
        logger.error(f"[{strategy_name}] No execution context for mode: {mode}")
        attempt_recorder.record_blocked(
            f"No execution context for mode: {mode}",
            phase="context",
            reason_code="BLOCKED_NO_EXECUTION_CONTEXT",
        )
        db.commit()
        return None

    # 1b. Emergency kill switch check
    from pathlib import Path

    kill_switch_path = Path(__file__).parent.parent.parent / ".kill_switch"
    if kill_switch_path.exists() and mode == "live":
        logger.critical(f"[KILL SWITCH] Emergency stop active - .kill_switch file found")
        attempt_recorder.record_blocked(
            "Emergency kill switch active (.kill_switch file exists)",
            phase="preflight",
            reason_code="BLOCKED_KILL_SWITCH",
        )
        db.commit()
        return None

    # 2. Duplicate execution block (same-strategy only — cross-strategy positions allowed)
    event_slug = decision.get("slug") or decision.get("event_slug")
    filters = [
        or_(Trade.settled.is_(False), Trade.pnl.is_(None)),
        Trade.trading_mode == mode,
    ]
    if event_slug:
        filters.append(
            and_(
                Trade.market_ticker == market_ticker,
                Trade.event_slug == event_slug,
            )
        )
    else:
        filters.append(Trade.market_ticker == market_ticker)
    existing = db.query(Trade).filter(*filters, Trade.strategy == strategy_name).first()
    if existing:
        logger.info(f"[{strategy_name}] Duplicate execution blocked for {market_ticker}/{event_slug}")
        attempt_recorder.record_blocked(
            "Duplicate open position for market",
            phase="preflight",
            reason_code="BLOCKED_DUPLICATE_OPEN_POSITION",
            trade_id=existing.id,
        )
        db.commit()
        return None

    # 3. Bot running check
    state = db.query(BotState).filter_by(mode=mode).first()
    if not state or not state.is_running:
        logger.info(f"[{strategy_name}] Bot not running, skipping decision for {market_ticker}")
        strategy_config = (
            db.query(StrategyConfig).filter_by(strategy_name=strategy_name).first()
        )
        if not strategy_config or not strategy_config.enabled:
            logger.warning(f"[{strategy_name}] Skipping execution as strategy is disabled or missing")
            attempt_recorder.record_blocked(
                "Strategy disabled or missing",
                phase="preflight",
                reason_code="BLOCKED_STRATEGY_DISABLED",
            )
            db.commit()
            return None
        attempt_recorder.record_blocked(
            "Bot not running for selected mode",
            phase="preflight",
            reason_code="BLOCKED_BOT_NOT_RUNNING",
        )
        db.commit()
        return None

    # 4. Cooldown after consecutive losses
    # Skip cooldown for strategies re-enabled after bug fixes (old pre-fix losses don't count)
    import json as _cfg_json

    _strategy_params = {}
    try:
        from backend.models.strategy_db import StrategyConfig as _SC

        _scfg = db.query(_SC).filter(_SC.strategy_name == strategy_name).first()
        if _scfg and _scfg.params:
            _strategy_params = _cfg_json.loads(_scfg.params)
    except Exception:
        pass
    if _strategy_params.get("re_enabled_after_fix"):
        cooldown_losses = 0  # skip cooldown for re-enabled strategies
    else:
        cooldown_losses = int(_cfg("COOLDOWN_CONSECUTIVE_LOSSES", 3) or 3)

    cooldown_minutes = int(_cfg("COOLDOWN_MINUTES", 60) or 60)
    if cooldown_losses > 0:
        from datetime import timedelta as _td

        recent_trades = (
            db.query(Trade)
            .filter(
                Trade.strategy == strategy_name,
                Trade.settled.is_(True),
                Trade.trading_mode == mode,
            )
            .order_by(Trade.settlement_time.desc())
            .limit(cooldown_losses)
            .all()
        )
        if len(recent_trades) >= cooldown_losses:
            all_losses = all(t.result == "loss" for t in recent_trades)
            if all_losses:
                last_loss_time = recent_trades[0].settlement_time
                if last_loss_time and last_loss_time.tzinfo is None:
                    last_loss_time = last_loss_time.replace(tzinfo=timezone.utc)
                cooldown_until = last_loss_time + _td(minutes=cooldown_minutes)
                now_utc = datetime.now(timezone.utc)
                if now_utc < cooldown_until:
                    remaining = (cooldown_until - now_utc).total_seconds() / 60.0
                    logger.info(
                        f"[{strategy_name}] Cooldown active: {cooldown_losses} consecutive losses, "
                        f"pausing for {remaining:.1f} more minutes"
                    )
                    attempt_recorder.record_blocked(
                        f"Cooldown: {cooldown_losses} consecutive losses, {remaining:.1f}min remaining",
                        phase="cooldown",
                        reason_code="BLOCKED_COOLDOWN",
                    )
                    db.commit()
                    return None

    # 5. Bankroll
    if mode == "paper":
        bankroll = state.paper_bankroll if state.paper_bankroll is not None else 0.0
    elif mode == "testnet":
        bankroll = state.testnet_bankroll if state.testnet_bankroll is not None else 0.0
    else:
        from backend.core.strategy_executor import _fetch_live_pusd_balance_sync as _fx
        pusd_balance = _fx()
        if pusd_balance > 0:
            bankroll = pusd_balance
            logger.debug(f"[LIVE] Using real PUSD balance: ${pusd_balance:.2f}")
        else:
            bankroll = (
                state.bankroll
                if state.bankroll is not None
                else _cfg("INITIAL_BANKROLL", 1000.0)
            )
    if bankroll < 0:
        logger.warning(
            "[%s] Negative bankroll ($%.2f) detected; flooring to $0.00",
            mode.upper(), bankroll,
        )
        bankroll = 0.0

    # 5b. Live mode minimum balance check
    clob_min = float(_cfg("MIN_ORDER_USDC", 1.0))
    if mode == "live" and bankroll < clob_min and order_side == "BUY" and not force_unwind:
        logger.warning(
            f"[{strategy_name}] Live trade rejected: bankroll ${bankroll:.2f} below ${clob_min:.2f} minimum"
        )
        attempt_recorder.record_blocked(
            f"Bankroll ${bankroll:.2f} below ${clob_min:.2f} minimum",
            phase="preflight",
            reason_code="BLOCKED_INSUFFICIENT_BALANCE",
        )
        db.commit()
        return None

    # 6. Hard safety guards
    safety_block = _pre_trade_safety_checks(db, strategy_name, mode, bankroll, size)
    if safety_block is not None:
        logger.warning(f"[{strategy_name}] Safety guard blocked: {safety_block}")
        attempt_recorder.record_blocked(
            safety_block,
            phase="safety_guard",
            reason_code="BLOCKED_SAFETY_GUARD",
        )
        db.commit()
        return None

    # 7. Risk manager
    from backend.core.risk.risk_manager import RiskManager

    current_exposure = _get_current_exposure(db, trading_mode=mode)
    attempt_recorder.update(
        phase="risk_gate",
        status="RISK_EVALUATING",
        reason_code="RISK_EVALUATING",
        reason="Risk manager evaluating trade",
        bankroll=bankroll,
        current_exposure=current_exposure,
        factors_json={
            "bankroll": bankroll,
            "current_exposure": current_exposure,
            "requested_size": size,
            "confidence": confidence,
            "market_ticker": market_ticker,
            "mode": mode,
        },
    )

    if force_unwind:
        from types import SimpleNamespace as _SimpleNamespace

        risk = _SimpleNamespace(
            allowed=True,
            adjusted_size=size,
            reason="Force unwind bypasses entry risk gate",
        )
    else:
        from backend.core.mode_context import get_context

        ctx = get_context(mode)
        risk_manager = ctx.risk_manager if ctx else RiskManager()
        risk = risk_manager.validate_trade(
            size=size,
            current_exposure=current_exposure,
            bankroll=bankroll,
            confidence=confidence,
            market_ticker=market_ticker,
            db=db,
            mode=mode,
            strategy_name=strategy_name,
            direction=direction if direction else None,
            market_price=entry_price,
            signal_win_rate=model_probability,
        )
    if not risk.allowed:
        logger.info(f"[{strategy_name}] Risk rejected {market_ticker}: {risk.reason}")
        attempt_recorder.record_rejected(
            risk.reason,
            phase="risk_gate",
            risk_allowed=False,
            risk_reason=risk.reason,
            adjusted_size=risk.adjusted_size,
        )
        db.commit()
        return None

    adjusted_size = risk.adjusted_size
    attempt_recorder.update(
        status="RISK_APPROVED",
        phase="risk_gate",
        reason_code="RISK_APPROVED",
        reason="Risk gate approved trade",
        risk_allowed=True,
        risk_reason=risk.reason,
        adjusted_size=adjusted_size,
    )

    # 8. Min size
    min_size = _cfg("MIN_ORDER_USDC", 5.0)
    if entry_price > 0 and entry_price < 1.0:
        min_shares = math.ceil(1.0 / entry_price)
        clob_min_usdc = min_shares * entry_price * 1.02
        min_size = max(min_size, clob_min_usdc)
    if adjusted_size < min_size:
        if bankroll > 0 and min_size <= bankroll * 0.95:
            logger.info(
                f"[{mode.upper()}][{strategy_name}] Bumping {market_ticker} "
                f"size ${adjusted_size:.2f} → ${min_size:.2f} to meet CLOB min"
            )
            adjusted_size = min_size
        else:
            logger.info(
                f"[{mode.upper()}][{strategy_name}] Order rejected for {market_ticker}: "
                f"Size ${adjusted_size:.2f} below minimum ${min_size:.2f} (entry_price={entry_price})"
            )
            attempt_recorder.record_rejected(
                f"Size ${adjusted_size:.2f} below minimum ${min_size:.2f}",
                phase="sizing",
                reason_code="REJECTED_ORDER_TOO_SMALL",
                adjusted_size=adjusted_size,
            )
            db.commit()
            return None

    # 9. Stale market filter
    if market_end_date is not None:
        _now = datetime.now(timezone.utc)
        _time_to_resolution = (market_end_date - _now).total_seconds() / 60.0
        _is_short_lived = (
            "-5m-" in str(market_ticker)
            or "-15m-" in str(market_ticker)
            or _time_to_resolution < 30.0
        )
        _stale_threshold = 1.0 if _is_short_lived else 60.0
        if _time_to_resolution < _stale_threshold:
            logger.info(
                f"[{strategy_name}] Stale market blocked: {market_ticker} resolves in "
                f"{_time_to_resolution:.1f} min (< {_stale_threshold:.0f} min threshold)"
            )
            attempt_recorder.record_rejected(
                f"Stale market: {market_ticker} resolves in {_time_to_resolution:.1f} min",
                phase="stale_market",
                reason_code="REJECTED_STALE_MARKET",
                adjusted_size=adjusted_size,
            )
            db.commit()
            return None

    # 10. Duplicate market guard (same strategy+ticker)
    _cooldown_sec = _cfg("DUPLICATE_TRADE_COOLDOWN_SEC", 60)
    _cutoff = datetime.now(timezone.utc) - timedelta(seconds=_cooldown_sec)
    _dup_query = db.query(Trade).filter(
        Trade.strategy == strategy_name,
        Trade.market_ticker == market_ticker,
        Trade.timestamp >= _cutoff,
    )
    if mode:
        _dup_query = _dup_query.filter(Trade.trading_mode == mode)
    _recent_dup = None if force_unwind else _dup_query.first()
    if _recent_dup is not None:
        logger.warning(
            f"[{strategy_name}] Duplicate blocked: already traded {market_ticker} "
            f"(any direction) within {_cooldown_sec} sec (trade #{_recent_dup.id})"
        )
        attempt_recorder.record_rejected(
            f"Duplicate: {market_ticker} already traded in last {_cooldown_sec} sec",
            phase="duplicate_guard",
            reason_code="REJECTED_DUPLICATE_MARKET",
            adjusted_size=adjusted_size,
        )
        db.commit()
        return None

    # 11. Per-market position cap (same-strategy only — cross-strategy is fine)
    _existing_open = (
        db.query(Trade)
        .filter(
            Trade.market_ticker == market_ticker,
            or_(Trade.settled.is_(False), Trade.pnl.is_(None)),
            Trade.trading_mode == mode,
            Trade.strategy == strategy_name,
        )
        .first()
    )
    if _existing_open is not None and not force_unwind:
        logger.warning(
            f"[{strategy_name}] Duplicate position blocked: already have open position "
            f"on {market_ticker} (trade #{_existing_open.id})"
        )
        attempt_recorder.record_rejected(
            f"Duplicate position: already have position on {market_ticker}",
            phase="position_cap",
            reason_code="REJECTED_DUPLICATE_POSITION",
            adjusted_size=adjusted_size,
        )
        db.commit()
        return None

    return _PreflightResult(
        adjusted_size=adjusted_size,
        bankroll=bankroll,
        risk_reason=risk.reason,
        market_end_date=market_end_date,
        fee=None,
        context=context,
        attempt_recorder=attempt_recorder,
    )