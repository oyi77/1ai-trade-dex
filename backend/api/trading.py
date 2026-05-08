"""Trading routes - signals, trades, settlements, calibration."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from collections import defaultdict

from backend.config import settings
from backend.models.database import (
    get_db,
    Signal,
    Trade,
    TradeContext,
    SettlementEvent,
    DecisionLog,
)
from backend.core.signals import scan_for_signals, TradingSignal
from backend.core.errors import handle_errors
from backend.api.auth import require_admin

router = APIRouter(tags=["trading"])


# ============================================================================
# Pydantic Response Models (reused from main.py for compatibility)
# ============================================================================


class CalibrationBucket(BaseModel):
    bucket: str
    predicted_avg: float
    actual_rate: float
    count: int


class CalibrationSummary(BaseModel):
    total_signals: int
    total_with_outcome: int
    accuracy: float
    avg_predicted_edge: float
    avg_actual_edge: float
    brier_score: float


class SignalResponse(BaseModel):
    market_ticker: str
    market_title: str
    platform: str
    direction: str
    model_probability: float
    market_probability: float
    edge: float
    confidence: float
    suggested_size: float
    reasoning: str
    timestamp: datetime
    category: str = "crypto"
    event_slug: Optional[str] = None
    btc_price: float = 0.0
    btc_change_24h: float = 0.0
    window_end: Optional[datetime] = None
    actionable: bool = False
    execution_mode: str = "paper"


class TradeResponse(BaseModel):
    id: int
    market_ticker: str
    market_question: Optional[str] = None
    platform: str
    event_slug: Optional[str] = None
    direction: str
    entry_price: float
    size: float
    timestamp: datetime
    settled: bool
    result: str
    pnl: Optional[float]
    strategy: Optional[str] = None
    signal_source: Optional[str] = None
    confidence: Optional[float] = None
    trading_mode: str = "paper"


class CreateSignalRequest(BaseModel):
    market_id: str
    prediction: float
    confidence: float
    reasoning: str
    source: str
    weight: float = 1.0


from backend.api.validation import SignalCreateRequest as ValidatedSignalCreateRequest  # noqa: E402


# ============================================================================
# Helper Functions
# ============================================================================


def _signal_to_response(s: TradingSignal, actionable: bool = False) -> SignalResponse:
    return SignalResponse(
        market_ticker=s.market.market_id,
        market_title=f"BTC 5m - {s.market.slug}",
        platform="polymarket",
        direction=s.direction,
        model_probability=s.model_probability,
        market_probability=s.market_probability,
        edge=s.edge,
        confidence=s.confidence,
        suggested_size=s.suggested_size,
        reasoning=s.reasoning,
        timestamp=s.timestamp,
        category="crypto",
        event_slug=s.market.slug,
        btc_price=s.btc_price,
        btc_change_24h=s.btc_change_24h,
        window_end=s.market.window_end,
        actionable=actionable,
        execution_mode="paper",
    )


def _compute_calibration_summary(db: Session) -> Optional[CalibrationSummary]:
    """Compute calibration summary from settled signals."""
    total_signals = db.query(Signal).count()
    settled_signals = db.query(Signal).filter(Signal.outcome_correct.isnot(None)).all()

    if not settled_signals:
        if total_signals == 0:
            return None
        return CalibrationSummary(
            total_signals=total_signals,
            total_with_outcome=0,
            accuracy=0.0,
            avg_predicted_edge=0.0,
            avg_actual_edge=0.0,
            brier_score=0.0,
        )

    total_with_outcome = len(settled_signals)
    correct = sum(1 for s in settled_signals if s.outcome_correct)
    accuracy = correct / total_with_outcome if total_with_outcome > 0 else 0.0

    avg_predicted_edge = sum(abs(s.edge or 0.0) for s in settled_signals) / total_with_outcome
    # Actual edge: for correct predictions, edge was real; for incorrect, edge was negative
    avg_actual_edge = (
        sum(abs(s.edge or 0.0) if s.outcome_correct else -abs(s.edge or 0.0) for s in settled_signals)
        / total_with_outcome
    )

    # Brier score: mean squared error of probability forecasts
    # For each signal: (predicted_prob - actual_outcome)^2
    brier_sum = 0.0
    for s in settled_signals:
        # Model probability is for UP; actual is 1.0 if UP won, 0.0 if DOWN won
        actual = s.settlement_value if s.settlement_value is not None else 0.5
        model_prob = s.model_probability if s.model_probability is not None else 0.5
        brier_sum += (model_prob - actual) ** 2
    brier_score = brier_sum / total_with_outcome

    return CalibrationSummary(
        total_signals=total_signals,
        total_with_outcome=total_with_outcome,
        accuracy=accuracy,
        avg_predicted_edge=avg_predicted_edge,
        avg_actual_edge=avg_actual_edge,
        brier_score=brier_score,
    )


# ============================================================================
# Signal Endpoints
# ============================================================================


@router.get("/signals", response_model=List[SignalResponse])
@handle_errors(default_response=[])
async def get_signals():
    """Get current BTC trading signals."""
    signals = await scan_for_signals()
    return [_signal_to_response(s, actionable=s.passes_threshold) for s in signals]


@router.post("/signals", status_code=201)
async def create_signal(
    request: ValidatedSignalCreateRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """Create a new trading signal (e.g., from MiroFish debate engine)."""
    from backend.models.database import MiroFishSignal

    signal = MiroFishSignal(
        market_id=request.market_id,
        prediction=request.prediction,
        confidence=request.confidence,
        reasoning=request.reasoning,
        source=request.source,
        weight=request.weight
    )
    db.add(signal)
    db.commit()
    db.refresh(signal)

    return {
        "id": signal.id,
        "market_id": signal.market_id,
        "prediction": signal.prediction,
        "confidence": signal.confidence,
        "source": signal.source,
        "created_at": signal.created_at.isoformat()
    }


@router.get("/signals/history")
async def get_signals_history(
    limit: int = 100,
    offset: int = 0,
    market_type: Optional[str] = None,
    direction: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Return historical signals from the database with outcome data."""
    query = db.query(Signal)
    if market_type:
        query = query.filter(Signal.market_type == market_type)
    if direction:
        query = query.filter(Signal.direction == direction)
    total = query.count()
    rows = query.order_by(Signal.timestamp.desc()).offset(offset).limit(limit).all()
    items = [
         {
             "id": r.id,
             "market_ticker": r.market_ticker,
             "platform": r.platform or "polymarket",
             "market_type": r.market_type or "btc",
             "timestamp": r.timestamp.isoformat() if r.timestamp else None,
             "direction": r.direction,
             "model_probability": r.model_probability,
             "market_probability": r.market_price,
             "edge": r.edge,
             "confidence": r.confidence,
             "suggested_size": r.suggested_size,
             "reasoning": r.reasoning,
             "executed": r.executed,
             "actual_outcome": r.actual_outcome,
             "outcome_correct": r.outcome_correct,
             "settlement_value": r.settlement_value,
             "settled_at": r.settled_at.isoformat() if r.settled_at else None,
              "execution_mode": r.execution_mode or "paper",
         }
         for r in rows
     ]
    return {"items": items, "total": total}


