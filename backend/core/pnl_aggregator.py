"""Real-time PnL aggregation — per-strategy, per-mode, portfolio-wide.

Provides fast aggregate queries for dashboards, circuit breakers, and
real-time monitoring without caching stale data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from loguru import logger


@dataclass
class StrategyPnL:
    """Aggregate PnL for a single strategy."""
    strategy: str
    mode: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    total_pnl: float
    avg_pnl: float
    win_rate: float
    max_drawdown: float
    recent_pnl_24h: float  # PnL in last 24 hours
    open_positions: int


@dataclass
class PortfolioPnL:
    """Aggregate PnL across all strategies."""
    mode: str
    total_equity: float
    total_pnl: float
    daily_pnl: float
    open_positions: int
    active_strategies: int
    strategies: List[StrategyPnL]


def get_strategy_pnl(
    strategy_name: str,
    mode: str = "live",
    db=None,
) -> StrategyPnL:
    """Get aggregate PnL for a single strategy."""
    from sqlalchemy import func, text as _sql_text
    from backend.models.database import Trade
    from backend.db.utils import get_db_session
    from datetime import datetime, timedelta, timezone

    _owns = db is None
    if _owns:
        from backend.db.utils import get_db_session
        db = get_db_session()

    try:
        # Aggregate stats from settled trades
        settled = (
            db.query(
                func.count(Trade.id).label("total"),
                func.sum(Trade.pnl).label("total_pnl"),
                func.avg(Trade.pnl).label("avg_pnl"),
            )
            .filter(
                Trade.strategy == strategy_name,
                Trade.trading_mode == mode,
                Trade.settled.is_(True),
            )
            .first()
        )

        total_trades = int(settled.total or 0)
        total_pnl = float(settled.total_pnl or 0.0)
        avg_pnl = float(settled.avg_pnl or 0.0)

        # Win/loss breakdown
        wins = (
            db.query(func.count(Trade.id))
            .filter(
                Trade.strategy == strategy_name,
                Trade.trading_mode == mode,
                Trade.settled.is_(True),
                Trade.pnl > 0,
            )
            .scalar() or 0
        )
        losses = total_trades - wins
        win_rate = wins / total_trades if total_trades > 0 else 0.0

        # 24h PnL
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        recent_pnl = (
            db.query(func.coalesce(func.sum(Trade.pnl), 0.0))
            .filter(
                Trade.strategy == strategy_name,
                Trade.trading_mode == mode,
                Trade.settled.is_(True),
                Trade.timestamp >= cutoff,
            )
            .scalar() or 0.0
        )

        # Open positions count
        open_count = (
            db.query(func.count(Trade.id))
            .filter(
                Trade.strategy == strategy_name,
                Trade.trading_mode == mode,
                Trade.settled.is_(False),
            )
            .scalar() or 0
        )

        # Max drawdown (simple: worst single trade)
        worst = (
            db.query(func.min(Trade.pnl))
            .filter(
                Trade.strategy == strategy_name,
                Trade.trading_mode == mode,
                Trade.settled.is_(True),
            )
            .scalar()
        )
        max_dd = abs(float(worst or 0.0))

        return StrategyPnL(
            strategy=strategy_name,
            mode=mode,
            total_trades=total_trades,
            winning_trades=wins,
            losing_trades=losses,
            total_pnl=total_pnl,
            avg_pnl=avg_pnl,
            win_rate=win_rate,
            max_drawdown=max_dd,
            recent_pnl_24h=float(recent_pnl),
            open_positions=open_count,
        )
    except Exception as e:
        logger.error(f"[pnl_aggregator] Failed to get PnL for {strategy_name}: {e}")
        return StrategyPnL(
            strategy=strategy_name, mode=mode, total_trades=0,
            winning_trades=0, losing_trades=0, total_pnl=0.0,
            avg_pnl=0.0, win_rate=0.0, max_drawdown=0.0,
            recent_pnl_24h=0.0, open_positions=0,
        )
    finally:
        if _owns:
            try:
                db.close()
            except Exception:
                pass


def get_portfolio_pnl(
    mode: str = "live",
    db=None,
) -> PortfolioPnL:
    """Get aggregate PnL across all strategies for a mode."""
    from sqlalchemy import func
    from backend.models.database import Trade, BotState
    from backend.db.utils import get_db_session
    from datetime import datetime, timedelta, timezone

    _owns = db is None
    if _owns:
        db = get_db_session()

    try:
        # Get distinct strategies
        strategies = (
            db.query(Trade.strategy)
            .filter(Trade.trading_mode == mode)
            .distinct()
            .all()
        )
        strategy_names = [s[0] for s in strategies if s[0]]

        # Aggregate per strategy
        strategy_pnls = []
        for name in strategy_names:
            sp = get_strategy_pnl(name, mode=mode, db=db)
            strategy_pnls.append(sp)

        # Portfolio totals
        total_pnl = sum(s.total_pnl for s in strategy_pnls)
        daily_pnl = sum(s.recent_pnl_24h for s in strategy_pnls)
        open_positions = sum(s.open_positions for s in strategy_pnls)
        active = sum(1 for s in strategy_pnls if s.total_trades > 0)

        # Get bankroll from BotState
        state = db.query(BotState).filter_by(mode=mode).first()
        if state:
            if mode == "live":
                total_equity = float(state.bankroll or 0.0)
            elif mode == "testnet":
                total_equity = float(state.testnet_bankroll or 0.0)
            else:
                total_equity = float(state.paper_bankroll or 0.0)
        else:
            total_equity = 0.0

        return PortfolioPnL(
            mode=mode,
            total_equity=total_equity,
            total_pnl=total_pnl,
            daily_pnl=daily_pnl,
            open_positions=open_positions,
            active_strategies=active,
            strategies=strategy_pnls,
        )
    except Exception as e:
        logger.error(f"[pnl_aggregator] Failed to get portfolio PnL: {e}")
        return PortfolioPnL(
            mode=mode, total_equity=0.0, total_pnl=0.0,
            daily_pnl=0.0, open_positions=0, active_strategies=0,
            strategies=[],
        )
    finally:
        if _owns:
            try:
                db.close()
            except Exception:
                pass
