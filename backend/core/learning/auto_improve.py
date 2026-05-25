"""DEPRECATED: Use backend.core.auto_improve instead.

Auto-improvement job for PolyEdge — learns from trade outcomes and
auto-applies optimizer suggestions with guardrails and rollback.

This module will be removed in a future release.
"""



from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from backend.config import settings
from backend.models.database import SessionLocal, Trade, DecisionLog
from backend.ai.optimizer import ParameterOptimizer
from backend.clients.bigbrain import BigBrainClient, get_bigbrain

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from loguru import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MIN_CONFIDENCE_FOR_AUTO_APPLY = settings.AUTO_IMPROVE_MIN_CONFIDENCE
MAX_PARAM_CHANGE_FRACTION = settings.AUTO_IMPROVE_MAX_PARAM_CHANGE
ROLLBACK_TRADE_WINDOW = settings.AUTO_IMPROVE_ROLLBACK_WINDOW
ROLLBACK_PERF_DEGRADATION_THRESHOLD = settings.AUTO_IMPROVE_ROLLBACK_DEGRADATION

# Tunable parameters that auto-improve may modify
TUNABLE_PARAMS = (
    "kelly_fraction",
    "min_edge_threshold",
    "max_trade_size",
    "daily_loss_limit",
)

# Per-strategy rollback state. Each key is a strategy name; value has the same
# shape as the old single-dict: previous_values, applied_values, applied_at,
# pre_change_win_rate, pre_change_pnl, trade_count_at_apply.
# Using a per-strategy dict allows independent rollback windows for each
# strategy instead of serialising all improvements through a single slot.
_last_param_change: dict[str, dict] = {}
_param_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Guardrail helpers
# ---------------------------------------------------------------------------


def _confidence_to_float(confidence: object) -> float:
    if isinstance(confidence, (int, float)):
        return float(confidence)
    mapping = {"low": 0.3, "medium": 0.6, "high": 0.9}
    return mapping.get(str(confidence).lower().strip(), 0.0)


def clamp_to_bounds(current_value: float, suggested_value: float) -> float:
    if current_value <= 0:
        return 0.0
    lower = current_value * (1.0 - MAX_PARAM_CHANGE_FRACTION)
    upper = current_value * (1.0 + MAX_PARAM_CHANGE_FRACTION)
    clamped = max(lower, min(suggested_value, upper))
    return round(max(clamped, 0.0), 6)


def validate_and_clamp_params(current: dict, suggested: dict) -> dict:
    clamped = {}
    for key in TUNABLE_PARAMS:
        cur = current.get(key)
        sug = suggested.get(key)
        if cur is None or sug is None:
            continue
        clamped[key] = clamp_to_bounds(float(cur), float(sug))
    return clamped


def apply_params_to_settings(params: dict, target_settings=None) -> dict:
    target = target_settings or settings
    previous: dict = {}
    for key in TUNABLE_PARAMS:
        if key not in params:
            continue
        attr = key.upper()  # e.g. "kelly_fraction" -> "KELLY_FRACTION"
        if hasattr(target, attr):
            previous[key] = getattr(target, attr)
            # Pydantic v2 Settings are generally frozen; use object.__setattr__
            object.__setattr__(target, attr, params[key])
    return previous


def rollback_params(previous_values: dict, target_settings=None) -> None:
    target = target_settings or settings
    for key, value in previous_values.items():
        attr = key.upper()
        if hasattr(target, attr):
            object.__setattr__(target, attr, value)


def _get_current_params(target_settings=None) -> dict:
    target = target_settings or settings
    return {key: getattr(target, key.upper(), None) for key in TUNABLE_PARAMS}


# ---------------------------------------------------------------------------
# Rolling rollback checker
# ---------------------------------------------------------------------------


