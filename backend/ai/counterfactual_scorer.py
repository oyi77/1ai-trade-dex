"""Counterfactual Scorer: scores blocked signals against actual market resolutions.

Every signal that RiskManager or preflight blocks is a FREE prediction data point.
We know the strategy's direction, confidence, and edge — we just need to check
whether the market resolved in that direction.

This engine:
1. Ingests BLOCKED/REJECTED TradeAttempts and SKIP DecisionLogs into BlockedSignalCounterfactual
2. Scores them against MarketOutcome table + Gamma API
3. Computes hypothetical WR and PnL
4. Aggregates insights by strategy, block_reason, edge_range, confidence_range
5. Feeds insights into Meta-Learner for risk gate calibration
"""

import json
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from backend.models.database import SessionLocal, TradeAttempt, DecisionLog, Signal
from backend.models.historical_data import MarketOutcome
from backend.models.outcome_tables import BlockedSignalCounterfactual, CounterfactualInsight
from backend.config import settings

from loguru import logger
DIRECTION_UP_ALIASES = {"up", "yes", "UP", "YES", "buy", "BUY"}
DIRECTION_DOWN_ALIASES = {"down", "no", "DOWN", "NO", "sell", "SELL"}

MIN_AGE_BEFORE_SCORING_HOURS = 1
MAX_GAMMA_API_CALLS_PER_RUN = 50


def _normalize_direction(direction: str | None) -> str:
    if not direction:
        return "unknown"
    d = direction.strip().lower()
    if d in {"up", "yes", "buy"}:
        return "up"
    if d in {"down", "no", "sell"}:
        return "down"
    return d


def _direction_won(direction: str, settlement_value: float) -> bool:
    d = _normalize_direction(direction)
    if d == "up":
        return settlement_value >= 0.5
    if d == "down":
        return settlement_value < 0.5
    return False


def _compute_hypothetical_pnl(direction: str, entry_price: float, size: float, settlement_value: float) -> float:
    d = _normalize_direction(direction)
    if d == "up":
        if settlement_value >= 0.5:
            return size * (1.0 - entry_price)
        else:
            return -size * entry_price
    if d == "down":
        if settlement_value < 0.5:
            return size * entry_price
        else:
            return -size * (1.0 - entry_price)
    return 0.0


def ingest_blocked_attempts(db: Session) -> int:
    existing_source_ids = set(
        row[0] for row in db.query(BlockedSignalCounterfactual.source_id).filter(
            BlockedSignalCounterfactual.source_table == "trade_attempt"
        ).all()
    )

    blocked = db.query(TradeAttempt).filter(
        TradeAttempt.status.in_(["BLOCKED", "REJECTED"]),
        ~TradeAttempt.id.in_(existing_source_ids),
    ).order_by(TradeAttempt.created_at.desc()).limit(500).all()

    ingested = 0
    for attempt in blocked:
        signal_data = {}
        if attempt.signal_data:
            try:
                signal_data = json.loads(attempt.signal_data)
            except (json.JSONDecodeError, TypeError):
                pass

        entry_price = attempt.entry_price or signal_data.get("market_price")
        model_prob = signal_data.get("model_probability")
        if model_prob is None and attempt.confidence:
            model_prob = attempt.confidence

        row = BlockedSignalCounterfactual(
            source_table="trade_attempt",
            source_id=attempt.id,
            strategy=attempt.strategy,
            market_ticker=attempt.market_ticker,
            direction=attempt.direction,
            confidence=attempt.confidence,
            edge=attempt.edge,
            model_probability=model_prob,
            market_price=entry_price,
            requested_size=attempt.requested_size,
            entry_price=entry_price,
            block_reason=attempt.reason,
            block_reason_code=attempt.reason_code,
            block_phase=attempt.phase,
            signal_blocked_at=attempt.created_at,
        )
        db.add(row)
        ingested += 1

    if ingested:
        db.flush()
    return ingested


