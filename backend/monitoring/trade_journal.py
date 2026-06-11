"""
Trade Journal -- Query and export trade history.
"""

import csv
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from dataclasses import dataclass
from pathlib import Path


from backend.models.database import Trade

logger = logging.getLogger(__name__)


@dataclass
class DailySummary:
    date: str
    total_trades: int = 0
    total_pnl: float = 0.0
    win_rate: float = 0.0
    wins: int = 0
    losses: int = 0
    best_trade: Optional[dict] = None
    worst_trade: Optional[dict] = None
    volume: float = 0.0


@dataclass
class StrategyPerformance:
    strategy: str
    total_trades: int = 0
    total_pnl: float = 0.0
    win_rate: float = 0.0
    avg_pnl: float = 0.0
    best_trade: Optional[dict] = None
    worst_trade: Optional[dict] = None


def _trade_to_dict(trade: Trade) -> dict:
    """Convert a Trade ORM object to a plain dict for export."""
    return {
        "id": trade.id,
        "market_ticker": trade.market_ticker,
        "platform": trade.platform,
        "strategy": trade.strategy,
        "trading_mode": trade.trading_mode,
        "direction": trade.direction,
        "entry_price": trade.entry_price,
        "size": trade.size,
        "timestamp": trade.timestamp.isoformat() if trade.timestamp else None,
        "settled": trade.settled,
        "result": trade.result,
        "pnl": trade.pnl,
        "settlement_value": trade.settlement_value,
        "confidence": trade.confidence,
        "model_probability": trade.model_probability,
        "edge_at_entry": trade.edge_at_entry,
        "fee": trade.fee,
        "slippage": trade.slippage,
        "source": trade.source,
    }


class TradeJournal:
    """
    Query trade history from existing DB models.
    Wraps the existing Trade model without creating new tables.
    """

    def __init__(self, db_session=None):
        self._db = db_session

    def _get_session(self):
        """Get DB session -- use provided or create new."""
        if self._db:
            return self._db
        from backend.models.database import SessionLocal

        return SessionLocal()

    def _owns_session(self) -> bool:
        """True when the journal created its own session (must close it)."""
        return self._db is None

    def get_trades(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        strategy: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """Get trades with optional filters. Returns list of dicts."""
        session = self._get_session()
        try:
            query = session.query(Trade)

            if start_date:
                start_dt = datetime.fromisoformat(start_date)
                if start_dt.tzinfo is None:
                    start_dt = start_dt.replace(tzinfo=timezone.utc)
                query = query.filter(Trade.timestamp >= start_dt)

            if end_date:
                end_dt = datetime.fromisoformat(end_date)
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=timezone.utc)
                query = query.filter(Trade.timestamp <= end_dt)

            if strategy:
                query = query.filter(Trade.strategy == strategy)

            query = query.order_by(Trade.timestamp.desc()).limit(limit)
            trades = query.all()
            return [_trade_to_dict(t) for t in trades]
        finally:
            if self._owns_session():
                session.close()

    def get_daily_summary(self, target_date: Optional[str] = None) -> DailySummary:
        """Get summary for a specific day. Defaults to today (UTC)."""
        if target_date:
            day = datetime.fromisoformat(target_date)
        else:
            day = datetime.now(timezone.utc)

        if day.tzinfo is None:
            day = day.replace(tzinfo=timezone.utc)

        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        date_str = day_start.strftime("%Y-%m-%d")

        session = self._get_session()
        try:
            trades = (
                session.query(Trade)
                .filter(Trade.timestamp >= day_start, Trade.timestamp < day_end)
                .all()
            )

            summary = DailySummary(date=date_str)
            if not trades:
                return summary

            summary.total_trades = len(trades)
            pnls = [t.pnl for t in trades if t.pnl is not None]
            summary.total_pnl = sum(pnls)
            summary.volume = sum(
                abs(t.size) * (t.entry_price or 0.5) for t in trades if t.size
            )

            settled = [t for t in trades if t.pnl is not None]
            summary.wins = sum(1 for t in settled if t.pnl > 0)
            summary.losses = sum(1 for t in settled if t.pnl < 0)
            total_settled = summary.wins + summary.losses
            if total_settled > 0:
                summary.win_rate = summary.wins / total_settled

            if pnls:
                best = max(
                    trades, key=lambda t: t.pnl if t.pnl is not None else float("-inf")
                )
                worst = min(
                    trades, key=lambda t: t.pnl if t.pnl is not None else float("inf")
                )
                summary.best_trade = _trade_to_dict(best)
                summary.worst_trade = _trade_to_dict(worst)

            return summary
        finally:
            if self._owns_session():
                session.close()

    def get_strategy_performance(self, strategy_name: str) -> StrategyPerformance:
        """Get performance stats for a strategy."""
        session = self._get_session()
        try:
            trades = session.query(Trade).filter(Trade.strategy == strategy_name).all()

            perf = StrategyPerformance(strategy=strategy_name)
            if not trades:
                return perf

            perf.total_trades = len(trades)
            pnls = [t.pnl for t in trades if t.pnl is not None]
            perf.total_pnl = sum(pnls)

            settled = [t for t in trades if t.pnl is not None]
            wins = sum(1 for t in settled if t.pnl > 0)
            losses = sum(1 for t in settled if t.pnl < 0)
            total_settled = wins + losses
            if total_settled > 0:
                perf.win_rate = wins / total_settled

            if pnls:
                perf.avg_pnl = perf.total_pnl / len(pnls)
                best = max(
                    trades, key=lambda t: t.pnl if t.pnl is not None else float("-inf")
                )
                worst = min(
                    trades, key=lambda t: t.pnl if t.pnl is not None else float("inf")
                )
                perf.best_trade = _trade_to_dict(best)
                perf.worst_trade = _trade_to_dict(worst)

            return perf
        finally:
            if self._owns_session():
                session.close()

    def export_csv(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        output_path: str = "data/trade_export.csv",
    ) -> str:
        """Export trades to CSV. Returns file path."""
        trades = self.get_trades(start_date=start_date, end_date=end_date, limit=10000)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        if not trades:
            # Write empty file with header
            with open(output_path, "w", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "id",
                        "market_ticker",
                        "platform",
                        "strategy",
                        "trading_mode",
                        "direction",
                        "entry_price",
                        "size",
                        "timestamp",
                        "settled",
                        "result",
                        "pnl",
                        "settlement_value",
                        "confidence",
                        "model_probability",
                        "edge_at_entry",
                        "fee",
                        "slippage",
                        "source",
                    ],
                )
                writer.writeheader()
            return output_path

        fields = list(trades[0].keys())

        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for trade in trades:
                writer.writerow(trade)

        return output_path