def check_rollback_needed(
    db: Session, target_settings=None, bigbrain=None, strategy: str = "__global__"
) -> bool:
    """Check whether the most recent param change for *strategy* should be rolled back.

    Pass ``strategy`` to scope the rollback check to a specific strategy.
    The legacy ``"__global__"`` key is used when no strategy is specified so
    that callers that don't pass a strategy still work correctly.
    """
    global _last_param_change
    with _param_lock:
        if strategy not in _last_param_change:
            return False

        applied_at = _last_param_change[strategy].get("applied_at")
        if applied_at is None:
            return False
        snapshot = dict(_last_param_change[strategy])

    # Gather settled trades since the change was applied (scoped to strategy when possible)
    trade_filter = [
        Trade.settled.is_(True),
        Trade.settlement_time >= applied_at,
        Trade.result.in_(("win", "loss")),
    ]
    if strategy != "__global__" and hasattr(Trade, "strategy"):
        trade_filter.append(Trade.strategy == strategy)

    post_trades = (
        db.query(Trade)
        .filter(*trade_filter)
        .order_by(Trade.settlement_time.asc())
        .limit(ROLLBACK_TRADE_WINDOW)
        .all()
    )

    if len(post_trades) < ROLLBACK_TRADE_WINDOW:
        # Not enough data yet — keep current params
        return False

    wins = sum(1 for t in post_trades if t.result == "win")
    post_win_rate = wins / len(post_trades) if post_trades else 0.0
    pre_win_rate = snapshot.get("pre_change_win_rate", 0.0)

    # Absolute degradation check: post_win_rate < pre_win_rate * (1 - threshold)
    if pre_win_rate > 0 and post_win_rate < pre_win_rate * (
        1.0 - ROLLBACK_PERF_DEGRADATION_THRESHOLD
    ):
        logger.warning(
            f"[auto_improve] Rolling back parameters: post-change win rate "
            f"{post_win_rate:.1%} vs pre-change {pre_win_rate:.1%} "
            f"(>{ROLLBACK_PERF_DEGRADATION_THRESHOLD:.0%} degradation)"
        )
        rollback_params(snapshot["previous_values"], target_settings)

        if bigbrain:
            rollback_msg = (
                f"⚠️ AUTO-IMPROVE ROLLBACK: Performance degraded from "
                f"{pre_win_rate:.1%} to {post_win_rate:.1%}. "
                f"Restored: {json.dumps(snapshot['previous_values'])}"
            )
            try:
                task = asyncio.create_task(
                    bigbrain.send_alert(rollback_msg, level="warning")
                )
                task.add_done_callback(
                    lambda t: (
                        t.exception() if not t.cancelled() and t.exception() else None
                    )
                )
            except Exception as e:
                logger.debug("Failed to send rollback alert: %s", e)

        # Audit trail
        try:
            from backend.models.database import log_audit

            log_audit(
                action="auto_improve_rollback",
                actor="auto_improve",
                details={
                    "pre_win_rate": pre_win_rate,
                    "post_win_rate": post_win_rate,
                    "restored_values": snapshot["previous_values"],
                    "rolled_back_values": snapshot["applied_values"],
                },
            )
        except Exception as e:
            logger.debug("Audit log for rollback failed: %s", e)

        with _param_lock:
            _last_param_change.pop(strategy, None)
        return True

    # Performance acceptable — clear the pending rollback check
    logger.info(
        f"[auto_improve] Post-change performance OK for '{strategy}' "
        f"({post_win_rate:.1%} vs {pre_win_rate:.1%}), keeping new params"
    )
    with _param_lock:
        _last_param_change.pop(strategy, None)
    return False


# ---------------------------------------------------------------------------
# Main job
# ---------------------------------------------------------------------------