def ingest_skipped_decisions(db: Session) -> int:
    existing_source_ids = set(
        row[0] for row in db.query(BlockedSignalCounterfactual.source_id).filter(
            BlockedSignalCounterfactual.source_table == "decision_log"
        ).all()
    )

    skipped = db.query(DecisionLog).filter(
        DecisionLog.decision == "SKIP",
        ~DecisionLog.id.in_(existing_source_ids),
    ).order_by(DecisionLog.created_at.desc()).limit(500).all()

    ingested = 0
    for dl in skipped:
        signal_data = {}
        if dl.signal_data:
            try:
                signal_data = json.loads(dl.signal_data)
            except (json.JSONDecodeError, TypeError):
                pass

        direction = signal_data.get("direction")
        edge = signal_data.get("edge")
        model_prob = signal_data.get("model_probability")
        market_price = signal_data.get("market_probability")

        reason_code = "SKIP"
        reason_text = dl.reason or ""
        if "auto-deny" in reason_text.lower():
            reason_code = "SKIP_AUTO_DENY"
        elif "confidence" in reason_text.lower():
            reason_code = "SKIP_LOW_CONFIDENCE"
        elif "auto-approve" in reason_text.lower():
            reason_code = "SKIP_AUTO_APPROVE_THRESHOLD"

        row = BlockedSignalCounterfactual(
            source_table="decision_log",
            source_id=dl.id,
            strategy=dl.strategy,
            market_ticker=dl.market_ticker,
            direction=direction,
            confidence=dl.confidence,
            edge=edge,
            model_probability=model_prob,
            market_price=market_price,
            block_reason=dl.reason,
            block_reason_code=reason_code,
            block_phase="approval_gate",
            signal_blocked_at=dl.created_at,
        )
        db.add(row)
        ingested += 1

    if ingested:
        db.flush()
    return ingested


async def _resolve_from_market_outcome(db: Session, market_ticker: str) -> Optional[tuple[str, float]]:
    outcome = db.query(MarketOutcome).filter(
        MarketOutcome.market_ticker == market_ticker
    ).order_by(MarketOutcome.resolved_at.desc()).first()

    if outcome and outcome.outcome:
        outcome_str = outcome.outcome.lower().strip()
        final_price = outcome.final_price if outcome.final_price is not None else (1.0 if outcome_str in ("up", "yes") else 0.0)
        actual_dir = "up" if final_price >= 0.5 else "down"
        return actual_dir, final_price
    return None


async def _resolve_from_signal_calibration(db: Session, market_ticker: str) -> Optional[tuple[str, float]]:
    signal = db.query(Signal).filter(
        Signal.market_ticker == market_ticker,
        Signal.actual_outcome.isnot(None),
    ).order_by(Signal.settled_at.desc()).first()

    if signal and signal.actual_outcome:
        actual_dir = _normalize_direction(signal.actual_outcome)
        sv = signal.settlement_value if signal.settlement_value is not None else (1.0 if actual_dir == "up" else 0.0)
        return actual_dir, sv
    return None


async def _resolve_from_gamma_api(market_ticker: str) -> Optional[tuple[str, float]]:
    is_condition_id = market_ticker.startswith("0x") and len(market_ticker) >= 40
    is_token_id = market_ticker.isdigit() and len(market_ticker) >= 20

    search_params = []
    if is_condition_id:
        search_params.append({"condition_id": market_ticker, "closed": "true", "limit": 1})
    elif is_token_id:
        search_params.append({"clob_token_ids": market_ticker, "closed": "true", "limit": 1})
        search_params.append({"clob_token_ids": market_ticker, "closed": "false", "limit": 1})
    else:
        search_params.append({"slug": market_ticker, "limit": 1})
        search_params.append({"id": market_ticker, "limit": 1})

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            for params in search_params:
                try:
                    resp = await client.get(
                        f"{settings.GAMMA_API_URL}/markets",
                        params=params,
                        timeout=10.0,
                    )
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    if not data or not isinstance(data, list) or len(data) == 0:
                        continue

                    market = data[0]
                    if not (market.get("closed") or market.get("resolved")):
                        continue

                    outcome_prices = market.get("outcomePrices")
                    if outcome_prices:
                        prices = [float(p) for p in outcome_prices]
                        yes_price = prices[0] if len(prices) > 0 else 0.5
                        actual_dir = "up" if yes_price >= 0.5 else "down"
                        return actual_dir, yes_price
                except (httpx.TimeoutException, httpx.ConnectTimeout):
                    continue
    except Exception as e:
        logger.debug(f"Gamma API resolution failed for {market_ticker}: {e}")
    return None


