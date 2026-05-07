"""Rejection Learner — feeds TradeAttempt rejection patterns back into strategy parameters.

Reads blocked/rejected TradeAttempts, identifies systematic rejection causes per strategy,
and generates targeted proposals to fix the root cause.

Example: if strategy X keeps hitting ORDER_TOO_SMALL, this module proposes increasing
kelly_fraction or lowering min_edge threshold so future trades exceed the minimum order size.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

from sqlalchemy.sql import func

from backend.models.database import SessionLocal, TradeAttempt, StrategyConfig, StrategyProposal

logger = logging.getLogger("trading_bot.rejection_learner")

LOOKBACK_DAYS = 7
MIN_REJECTIONS = 10

REJECTION_ADJUSTMENTS = {
    "REJECTED_DRAWDOWN_BREAKER": {
        "description": "Strategy hitting drawdown limit too often — reduce position sizing",
        "param_adjustments": {"kelly_fraction": 0.7},
        "root_cause_checks": ["constant_model_probability", "always_positive_edge"],
    },
    "REJECTED_LOW_CONFIDENCE": {
        "description": "Confidence below threshold — lower confidence requirement or improve signal quality",
        "param_adjustments": {"confidence_threshold": 0.85},
        "root_cause_checks": ["flat_confidence", "zero_edge"],
    },
    "REJECTED_MAX_EXPOSURE": {
        "description": "Portfolio over-concentrated — reduce max exposure per trade",
        "param_adjustments": {"max_position_fraction": 0.7, "max_total_exposure": 0.85},
        "root_cause_checks": [],
    },
    "REJECTED_ORDER_TOO_SMALL": {
        "description": "Trade size below exchange minimum — increase kelly fraction or minimum edge",
        "param_adjustments": {"kelly_fraction": 1.8, "min_edge": 0.04},
        "root_cause_checks": [],
    },
    "BLOCKED_DUPLICATE_OPEN_POSITION": {
        "description": "Repeated duplicate positions — increase cooldown or reduce per-market frequency",
        "param_adjustments": {"cooldown_minutes": 1.5},
        "root_cause_checks": [],
    },
    "REJECTED_BROKER_ORDER": {
        "description": "Exchange rejecting orders — check token/liquidity/size issues",
        "param_adjustments": {"slippage_buffer": 1.5},
        "root_cause_checks": [],
    },
    "BLOCKED_NO_EXECUTION_CONTEXT": {
        "description": "Bot not in proper state to execute — check orchestrator lifecycle",
        "param_adjustments": {},
        "root_cause_checks": [],
    },
}


ROOT_CAUSE_SIGNATURES = {
    "constant_model_probability": {
        "pattern": "All decisions have identical model_probability",
        "description": "Model probability is hardcoded or not varying — strategy fabricates fake edge",
    },
    "always_positive_edge": {
        "pattern": "Edge is always positive regardless of market conditions",
        "description": "Edge calculation is biased — always signals BUY with inflated edge",
    },
    "flat_confidence": {
        "pattern": "Confidence never varies across decisions",
        "description": "Confidence is constant — signal quality metric is broken",
    },
    "zero_edge": {
        "pattern": "Edge at entry is zero or near-zero",
        "description": "No real edge detected — strategy cannot identify mispriced markets",
    },
}


def detect_root_causes(strategy_name: str) -> list[dict]:
    """Analyze DecisionLog for root-cause anomalies that rejection patterns can't see.

    Checks for: constant probability, always-positive edge, flat confidence.
    Returns list of {root_cause, description, severity}.
    """
    db = SessionLocal()
    causes = []
    try:
        from backend.models.database import DecisionLog
        from sqlalchemy.sql import func

        decisions = (
            db.query(DecisionLog)
            .filter(DecisionLog.strategy == strategy_name)
            .order_by(DecisionLog.created_at.desc())
            .limit(50)
            .all()
        )

        if len(decisions) < 5:
            return causes

        probs = []
        edges = []
        confs = []

        for d in decisions:
            data = d.signal_data if d.signal_data else {}
            if isinstance(data, str):
                import json as _json
                try:
                    data = _json.loads(data)
                except Exception:
                    data = {}

            if "model_probability" in data:
                probs.append(float(data["model_probability"]))
            if "edge" in data:
                edges.append(float(data["edge"]))
            if "confidence" in data:
                confs.append(float(data["confidence"]))

        if len(probs) >= 5:
            unique_probs = set(round(p, 4) for p in probs)
            if len(unique_probs) == 1:
                causes.append({
                    "root_cause": "constant_model_probability",
                    "value": list(unique_probs)[0],
                    "description": ROOT_CAUSE_SIGNATURES["constant_model_probability"]["description"],
                    "severity": "critical",
                    "sample_size": len(probs),
                })

        if len(edges) >= 5:
            all_positive = all(e > 0 for e in edges)
            avg_edge = sum(edges) / len(edges)
            if all_positive and avg_edge > 0.3:
                causes.append({
                    "root_cause": "always_positive_edge",
                    "value": round(avg_edge, 4),
                    "description": ROOT_CAUSE_SIGNATURES["always_positive_edge"]["description"],
                    "severity": "critical",
                    "sample_size": len(edges),
                })

        if len(confs) >= 5:
            unique_confs = set(round(c, 2) for c in confs)
            if len(unique_confs) == 1:
                causes.append({
                    "root_cause": "flat_confidence",
                    "value": list(unique_confs)[0],
                    "description": ROOT_CAUSE_SIGNATURES["flat_confidence"]["description"],
                    "severity": "high",
                    "sample_size": len(confs),
                })

        return causes
    except Exception as e:
        logger.warning(f"Root cause detection failed for {strategy_name}: {e}")
        return causes
    finally:
        db.close()


def analyze_rejections(lookback_days: int = LOOKBACK_DAYS) -> Dict[str, Dict]:
    """Analyze TradeAttempt rejections grouped by (strategy, reason_code).

    Returns dict keyed by strategy_name, each containing:
    - top rejection reasons with counts
    - total rejection count
    - total attempt count (for context)
    """
    from backend.db.utils import get_db_session
    try:
        with get_db_session() as db:
            since = datetime.now(timezone.utc) - timedelta(days=lookback_days)

            rejected = db.query(
                TradeAttempt.strategy,
                TradeAttempt.reason_code,
                TradeAttempt.status,
                func.count(TradeAttempt.id).label("cnt"),
                func.avg(TradeAttempt.requested_size).label("avg_size"),
                func.avg(TradeAttempt.confidence).label("avg_conf"),
                func.avg(TradeAttempt.edge).label("avg_edge"),
            ).filter(
                TradeAttempt.status.in_(["BLOCKED", "REJECTED", "FAILED"]),
                TradeAttempt.created_at >= since,
            ).group_by(
                TradeAttempt.strategy,
                TradeAttempt.reason_code,
                TradeAttempt.status,
            ).order_by(func.count(TradeAttempt.id).desc()).all()

            total_attempts = db.query(func.count(TradeAttempt.id)).filter(
                TradeAttempt.created_at >= since
            ).scalar() or 1

            strategies: Dict[str, Dict] = {}
            for row in rejected:
                strat = row.strategy or "unknown"
                if strat not in strategies:
                    strategies[strat] = {
                        "rejections": [],
                        "total_rejections": 0,
                        "total_attempts": total_attempts,
                    }
                strategies[strat]["rejections"].append({
                    "reason_code": row.reason_code,
                    "status": row.status,
                    "count": row.cnt,
                    "avg_size": float(row.avg_size or 0),
                    "avg_conf": float(row.avg_conf or 0),
                    "avg_edge": float(row.avg_edge or 0),
                })
                strategies[strat]["total_rejections"] += row.cnt

            return strategies
    except Exception as e:
        logger.warning(f"Rejection analysis failed: {e}")
        return {}


def generate_rejection_proposals(min_rejections: int = MIN_REJECTIONS) -> List[str]:
    """Generate StrategyProposals from systematic rejection patterns + root cause analysis."""
    db = SessionLocal()
    created: List[str] = []
    try:
        analysis = analyze_rejections()

        for strategy_name, data in analysis.items():
            if data["total_rejections"] < min_rejections:
                continue

            root_causes = detect_root_causes(strategy_name)
            for rc in root_causes:
                if rc["severity"] == "critical":
                    proposal = StrategyProposal(
                        strategy_name=strategy_name,
                        change_details={"_root_cause": rc["root_cause"]},
                        expected_impact=(
                            f"ROOT CAUSE DETECTED: {rc['description']} "
                            f"(value={rc['value']}, samples={rc['sample_size']}). "
                            f"Requires code-level fix, not parameter adjustment."
                        ),
                        admin_decision="pending",
                        status="pending",
                        auto_promotable=False,
                        proposed_params={},
                    )
                    db.add(proposal)
                    created.append(f"{strategy_name}: ROOT_CAUSE:{rc['root_cause']}")

            for rej in data["rejections"]:
                reason_code = rej["reason_code"]
                count = rej["count"]
                if count < min_rejections:
                    continue

                adjustment = REJECTION_ADJUSTMENTS.get(reason_code)
                if not adjustment:
                    continue

                param_changes = adjustment["param_adjustments"]
                if not param_changes:
                    continue

                cfg = db.query(StrategyConfig).filter(
                    StrategyConfig.strategy_name == strategy_name
                ).first()

                raw_params = cfg.params if cfg and cfg.params else "{}"
                try:
                    import json as _json
                    current_params = _json.loads(raw_params) if isinstance(raw_params, str) else (raw_params or {})
                except Exception:
                    current_params = {}
                proposed = {}
                for key, multiplier in param_changes.items():
                    current_val = current_params.get(key)
                    if current_val is not None and isinstance(current_val, (int, float)):
                        proposed[key] = round(float(current_val) * multiplier, 6)
                    elif current_val is None:
                        proposed[key] = round(multiplier, 6)

                if not proposed:
                    continue

                proposal = StrategyProposal(
                    strategy_name=strategy_name,
                    change_details=proposed,
                    expected_impact=(
                        f"{adjustment['description']} "
                        f"(reason: {reason_code}, occurrences: {count}, "
                        f"avg_size: {rej['avg_size']:.2f}, avg_conf: {rej['avg_conf']:.2f})"
                    ),
                    admin_decision="pending",
                    status="pending",
                    auto_promotable=True,
                    proposed_params=proposed,
                )
                db.add(proposal)
                created.append(f"{strategy_name}: {reason_code} → {proposed}")

        if created:
            db.commit()
            logger.info(f"Rejection learner: created {len(created)} proposals from rejection patterns")
    except Exception as e:
        logger.warning(f"Rejection proposal generation failed: {e}")
        db.rollback()
    finally:
        db.close()

    return created