async def auto_improve_job():
    """
    Weekly maintenance job:
    1. Writes recent trade outcomes and market insights to BigBrain
    2. Auto-applies high-confidence param suggestions (confidence >= MIN_CONFIDENCE_FOR_AUTO_APPLY)
    3. Runs StrategyEvolver proposals
    """
    global _last_param_change

    from backend.core.scheduler import log_event

    log_event("info", "Running auto-improvement analysis...")

    bigbrain = get_bigbrain()

    try:
        with SessionLocal() as db:
            optimizer = ParameterOptimizer(settings)
            analysis = optimizer.analyze_performance(db, trade_limit=100)

        log_event(
            "data",
            f"Performance: {analysis['total_trades']} trades, {analysis['win_rate']:.1%} win rate, ${analysis['pnl']:.2f} P&L",
        )

        await _write_outcomes_to_brain(db, bigbrain)

        if analysis["total_trades"] >= 30:
            suggestions = await optimizer.get_suggestions(db)
            if suggestions.get("status") == "ok":
                params = suggestions.get("suggestions", {})
                reasoning = params.get("reasoning", "No reasoning provided")
                confidence = params.get("confidence", "low")

                try:
                    from backend.core.experiment_tracker import experiment_tracker

                    exp_id = experiment_tracker.create_experiment(
                        db,
                        "auto_improve",
                        params,
                        notes=f"AI suggested ({confidence}): {reasoning[:200]}",
                    )
                    experiment_tracker.record_metrics(
                        db,
                        exp_id,
                        {
                            "win_rate": analysis["win_rate"],
                            "pnl": analysis["pnl"],
                            "total_trades": analysis["total_trades"],
                            "confidence": confidence,
                        },
                    )
                except Exception as e:
                    logger.debug("Experiment tracking failed: %s", e)

                await bigbrain.write_strategy_insight(
                    strategy="parameter_optimizer",
                    insight=f"Suggested: edge={params.get('min_edge_threshold')}, kelly={params.get('kelly_fraction')}, reasoning={reasoning}",
                    confidence=confidence,
                )

                await bigbrain.write_parameter_tuning(
                    params={
                        "kelly_fraction": params.get("kelly_fraction"),
                        "min_edge_threshold": params.get("min_edge_threshold"),
                        "max_trade_size": params.get("max_trade_size"),
                        "daily_loss_limit": params.get("daily_loss_limit"),
                    },
                    win_rate=analysis["win_rate"],
                    pnl=analysis["pnl"],
                    confidence=confidence,
                )

                log_event(
                    "success",
                    f"Auto-improve: {confidence} confidence - {reasoning[:100]}",
                )

                conf_float = _confidence_to_float(confidence)
                if conf_float >= MIN_CONFIDENCE_FOR_AUTO_APPLY:
                    # Use "__global__" as the strategy key when no specific strategy
                    # is targeted (legacy behaviour). Per-strategy callers should
                    # pass their own key to allow independent rollback windows.
                    _strategy_key = "__global__"
                    with _param_lock:
                        pending = _strategy_key in _last_param_change
                    if pending:
                        logger.info(
                            "Auto-improve: skipping apply for '%s' — pending change awaiting rollback review",
                            _strategy_key,
                        )
                    else:
                        current = _get_current_params()
                        clamped = validate_and_clamp_params(current, params)
                        if clamped:
                            previous = apply_params_to_settings(clamped)
                            with _param_lock:
                                _last_param_change[_strategy_key] = {
                                    "previous_values": previous,
                                    "applied_values": clamped,
                                    "applied_at": datetime.now(timezone.utc),
                                    "pre_change_win_rate": analysis.get(
                                        "win_rate", 0.0
                                    ),
                                    "pre_change_pnl": analysis.get("pnl", 0.0),
                                    "trade_count_at_apply": analysis.get(
                                        "total_trades", 0
                                    ),
                                }
                            logger.info(
                                "Auto-improve applied %d param(s) (confidence=%.2f): %s",
                                len(clamped),
                                conf_float,
                                list(clamped.keys()),
                            )
        else:
            log_event(
                "info",
                f"Auto-improve: only {analysis['total_trades']} trades (need 30), skipping param optimization",
            )

        await _write_market_insights(db, bigbrain)

        try:
            from backend.agents.autoresearch.evolver import StrategyEvolver

            evolver = StrategyEvolver()
            proposals = await evolver.run_evolution_cycle(db)
            if proposals:
                log_event(
                    "info",
                    f"Evolution: {len(proposals)} proposal(s) generated — "
                    "approve via POST /api/agents/experiments/{id}/approve",
                )
        except Exception as _e:
            logger.debug("[auto_improve] StrategyEvolver skipped: %s", _e)

        log_event("success", "Auto-improvement cycle complete")

    except Exception as e:
        log_event("error", f"Auto-improve error: {e}")
        logger.exception("Error in auto_improve_job")
    finally:
        await bigbrain.close()


async def _write_outcomes_to_brain(db: Session, bigbrain: BigBrainClient) -> None:
    """Write recent trade outcomes to BigBrain."""
    try:
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)

        trades = (
            db.query(Trade)
            .filter(
                Trade.settled.is_(True),
                Trade.settlement_time >= week_ago,
            )
            .limit(50)
            .all()
        )

        for trade in trades:
            await bigbrain.write_trade_outcome(
                strategy=trade.strategy or "unknown",
                market=trade.market_ticker,
                direction=trade.direction,
                result=trade.result or "unknown",
                pnl=trade.pnl or 0.0,
                edge=trade.edge_at_entry or 0.0,
                confidence=getattr(trade, "confidence", 0.5),
                timestamp=(
                    trade.settlement_time.isoformat() if trade.settlement_time else None
                ),
            )
    except Exception as e:
        logger.warning("Failed to write outcomes to brain: %s", e)


async def _write_market_insights(db: Session, bigbrain: BigBrainClient) -> None:
    """Write market analysis insights to BigBrain."""
    try:
        recent_signals = (
            db.query(DecisionLog)
            .filter(
                DecisionLog.decision == "BUY",
            )
            .order_by(DecisionLog.created_at.desc())
            .limit(20)
            .all()
        )

        for sig in recent_signals:
            if sig.signal_data:
                try:
                    data = (
                        json.loads(sig.signal_data)
                        if isinstance(sig.signal_data, str)
                        else sig.signal_data
                    )
                    prob = data.get("model_probability", 0.5)
                    edge = data.get("edge", 0.0)
                    direction = data.get("direction", "up")

                    await bigbrain.write_signal_analysis(
                        market=sig.market_ticker,
                        direction=direction,
                        probability=prob,
                        edge=edge,
                        reasoning=f"Signal from {sig.strategy}",
                    )
                except Exception as e:
                    logger.debug(
                        "Skipping signal %s in insight writing: %s",
                        getattr(sig, "strategy", "unknown"),
                        e,
                    )
    except Exception as e:
        logger.warning("Failed to write market insights: %s", e)