async def score_unresolved(db: Session) -> dict:
    unscored = db.query(BlockedSignalCounterfactual).filter(
        BlockedSignalCounterfactual.scored.is_(False),
        BlockedSignalCounterfactual.direction.isnot(None),
    ).order_by(BlockedSignalCounterfactual.signal_blocked_at.desc()).limit(500).all()

    if not unscored:
        return {"scored": 0, "won": 0, "lost": 0, "no_resolution": 0}

    scored_count = 0
    won_count = 0
    lost_count = 0
    no_resolution = 0
    gamma_calls = 0
    resolution_cache: dict[str, tuple[str, float]] = {}

    for row in unscored:
        ticker = row.market_ticker

        if ticker in resolution_cache:
            result = resolution_cache[ticker]
        else:
            result = await _resolve_from_market_outcome(db, ticker)

            if result is None:
                result = await _resolve_from_signal_calibration(db, ticker)

            if result is None and gamma_calls < MAX_GAMMA_API_CALLS_PER_RUN:
                result = await _resolve_from_gamma_api(ticker)
                if result:
                    gamma_calls += 1

            if result:
                resolution_cache[ticker] = result

        if result is None:
            no_resolution += 1
            continue

        actual_dir, settlement_value = result
        row.actual_outcome = actual_dir
        row.settlement_value = settlement_value
        row.would_have_won = _direction_won(row.direction or "unknown", settlement_value)
        if not row.resolution_source:
            row.resolution_source = "market_outcome"
        row.resolved_at = datetime.now(timezone.utc)

        if row.entry_price and row.requested_size:
            row.hypothetical_pnl = _compute_hypothetical_pnl(
                row.direction or "unknown",
                row.entry_price,
                row.requested_size,
                settlement_value,
            )

        row.scored = True
        row.scored_at = datetime.now(timezone.utc)

        if row.would_have_won:
            won_count += 1
        else:
            lost_count += 1
        scored_count += 1

    db.flush()
    return {"scored": scored_count, "won": won_count, "lost": lost_count, "no_resolution": no_resolution}


def compute_insights(db: Session) -> dict:
    scored = db.query(BlockedSignalCounterfactual).filter(
        BlockedSignalCounterfactual.scored.is_(True),
    ).all()

    if not scored:
        return {"insights": 0}

    old_insights = db.query(CounterfactualInsight).all()
    for old in old_insights:
        db.delete(old)
    db.flush()

    buckets: dict[tuple[str, str], list] = {}

    for row in scored:
        for dim, val in _get_dimensions(row):
            key = (dim, val)
            buckets.setdefault(key, []).append(row)

    created = 0
    for (dim, val), rows in buckets.items():
        wins = sum(1 for r in rows if r.would_have_won)
        losses = sum(1 for r in rows if r.would_have_won is False)
        total = wins + losses
        wr = wins / total if total > 0 else 0.0
        hyp_pnl = sum(r.hypothetical_pnl or 0.0 for r in rows)
        lost = sum(r.hypothetical_pnl or 0.0 for r in rows if r.would_have_won)

        min_ts = min(r.signal_blocked_at for r in rows if r.signal_blocked_at)
        max_ts = max(r.signal_blocked_at for r in rows if r.signal_blocked_at)

        insight = CounterfactualInsight(
            dimension=dim,
            dimension_value=val,
            total_blocked=len(rows),
            total_would_win=wins,
            total_would_lose=losses,
            counterfactual_wr=wr,
            hypothetical_total_pnl=round(hyp_pnl, 2),
            lost_profit=round(lost, 2),
            sample_period_start=min_ts,
            sample_period_end=max_ts,
        )
        db.add(insight)
        created += 1

    db.flush()
    return {"insights": created}


def _get_dimensions(row: BlockedSignalCounterfactual) -> list[tuple[str, str]]:
    dims = []

    if row.strategy:
        dims.append(("strategy", row.strategy))
    if row.block_reason_code:
        dims.append(("block_reason", row.block_reason_code))
    if row.edge is not None:
        if row.edge < 0.05:
            dims.append(("edge_range", "low_<0.05"))
        elif row.edge < 0.10:
            dims.append(("edge_range", "medium_0.05-0.10"))
        else:
            dims.append(("edge_range", "high_>0.10"))
    if row.confidence is not None:
        if row.confidence < 0.5:
            dims.append(("confidence_range", "low_<0.50"))
        elif row.confidence < 0.7:
            dims.append(("confidence_range", "medium_0.50-0.70"))
        else:
            dims.append(("confidence_range", "high_>0.70"))

    return dims


