"""Carved verbatim out of ``backend/api/trading.py`` — statements moved, no logic changed."""

from .trading import (
    Body,
    Depends,
    Optional,
    Query,
    Session,
    Trade,
    get_db,
    router,
)

from . import trading as _facade

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
    try:
        debate_pk = int(debate_id)
        if debate_pk < 0 or debate_pk > 2**63 - 1:
            raise _facade.HTTPException(status_code=400, detail="Invalid debate_id: out of range")
    except (ValueError, TypeError):
        raise _facade.HTTPException(status_code=400, detail="Invalid debate_id: must be an integer")

    decision = db.query(_facade.DecisionLog).filter(_facade.DecisionLog.id == debate_pk).first()

    if not decision:
        raise _facade.HTTPException(status_code=404, detail="Debate not found")

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
        signal_data = (
            json.loads(decision.signal_data)
            if isinstance(decision.signal_data, str)
            else decision.signal_data
        )
    except (json.JSONDecodeError, TypeError):
        signal_data = {}

    debate_transcript = signal_data.get("debate_transcript", {})
    signal_votes = debate_transcript.get("signal_votes", [])

    vote_breakdown = {
        "total_votes": len(signal_votes),
        "positive_votes": sum(1 for v in signal_votes if v.get("prediction", 0) > 0.5),
        "negative_votes": sum(1 for v in signal_votes if v.get("prediction", 0) <= 0.5),
        "avg_prediction": (
            sum(v.get("prediction", 0) for v in signal_votes) / len(signal_votes)
            if signal_votes
            else 0
        ),
        "avg_confidence": (
            sum(v.get("confidence", 0) for v in signal_votes) / len(signal_votes)
            if signal_votes
            else 0
        ),
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
def _serialize_trade(t: Trade) -> dict:
    return {
        "id": t.id,
        "market_ticker": t.market_ticker,
        "platform": t.platform,
        "strategy": t.strategy,
        "trading_mode": t.trading_mode,
        "market_type": t.market_type,
        "event_slug": t.event_slug,
        "direction": t.direction,
        "entry_price": t.entry_price,
        "size": t.size,
        "filled_size": t.filled_size,
        "fill_price": t.fill_price,
        "fee": t.fee,
        "slippage": t.slippage,
        "confidence": t.confidence,
        "model_probability": t.model_probability,
        "edge_at_entry": t.edge_at_entry,
        "market_price_at_entry": t.market_price_at_entry,
        "signal_source": t.signal_source,
        "clob_order_id": t.clob_order_id,
        "settled": t.settled,
        "result": t.result,
        "pnl": t.pnl,
        "settlement_value": t.settlement_value,
        "settlement_time": t.settlement_time.isoformat() if t.settlement_time else None,
        "timestamp": t.timestamp.isoformat() if t.timestamp else None,
        "market_end_date": t.market_end_date.isoformat() if t.market_end_date else None,
        "blockchain_verified": t.blockchain_verified,
        "journal_notes": t.journal_notes,
        "journal_tags": t.journal_tags,
    }
@router.get("/journal")
async def get_journal(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    strategy: Optional[str] = Query(None),
    mode: Optional[str] = Query(None),
    result: Optional[str] = Query(None),
    market_type: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    sort_by: str = Query("timestamp"),
    sort_dir: str = Query("desc"),
    db: Session = Depends(get_db),
):
    """Paginated trading journal with full trade lifecycle data."""
    try:
        q = db.query(_facade.Trade)

        if strategy:
            q = q.filter(_facade.Trade.strategy == strategy)
        if mode:
            q = q.filter(_facade.Trade.trading_mode == mode)
        if result:
            q = q.filter(_facade.Trade.result == result)
        if market_type:
            q = q.filter(_facade.Trade.market_type == market_type)
        if date_from:
            q = q.filter(_facade.Trade.timestamp >= _facade.datetime.fromisoformat(date_from))
        if date_to:
            q = q.filter(_facade.Trade.timestamp <= _facade.datetime.fromisoformat(date_to))

        sort_col = getattr(_facade.Trade, sort_by, _facade.Trade.timestamp)
        q = q.order_by(sort_col.desc() if sort_dir == "desc" else sort_col.asc())

        total = q.count()
        trades = q.offset((page - 1) * page_size).limit(page_size).all()

        entries = []
        for trade in trades:
            entry = {"trade": _serialize_trade(trade)}

            # Signal
            signal = None
            if trade.signal_id:
                signal = db.query(_facade.Signal).filter(_facade.Signal.id == trade.signal_id).first()
            if signal:
                sources = signal.sources
                if isinstance(sources, str):
                    try:
                        sources = _facade._json.loads(sources)
                    except Exception:
                        sources = None
                entry["signal"] = {
                    "reasoning": signal.reasoning,
                    "sources": sources,
                    "token_id": signal.token_id,
                    "kelly_fraction": signal.kelly_fraction,
                }
            else:
                entry["signal"] = None

            # TradeAttempt
            attempt = (
                db.query(_facade.TradeAttempt)
                .filter(_facade.TradeAttempt.trade_id == trade.id)
                .order_by(_facade.TradeAttempt.created_at.desc())
                .first()
            )
            if attempt:
                factors = attempt.factors_json
                if isinstance(factors, str):
                    try:
                        factors = _facade._json.loads(factors)
                    except Exception:
                        factors = None
                entry["attempt"] = {
                    "factors": factors,
                    "reason_code": attempt.reason_code,
                    "latency_ms": attempt.latency_ms,
                    "phase": attempt.phase,
                }
            else:
                entry["attempt"] = None

            # DecisionLog
            decision = None
            if trade.strategy and trade.timestamp:
                cutoff = trade.timestamp + _facade.timedelta(minutes=5)
                decision = (
                    db.query(_facade.DecisionLog)
                    .filter(
                        _facade.DecisionLog.market_ticker == trade.market_ticker,
                        _facade.DecisionLog.strategy == trade.strategy,
                        _facade.DecisionLog.created_at
                        >= trade.timestamp - _facade.timedelta(minutes=5),
                        _facade.DecisionLog.created_at <= cutoff,
                    )
                    .order_by(_facade.DecisionLog.created_at.desc())
                    .first()
                )
            if decision:
                sd = decision.signal_data
                if isinstance(sd, str):
                    try:
                        sd = _facade._json.loads(sd)
                    except Exception:
                        sd = None
                entry["decision"] = {
                    "signal_data": sd,
                    "reasoning": decision.reason,
                    "outcome": decision.outcome,
                }
            else:
                entry["decision"] = None

            entries.append(entry)

        return {
            "entries": entries,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    except Exception:
        from loguru import logger

        logger.exception("Journal query failed")
        raise _facade.HTTPException(status_code=500, detail="Journal query failed")
@router.put("/journal/{trade_id}/notes")
async def update_journal_notes(
    trade_id: int,
    notes: str = Body(..., embed=True),
    tags: list = Body(default=[], embed=True),
    db: Session = Depends(get_db),
):
    """Save notes and tags on a trade."""
    trade = db.query(_facade.Trade).filter(_facade.Trade.id == trade_id).first()
    if not trade:
        raise _facade.HTTPException(status_code=404, detail="Trade not found")
    trade.journal_notes = notes
    trade.journal_tags = tags
    db.commit()
    return {"ok": True}
@router.get("/journal/stats")
async def get_journal_stats(
    strategy: Optional[str] = Query(None),
    mode: Optional[str] = Query(None),
    days: int = Query(30, ge=1),
    db: Session = Depends(get_db),
):
    """Aggregate journal statistics."""
    try:
        since = _facade.datetime.now(_facade.timezone.utc) - _facade.timedelta(days=days)
        q = db.query(_facade.Trade).filter(_facade.Trade.timestamp >= since)

        if strategy:
            q = q.filter(_facade.Trade.strategy == strategy)
        if mode:
            q = q.filter(_facade.Trade.trading_mode == mode)

        trades = q.all()
        total = len(trades)
        settled = [t for t in trades if t.settled]
        wins = [t for t in settled if t.result == "win"]
        pnls = [t.pnl for t in settled if t.pnl is not None]
        edges = [t.edge_at_entry for t in trades if t.edge_at_entry is not None]
        confs = [t.confidence for t in trades if t.confidence is not None]

        by_strategy = {}
        for t in trades:
            s = t.strategy or "unknown"
            if s not in by_strategy:
                by_strategy[s] = {"trades": 0, "pnl": 0.0, "wins": 0, "settled": 0}
            by_strategy[s]["trades"] += 1
            if t.settled:
                by_strategy[s]["settled"] += 1
                if t.pnl is not None:
                    by_strategy[s]["pnl"] += t.pnl
                if t.result == "win":
                    by_strategy[s]["wins"] += 1
        for s in by_strategy:
            st = by_strategy[s]
            st["win_rate"] = (
                round(st["wins"] / st["settled"], 4) if st["settled"] > 0 else 0.0
            )
            st["pnl"] = round(st["pnl"], 2)
            del st["wins"]
            del st["settled"]

        daily = {}
        for t in settled:
            if t.pnl is not None and t.timestamp:
                d = t.timestamp.strftime("%Y-%m-%d")
                if d not in daily:
                    daily[d] = {"pnl": 0.0, "trades": 0}
                daily[d]["pnl"] += t.pnl
                daily[d]["trades"] += 1
        daily_pnl = [
            {"date": k, "pnl": round(v["pnl"], 2), "trades": v["trades"]}
            for k, v in sorted(daily.items())
        ]

        return {
            "total_trades": total,
            "total_pnl": round(sum(pnls), 2),
            "win_rate": round(len(wins) / len(settled), 4) if settled else 0.0,
            "avg_edge": round(sum(edges) / len(edges), 6) if edges else 0.0,
            "avg_confidence": round(sum(confs) / len(confs), 4) if confs else 0.0,
            "by_strategy": by_strategy,
            "daily_pnl": daily_pnl,
        }
    except Exception:
        from loguru import logger

        logger.exception("Journal stats query failed")
        raise _facade.HTTPException(status_code=500, detail="Journal stats query failed")
