"""Carved verbatim out of ``backend/api/trading.py`` — statements moved, no logic changed."""

from .trading import (
    BaseModel,
    Depends,
    List,
    Optional,
    Session,
    TradingSignal,
    ValidatedSignalCreateRequest,
    get_db,
    handle_errors,
    require_admin,
    router,
)

from . import trading as _facade

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
    timestamp: _facade.datetime
    category: str = "crypto"
    event_slug: _facade.Optional[str] = None
    btc_price: float = 0.0
    btc_change_24h: float = 0.0
    window_end: _facade.Optional[_facade.datetime] = None
    actionable: bool = False
    execution_mode: str = "paper"
class TradeResponse(BaseModel):
    id: int
    market_ticker: str
    market_question: _facade.Optional[str] = None
    platform: str
    event_slug: _facade.Optional[str] = None
    direction: str
    entry_price: float
    size: float
    timestamp: _facade.datetime
    settled: bool
    result: str
    pnl: _facade.Optional[float]
    strategy: _facade.Optional[str] = None
    signal_source: _facade.Optional[str] = None
    confidence: _facade.Optional[float] = None
    trading_mode: str = "paper"
class CreateSignalRequest(BaseModel):
    market_id: str
    prediction: float
    confidence: float
    reasoning: str
    source: str
    weight: float = 1.0
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
    total_signals = db.query(_facade.Signal).count()
    settled_signals = db.query(_facade.Signal).filter(_facade.Signal.outcome_correct.isnot(None)).all()

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

    avg_predicted_edge = (
        sum(abs(s.edge or 0.0) for s in settled_signals) / total_with_outcome
    )
    # Actual edge: for correct predictions, edge was real; for incorrect, edge was negative
    avg_actual_edge = (
        sum(
            abs(s.edge or 0.0) if s.outcome_correct else -abs(s.edge or 0.0)
            for s in settled_signals
        )
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
@router.get("/signals", response_model=List[SignalResponse])
@handle_errors(default_response=[])
async def get_signals():
    """Get current BTC trading signals."""
    signals = await _facade.scan_for_signals()
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
        weight=request.weight,
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
        "created_at": signal.created_at.isoformat(),
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
    query = db.query(_facade.Signal)
    if market_type:
        query = query.filter(_facade.Signal.market_type == market_type)
    if direction:
        query = query.filter(_facade.Signal.direction == direction)
    total = query.count()
    rows = query.order_by(_facade.Signal.timestamp.desc()).offset(offset).limit(limit).all()
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
    signals = await _facade.scan_for_signals()
    actionable = [s for s in signals if s.passes_threshold]
    return [_signal_to_response(s, actionable=True) for s in actionable]
@router.get("/trades", response_model=List[TradeResponse])
async def get_trades(
    limit: int = 50,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    limit = min(limit, 10000)
    query = db.query(_facade.Trade)
    if status:
        query = query.filter(_facade.Trade.result == status)
    trades = query.order_by(_facade.Trade.timestamp.desc()).limit(limit).all()

    trade_ids = [t.id for t in trades]
    context_map = {}
    if trade_ids:
        contexts = (
            db.query(_facade.TradeContext).filter(_facade.TradeContext.trade_id.in_(trade_ids)).all()
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
        db.query(_facade.Trade).filter(_facade.Trade.settled.is_(True)).order_by(_facade.Trade.timestamp).all()
    )

    curve = []
    cumulative_pnl = 0
    bankroll = _facade.settings.INITIAL_BANKROLL

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
    from backend.core.scheduling.scheduler import log_event

    signals = await _facade.scan_for_signals()
    signal = next((s for s in signals if s.market.market_id == signal_ticker), None)

    if not signal:
        raise _facade.HTTPException(status_code=404, detail="Signal not found")

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
        "platform": _facade.settings.DEFAULT_VENUE,
        "reasoning": f"manual simulate: edge {signal.edge:.3f} {signal.direction} @ {entry_price:.0%}",
        "market_type": "btc",
    }

    result = await execute_decision(decision, "simulate", db=db)
    if result is None:
        raise _facade.HTTPException(
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
    from backend.core.scheduling.scheduler import log_event

    log_event("info", "Manual settlement triggered")

    settled = await settle_pending_trades(db)
    await update_bot_state_with_settlements(db, settled)
    await reconcile_bot_state(db)

    return {
        "status": "ok",
        "settled_count": len(settled),
        "trades": [{"id": t.id, "result": t.result, "pnl": t.pnl} for t in settled],
    }
@router.get("/settlements")
async def get_settlements(
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    events = (
        db.query(_facade.SettlementEvent)
        .order_by(_facade.SettlementEvent.settled_at.desc())
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