@router.get("/signals/actionable", response_model=List[SignalResponse])
@handle_errors(default_response=[])
async def get_actionable_signals():
    """Get only signals that pass the edge threshold."""
    signals = await scan_for_signals()
    actionable = [s for s in signals if s.passes_threshold]
    return [_signal_to_response(s, actionable=True) for s in actionable]


# ============================================================================
# Trade Endpoints
# ============================================================================


@router.get("/trades", response_model=List[TradeResponse])
async def get_trades(
    limit: int = 50,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    limit = min(limit, 500)
    query = db.query(Trade)
    if status:
        query = query.filter(Trade.result == status)
    trades = query.order_by(Trade.timestamp.desc()).limit(limit).all()

    trade_ids = [t.id for t in trades]
    context_map = {}
    if trade_ids:
        contexts = (
            db.query(TradeContext).filter(TradeContext.trade_id.in_(trade_ids)).all()
        )
        context_map = {c.trade_id: c for c in contexts}

    result_list = []
    for t in trades:
        ctx = context_map.get(t.id)
        trade_dict = TradeResponse(
            id=t.id,
            market_ticker=t.market_ticker,
            platform=t.platform,
            event_slug=t.event_slug,
            direction=t.direction,
            entry_price=t.entry_price,
            size=t.size,
            timestamp=t.timestamp,
            settled=t.settled,
            result=t.result,
            pnl=t.pnl,
            trading_mode=t.trading_mode,
        )
        trade_dict = trade_dict.model_dump()
        trade_dict["strategy"] = (ctx.strategy if ctx else None) or getattr(
            t, "strategy", None
        )
        trade_dict["signal_source"] = (ctx.signal_source if ctx else None) or getattr(
            t, "signal_source", None
        )
        trade_dict["confidence"] = (ctx.confidence if ctx else None) or getattr(
            t, "confidence", None
        )
        result_list.append(trade_dict)

    return result_list


@router.get("/equity-curve")
async def get_equity_curve(
    db: Session = Depends(get_db),
):
    trades = (
        db.query(Trade).filter(Trade.settled.is_(True)).order_by(Trade.timestamp).all()
    )

    curve = []
    cumulative_pnl = 0
    bankroll = settings.INITIAL_BANKROLL

    for trade in trades:
        if trade.pnl is not None:
            cumulative_pnl += trade.pnl
            curve.append(
                {
                    "timestamp": trade.timestamp.isoformat(),
                    "pnl": cumulative_pnl,
                    "bankroll": bankroll + cumulative_pnl,
                    "trade_id": trade.id,
                }
            )

    return curve


@router.post("/simulate-trade")
async def simulate_trade(
    signal_ticker: str, db: Session = Depends(get_db), _: None = Depends(require_admin)
):
    """Execute a manual trade for a given signal ticker, routed through risk controls."""
    from backend.core.strategy_executor import execute_decision
    from backend.core.scheduler import log_event

    signals = await scan_for_signals()
    signal = next((s for s in signals if s.market.market_id == signal_ticker), None)

    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")

    entry_price = (
        signal.market.up_price if signal.direction == "up" else signal.market.down_price
    )
    token_id = getattr(
        signal.market,
        "up_token_id" if signal.direction == "up" else "down_token_id",
        None,
    )

    decision = {
        "market_ticker": signal.market.market_id,
        "slug": signal.market.slug,
        "event_slug": signal.market.slug,
        "direction": signal.direction,
        "size": signal.suggested_size,
        "entry_price": entry_price,
        "edge": signal.edge,
        "confidence": signal.confidence,
        "model_probability": signal.model_probability,
        "token_id": token_id,
        "platform": "polymarket",
        "reasoning": f"manual simulate: edge {signal.edge:.3f} {signal.direction} @ {entry_price:.0%}",
        "market_type": "btc",
    }

    result = await execute_decision(decision, "simulate", db=db)
    if result is None:
        raise HTTPException(
            status_code=400, detail="Trade rejected by risk controls or duplicate"
        )

    log_event(
        "trade", f"Manual BTC trade: {signal.direction.upper()} {signal.market.slug}"
    )
    return {"status": "ok", "trade_id": result["id"], "size": result["size"]}


@router.post("/settle-trades")
async def settle_trades_endpoint(
    db: Session = Depends(get_db), _: None = Depends(require_admin)
):
    from backend.core.settlement import (
        settle_pending_trades,
        update_bot_state_with_settlements,
        reconcile_bot_state,
    )
    from backend.core.scheduler import log_event

    log_event("info", "Manual settlement triggered")

    settled = await settle_pending_trades(db)
    await update_bot_state_with_settlements(db, settled)
    await reconcile_bot_state(db)

    return {
        "status": "ok",
        "settled_count": len(settled),
        "trades": [{"id": t.id, "result": t.result, "pnl": t.pnl} for t in settled],
    }


# ============================================================================
# Calibration Endpoints
# ============================================================================


@router.get("/calibration")
async def get_calibration(
    db: Session = Depends(get_db),
):
    """Return calibration data: predicted probability vs actual win rate."""
    signals = db.query(Signal).filter(Signal.outcome_correct.isnot(None)).all()

    if not signals:
        return {"buckets": [], "summary": None}

    # Bucket signals by model_probability into 5% bins

    buckets_data = defaultdict(lambda: {"predicted_sum": 0.0, "correct": 0, "total": 0})

    for s in signals:
        # Bin by 5% increments
        bin_start = int(s.model_probability * 100 // 5) * 5
        bin_end = bin_start + 5
        bucket_key = f"{bin_start}-{bin_end}%"

        buckets_data[bucket_key]["predicted_sum"] += s.model_probability
        buckets_data[bucket_key]["total"] += 1
        if s.outcome_correct:
            buckets_data[bucket_key]["correct"] += 1

    buckets = []
    for bucket_key in sorted(buckets_data.keys()):
        d = buckets_data[bucket_key]
        buckets.append(
            CalibrationBucket(
                bucket=bucket_key,
                predicted_avg=d["predicted_sum"] / d["total"],
                actual_rate=d["correct"] / d["total"],
                count=d["total"],
            )
        )

    summary = _compute_calibration_summary(db)

    return {"buckets": buckets, "summary": summary}


# ============================================================================
# Settlement Events Endpoint
# ============================================================================


@router.get("/settlements")
async def get_settlements(
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    events = (
        db.query(SettlementEvent)
        .order_by(SettlementEvent.settled_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [
        {
            "id": e.id,
            "trade_id": e.trade_id,
            "market_ticker": e.market_ticker,
            "resolved_outcome": e.resolved_outcome,
            "pnl": e.pnl,
            "settled_at": e.settled_at.isoformat() if e.settled_at else None,
            "source": e.source,
        }
        for e in events
    ]


@router.get("/debates/{debate_id}/signals")
def get_debate_signals(
    debate_id: str,
    db: Session = Depends(get_db),
):
    """
    Get all participating signals and vote breakdown for a debate.

    Returns debate transcript with signal votes, bull/bear arguments,
    and consensus decision. Shows MiroFish participation with equal weight.
    """
    decision = db.query(DecisionLog).filter(
        DecisionLog.id == int(debate_id)
    ).first()

    if not decision:
        raise HTTPException(status_code=404, detail="Debate not found")

    if not decision.signal_data:
        return {
            "debate_id": debate_id,
            "market_ticker": decision.market_ticker,
            "strategy": decision.strategy,
            "decision": decision.decision,
            "confidence": decision.confidence,
            "signal_votes": [],
            "debate_transcript": None,
        }

    import json
    try:
        signal_data = json.loads(decision.signal_data) if isinstance(decision.signal_data, str) else decision.signal_data
    except (json.JSONDecodeError, TypeError):
        signal_data = {}

    debate_transcript = signal_data.get("debate_transcript", {})
    signal_votes = debate_transcript.get("signal_votes", [])

    vote_breakdown = {
        "total_votes": len(signal_votes),
        "positive_votes": sum(1 for v in signal_votes if v.get("prediction", 0) > 0.5),
        "negative_votes": sum(1 for v in signal_votes if v.get("prediction", 0) <= 0.5),
        "avg_prediction": sum(v.get("prediction", 0) for v in signal_votes) / len(signal_votes) if signal_votes else 0,
        "avg_confidence": sum(v.get("confidence", 0) for v in signal_votes) / len(signal_votes) if signal_votes else 0,
    }

    return {
        "debate_id": debate_id,
        "market_ticker": decision.market_ticker,
        "strategy": decision.strategy,
        "decision": decision.decision,
        "confidence": decision.confidence,
        "created_at": decision.created_at.isoformat() if decision.created_at else None,
        "signal_votes": signal_votes,
        "vote_breakdown": vote_breakdown,
        "debate_transcript": debate_transcript,
    }
