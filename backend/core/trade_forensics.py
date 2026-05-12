"""Trade Forensics — post-settlement analysis of losing trades.

Analyzes losing trades to extract failure patterns and stores insights
for AGI learning and strategy improvement.
"""

from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from collections import Counter

from sqlalchemy.orm import Session

from backend.models.database import Trade, Signal

def classify_trade_role(
    order_type: str | None,
    fill_price: float | None,
    mid_price: float | None,
    maker_rebate: float | None,
    taker_fee: float | None,
) -> str:
    """Classify a trade as MAKER, TAKER, or UNKNOWN.

    Args:
        order_type: 'market' or 'limit'
        fill_price: actual fill price
        mid_price: mid price of order book at time of fill (optional)
        maker_rebate: maker rebate amount (optional, positive = maker)
        taker_fee: taker fee amount (optional, positive = taker)

    Returns:
        'maker', 'taker', or 'unknown'
    """
    # Market orders are always takers
    if order_type == "market":
        return "taker"

    # Positive maker rebate → definitely a maker
    if maker_rebate is not None and maker_rebate > 0:
        return "maker"

    # Positive taker fee → definitely a taker
    if taker_fee is not None and taker_fee > 0:
        return "taker"

    # Limit order near mid → likely maker
    if order_type == "limit" and fill_price is not None and mid_price is not None:
        spread = abs(fill_price - mid_price)
        # If fill is within 0.5% of mid, call it a maker
        if mid_price > 0 and spread / mid_price < 0.005:
            return "maker"

    return "unknown"