def get_risk_calibration_recommendations(db: Session) -> list[dict]:
    insights = db.query(CounterfactualInsight).filter(
        CounterfactualInsight.dimension.in_(["strategy", "block_reason"]),
        CounterfactualInsight.total_blocked >= 10,
    ).all()

    recommendations = []
    for ins in insights:
        if ins.counterfactual_wr > 0.55 and ins.lost_profit > 0:
            recommendations.append({
                "dimension": ins.dimension,
                "value": ins.dimension_value,
                "counterfactual_wr": round(ins.counterfactual_wr, 3),
                "lost_profit": ins.lost_profit,
                "total_blocked": ins.total_blocked,
                "recommendation": f"{ins.dimension_value} blocked signals win {ins.counterfactual_wr:.0%} "
                                    f"— ${ins.lost_profit:.2f} in missed profit. Consider loosening this gate.",
            })
        elif ins.counterfactual_wr < 0.35:
            recommendations.append({
                "dimension": ins.dimension,
                "value": ins.dimension_value,
                "counterfactual_wr": round(ins.counterfactual_wr, 3),
                "hypothetical_pnl": ins.hypothetical_total_pnl,
                "total_blocked": ins.total_blocked,
                "recommendation": f"{ins.dimension_value} blocked signals lose {1 - ins.counterfactual_wr:.0%} "
                                    f"— gate is correctly filtering. Keep as is.",
            })

    return recommendations


def get_strategy_counterfactual_stats(db: Session, strategy: str) -> dict:
    rows = db.query(BlockedSignalCounterfactual).filter(
        BlockedSignalCounterfactual.strategy == strategy,
        BlockedSignalCounterfactual.scored.is_(True),
    ).all()

    if not rows:
        return {"strategy": strategy, "total_scored": 0}

    wins = sum(1 for r in rows if r.would_have_won)
    total = len(rows)
    hyp_pnl = sum(r.hypothetical_pnl or 0.0 for r in rows)
    lost = sum(r.hypothetical_pnl or 0.0 for r in rows if r.would_have_won)

    by_reason: dict[str, dict] = {}
    for r in rows:
        rc = r.block_reason_code or "UNKNOWN"
        entry = by_reason.setdefault(rc, {"total": 0, "wins": 0, "lost_profit": 0.0})
        entry["total"] += 1
        if r.would_have_won:
            entry["wins"] += 1
            entry["lost_profit"] += r.hypothetical_pnl or 0.0

    return {
        "strategy": strategy,
        "total_scored": total,
        "would_have_won": wins,
        "would_have_lost": total - wins,
        "counterfactual_wr": round(wins / total, 3) if total > 0 else 0.0,
        "hypothetical_total_pnl": round(hyp_pnl, 2),
        "lost_profit_from_blocking": round(lost, 2),
        "by_block_reason": {k: {**v, "wr": round(v["wins"] / v["total"], 3) if v["total"] > 0 else 0.0} for k, v in by_reason.items()},
    }


async def run_counterfactual_cycle(db: Optional[Session] = None) -> dict:
    _owned = db is None
    db = db or SessionLocal()
    try:
        ingested_attempts = ingest_blocked_attempts(db)
        ingested_decisions = ingest_skipped_decisions(db)
        db.commit()

        scoring = await score_unresolved(db)
        db.commit()

        insights = compute_insights(db)
        db.commit()

        total_unscored = db.query(BlockedSignalCounterfactual).filter(
            BlockedSignalCounterfactual.scored.is_(False),
        ).count()
        total_scored = db.query(BlockedSignalCounterfactual).filter(
            BlockedSignalCounterfactual.scored.is_(True),
        ).count()

        logger.info(
            f"Counterfactual cycle: ingested={ingested_attempts + ingested_decisions} "
            f"scored={scoring.get('scored', 0)} won={scoring.get('won', 0)} "
            f"lost={scoring.get('lost', 0)} insights={insights.get('insights', 0)} "
            f"pending={total_unscored} total={total_scored + total_unscored}"
        )

        return {
            "ingested_attempts": ingested_attempts,
            "ingested_decisions": ingested_decisions,
            "scoring": scoring,
            "insights": insights,
            "total_unscored": total_unscored,
            "total_scored": total_scored,
        }
    finally:
        if _owned:
            db.close()