from loguru import logger  # noqa: E402
class TradeForensics:
    """Analyzes losing trades to diagnose failure modes."""

    FAILURE_PATTERNS = {
        "bad_entry_timing": "Entered just before price reversal",
        "wrong_regime": "Strategy misaligned with market regime",
        "low_liquidity": "Slippage > 3% or spread > 2%",
        "early_exit": "Exited too early, missed majority of move",
        "late_entry": "Entered after move already exhausted",
        "gapped_against": "Market gapped against position overnight",
        "high_volatility": "Extreme volatility triggered stop prematurely",
        "news_event": "Unscheduled news moved market",
        "data_staleness": "Signal based on stale market data",
        "circuit_breaker": "Trading paused during signal window",
    }

    def __init__(self):
        self._analysis_cache: Dict[int, Dict[str, Any]] = {}  # trade_id → insights

    async def analyze_losing_trade(self, trade_id: int) -> Optional[Dict[str, Any]]:
        """Deep-dive analysis of a single losing trade.

        Returns insights: {root_cause, confidence, contributing_factors, suggestions}
        """
        from backend.db.utils import get_db_session
        with get_db_session() as db:
                trade = db.query(Trade).filter_by(id=trade_id).first()
                if not trade or trade.result != "loss":
                    return None

                # Fetch linked signal and approval decision
                signal = None
                if trade.signal_id:
                    from backend.models.database import Signal
                    signal = db.query(Signal).filter_by(id=trade.signal_id).first()

                # Gather context
                context = {
                    "trade_id": trade_id,
                    "strategy": getattr(trade, "strategy", None) or "unknown",
                    "market": trade.market_ticker,
                    "side": trade.direction,
                    "size": trade.size,
                    "entry_price": trade.entry_price,
                    "pnl": trade.pnl,
                    "result": trade.result,
                    "timestamp": trade.timestamp.isoformat() if trade.timestamp else None,
                    "settlement_time": trade.settlement_time.isoformat() if trade.settlement_time else None,
                    "signal_confidence": signal.confidence if signal else None,
                    "signal_edge": getattr(signal, "edge", None) if signal else None,
                }

                # Diagnose using heuristics
                diagnosis = self._diagnose(trade, signal, db)
                context.update(diagnosis)

                # Cache and log
                self._analysis_cache[trade_id] = context
                logger.info(
                    f"[TradeForensics] Analyzed loss trade#{trade_id} ({trade.strategy}): "
                    f"cause={diagnosis.get('root_cause')}, conf={diagnosis.get('confidence', 0):.0%}"
                )
                return context

    def _diagnose(
        self,
        trade: Trade,
        signal: Optional[Any],
        db: Session
    ) -> Dict[str, Any]:
        """Heuristic diagnosis of loss root cause."""
        causes = []
        confidence = 0.5  # base
        factors: List[str] = []

        # 1. Check signal confidence
        if signal and signal.confidence and signal.confidence < 0.55:
            causes.append("low_confidence_signal")
            confidence -= 0.1
            factors.append(f"signal confidence {signal.confidence:.1%}")

        if trade.entry_price and trade.market_ticker:
            try:
                signal_record = (
                    db.query(Signal)
                    .filter(Signal.market_ticker == trade.market_ticker)
                    .order_by(Signal.timestamp.desc())
                    .first()
                )
                if signal_record and signal_record.price:
                    slippage = abs(trade.entry_price - signal_record.price) / signal_record.price if signal_record.price > 0 else 0
                    if slippage > 0.02:
                        causes.append("high_slippage")
                        confidence += 0.15
                        factors.append(f"slippage {slippage:.1%}")
            except Exception:
                logger.exception(f"[TradeForensics] Slippage calculation failed for trade_id={trade.id} market={trade.market_ticker}")
                pass

        # 3. Check if strategy was already warned
        from backend.core.strategy_health import StrategyHealthMonitor
        from backend.db.utils import get_db_session
        health = StrategyHealthMonitor()
        with get_db_session() as db_for_health:
            if health.should_warn(trade.strategy, db_for_health):
                causes.append("strategy_degrading")
                confidence += 0.2
                factors.append("strategy in warned state")

        ts = trade.timestamp or datetime.now(timezone.utc)
        recent_losses = (
            db.query(Trade)
            .filter(
                Trade.strategy == trade.strategy,
                Trade.result == "loss",
                Trade.timestamp <= ts,
                Trade.timestamp >= ts - timedelta(hours=24),
            )
            .count()
        )
        if recent_losses >= 3:
            causes.append("loss_streak")
            factors.append(f"{recent_losses} recent losses")

        root_cause = causes[0] if causes else "unknown"
        return {
            "root_cause": root_cause,
            "confidence": max(0.1, min(0.95, confidence)),
            "contributing_factors": factors,
            "suggestions": self._get_suggestions(root_cause),
        }

    def _get_suggestions(self, root_cause: str) -> List[str]:
        mapping = {
            "low_confidence_signal": ["Raise AUTO_APPROVE_MIN_CONFIDENCE", "Review prompt engineering"],
            "strategy_degrading": ["Consider disabling strategy temporarily", "Check strategy health metrics"],
            "loss_streak": ["Reduce position sizing temporarily", "Evaluate circuit breaker"],
            "bad_entry_timing": ["Add confirmation filter", "Delay entry by 1-2 candles"],
            "unknown": ["Gather more market context", "Run deeper backtest"],
        }
        return mapping.get(root_cause, ["Investigate manually"])

    async def analyze_recent_losses(self, lookback_hours: int = 24) -> Dict[str, Any]:
        """Batch analyze all losses in the last N hours.

        Returns summary: {total_losses, pattern_distribution, top_suggestions}
        """
        from backend.db.utils import get_db_session
        with get_db_session() as db:
                cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
                losses = (
                    db.query(Trade)
                    .filter(
                        Trade.result == "loss",
                        Trade.settlement_time >= cutoff,
                    )
                    .all()
                )

                analyses = []
                for trade in losses:
                    analysis = await self.analyze_losing_trade(trade.id)
                    if analysis:
                        analyses.append(analysis)

                # Aggregate stats
                total = len(analyses)
                causes = Counter(a["root_cause"] for a in analyses)
                all_factors = [f for a in analyses for f in a.get("contributing_factors", [])]
                top_suggestions = Counter(
                    s for a in analyses for s in a.get("suggestions", [])
                ).most_common(5)

                summary = {
                    "lookback_hours": lookback_hours,
                    "total_losses": total,
                    "pattern_distribution": dict(causes.most_common()),
                    "top_contributing_factors": Counter(all_factors).most_common(10),
                    "top_suggestions": top_suggestions,
                    "analyzed_at": datetime.now(timezone.utc).isoformat(),
                }

                logger.info(f"[TradeForensics] Summary: {summary}")
                return summary


# Module-level singleton
trade_forensics = TradeForensics()
