"""
Backtesting API endpoints for PolyEdge strategy evaluation.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

import logging
from backend.models.database import get_db, Signal
from backend.models.backtest import BacktestRun, BacktestTrade
from backend.strategies.registry import (
    BaseStrategy,
    STRATEGY_REGISTRY,
    load_all_strategies,
)
from backend.api.auth import require_admin
from backend.api.validation import BacktestRunRequest as ValidatedBacktestRunRequest

logger = logging.getLogger("trading_bot")

_collection_tasks: Dict[str, Dict[str, Any]] = {}


def get_all_strategies() -> dict:
    if not STRATEGY_REGISTRY:
        load_all_strategies()
    return dict(STRATEGY_REGISTRY)


# Alias for signal model used in queries
SignalHistoryRow = Signal

router = APIRouter(prefix="/backtest")


class BacktestRunRequest(BaseModel):
    strategy_name: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    initial_bankroll: float = 100.0
    kelly_fraction: float = 0.0625
    max_trade_size: float = 10.0
    max_position_fraction: float = 0.10
    max_total_exposure: float = 0.60
    daily_loss_limit: float = 15.0


def _parse_date(date_str: Optional[str], fallback: datetime) -> datetime:
    if not date_str:
        return fallback
    return datetime.fromisoformat(date_str)


@router.post("/run")
async def run_backtest_endpoint(
    body: ValidatedBacktestRunRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """Run a backtest for a given strategy and return results.

    Persists the run to BacktestRun/BacktestTrade tables so the
    /api/backtest/history endpoint has data.  Response shape matches
    the frontend Backtest.tsx component expectations.
    """
    from backend.core.backtester import BacktestEngine, BacktestConfig

    end_date = _parse_date(body.end_date, datetime.now(timezone.utc))
    start_date = _parse_date(body.start_date, end_date - timedelta(days=30))

    config = BacktestConfig(
        strategy_name=body.strategy_name,
        start_date=start_date,
        end_date=end_date,
        initial_bankroll=body.initial_bankroll,
        kelly_fraction=body.kelly_fraction,
        max_trade_size=body.max_trade_size,
        max_position_fraction=body.max_position_fraction,
        max_total_exposure=body.max_total_exposure,
        daily_loss_limit=body.daily_loss_limit,
    )

    backtest_run = BacktestRun(
        strategy_name=body.strategy_name,
        start_date=start_date,
        end_date=end_date,
        initial_bankroll=body.initial_bankroll,
        params={
            "kelly_fraction": body.kelly_fraction,
            "max_trade_size": body.max_trade_size,
            "max_position_fraction": body.max_position_fraction,
            "max_total_exposure": body.max_total_exposure,
            "daily_loss_limit": body.daily_loss_limit,
        },
        final_equity=0.0,
        total_pnl=0.0,
        total_return_pct=0.0,
        win_rate=0.0,
        total_trades=0,
        winning_trades=0,
        losing_trades=0,
        completed=False,
    )
    db.add(backtest_run)
    db.commit()
    db.refresh(backtest_run)
    run_id = backtest_run.id

    try:
        engine = BacktestEngine(config)
        result = await engine.run()
    except Exception as exc:
        logger.error(f"Backtest /run failed: {exc}")
        backtest_run.completed = True
        backtest_run.error_message = str(exc)
        backtest_run.completed_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(
            status_code=500, detail="Backtest failed — check server logs"
        )

    winning_trades = 0
    for bt in result.trades:
        pnl_val = bt.pnl if bt.pnl is not None else 0.0
        if pnl_val > 0:
            winning_trades += 1
        db.add(
            BacktestTrade(
                run_id=run_id,
                signal_id=None,
                market_ticker=bt.market_ticker,
                platform="backtest",
                direction=bt.direction,
                entry_price=bt.entry_price,
                exit_price=bt.settlement_value if bt.settled else None,
                size=bt.size,
                pnl=pnl_val,
                result="win" if pnl_val > 0 else ("loss" if pnl_val < 0 else "pending"),
                edge_at_entry=bt.edge,
                market_probability_at_entry=bt.entry_price,
                model_probability_at_entry=None,
                timestamp=bt.timestamp,
                executed=bt.settled,
            )
        )

    losing_trades = result.total_trades - winning_trades
    backtest_run.final_equity = result.final_bankroll
    backtest_run.total_pnl = result.total_pnl
    backtest_run.total_return_pct = result.return_pct
    backtest_run.win_rate = result.win_rate
    backtest_run.total_trades = result.total_trades
    backtest_run.winning_trades = winning_trades
    backtest_run.losing_trades = losing_trades
    backtest_run.sharpe_ratio = result.sharpe_ratio
    backtest_run.completed = True
    backtest_run.completed_at = datetime.now(timezone.utc)
    db.commit()

    cumulative_bankroll = body.initial_bankroll
    trade_log = []
    for bt in result.trades:
        pnl_val = bt.pnl if bt.pnl is not None else 0.0
        cumulative_bankroll += pnl_val
        trade_log.append(
            {
                "timestamp": bt.timestamp.isoformat(),
                "market_ticker": bt.market_ticker,
                "direction": bt.direction,
                "entry_price": bt.entry_price,
                "exit_price": bt.settlement_value if bt.settled else None,
                "size": bt.size,
                "pnl": pnl_val,
                "result": "win"
                if pnl_val > 0
                else ("loss" if pnl_val < 0 else "pending"),
                "edge_at_entry": bt.edge,
                "bankroll_after_trade": round(cumulative_bankroll, 4),
            }
        )

    return {
        "strategy_name": body.strategy_name,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "initial_bankroll": body.initial_bankroll,
        "run_id": run_id,
        "results": {
            "summary": {
                "total_signals": len(result.trades),
                "total_trades": result.total_trades,
                "winning_trades": winning_trades,
                "losing_trades": losing_trades,
                "win_rate": result.win_rate,
                "initial_bankroll": body.initial_bankroll,
                "final_equity": result.final_bankroll,
                "total_pnl": result.total_pnl,
                "total_return_pct": result.return_pct,
                "sharpe_ratio": result.sharpe_ratio,
                "max_drawdown": result.max_drawdown,
                "sortino_ratio": result.sortino_ratio,
                "profit_factor": result.profit_factor,
                "avg_edge": result.avg_edge,
                "avg_trade_size": result.avg_trade_size,
            },
            "trade_log": trade_log,
            "equity_curve": result.equity_curve,
            "signals_processed": len(result.trades),
        },
    }


@router.get("/strategies")
async def get_backtest_strategies(_: None = Depends(require_admin)):
    """Get all available strategies for backtesting."""
    strategies = get_all_strategies()
    result = []
    for name, strategy_class in strategies.items():
        try:
            inst = strategy_class()
            result.append(
                {
                    "name": name,
                    "description": getattr(inst, "description", name),
                    "category": getattr(inst, "category", "general"),
                    "default_params": getattr(inst, "default_params", {}),
                }
            )
        except Exception as e:
            logger.warning(f"Strategy instantiation failed for backtest: {e}")
            result.append(
                {
                    "name": name,
                    "description": name,
                    "category": "unknown",
                    "default_params": {},
                }
            )
    return {"strategies": result}


@router.get("/history")
async def get_backtest_history(
    limit: int = 10,
    offset: int = 0,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """Get history of backtest runs."""
    total = db.query(BacktestRun).count()
    runs = (
        db.query(BacktestRun)
        .order_by(BacktestRun.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "runs": [
            {
                "id": r.id,
                "strategy_name": r.strategy_name,
                "start_date": r.start_date.isoformat() if r.start_date else None,
                "end_date": r.end_date.isoformat() if r.end_date else None,
                "initial_bankroll": r.initial_bankroll,
                "final_equity": r.final_equity,
                "total_pnl": r.total_pnl,
                "total_return_pct": r.total_return_pct,
                "win_rate": r.win_rate,
                "total_trades": r.total_trades,
                "winning_trades": r.winning_trades,
                "losing_trades": r.losing_trades,
                "sharpe_ratio": r.sharpe_ratio,
                "completed": r.completed,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "error_message": r.error_message,
                "params": r.params,
            }
            for r in runs
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


async def run_backtest_engine(
    strategy: BaseStrategy,
    db: Session,
    start_date: datetime,
    end_date: datetime,
    initial_bankroll: float,
    params: Dict[str, Any],
    run_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Core backtesting engine (legacy helper used by other routes).
    """
    # Get historical signals for the date range
    historical_signals = get_historical_signals(db, strategy.name, start_date, end_date)

    # Initialize backtest state
    current_bankroll = initial_bankroll
    portfolio_value = [initial_bankroll]
    trade_log = []
    equity_curve = []

    # Simulate each signal
    for signal in historical_signals:
        # Calculate Kelly size
        kelly_size = calculate_kelly_size(
            edge=signal["edge"], bankroll=current_bankroll, max_bankroll_pct=0.15
        )

        # Execute trade
        trade_result = await execute_backtest_trade(
            strategy=strategy,
            signal=signal,
            size=kelly_size,
            current_bankroll=current_bankroll,
        )

        # Update state
        current_bankroll += trade_result["pnl"]
        portfolio_value.append(current_bankroll)

        # Record trade
        trade_result_record = {
            **trade_result,
            "timestamp": signal["timestamp"],
            "signal_id": signal["id"],
            "bankroll_after_trade": current_bankroll,
        }
        trade_log.append(trade_result_record)

        # Save to database if run_id is provided
        if run_id:
            backtest_trade = BacktestTrade(
                run_id=run_id,
                signal_id=signal["id"],
                market_ticker=signal["market_ticker"],
                platform=signal["platform"],
                direction=signal["direction"],
                entry_price=trade_result["entry_price"],
                exit_price=trade_result["exit_price"],
                size=trade_result["size"],
                pnl=trade_result["pnl"],
                result=trade_result["result"],
                edge_at_entry=signal["edge"],
                market_probability_at_entry=signal.get("market_probability"),
                model_probability_at_entry=signal.get("model_probability"),
                timestamp=datetime.fromisoformat(signal["timestamp"]),
                executed=signal.get("executed", False),
            )
            db.add(backtest_trade)

        equity_curve.append(
            {
                "timestamp": signal["timestamp"],
                "equity": current_bankroll,
                "pnl": current_bankroll - initial_bankroll,
            }
        )

    # Commit all trades to database
    if run_id:
        db.commit()

    # Calculate performance metrics
    import numpy as np

    final_equity = current_bankroll
    total_pnl = final_equity - initial_bankroll
    total_return = total_pnl / initial_bankroll * 100

    winning_trades = len([t for t in trade_log if t["pnl"] > 0])
    losing_trades = len([t for t in trade_log if t["pnl"] < 0])
    total_trades = len(trade_log)

    win_rate = winning_trades / total_trades if total_trades > 0 else 0

    returns = np.diff(portfolio_value)
    sharpe_ratio = (
        np.mean(returns) / np.std(returns) * np.sqrt(365 * 24 * 60)
        if len(returns) > 1
        else 0
    )

    return {
        "summary": {
            "total_signals": len(historical_signals),
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate": win_rate,
            "initial_bankroll": initial_bankroll,
            "final_equity": final_equity,
            "total_pnl": total_pnl,
            "total_return_pct": total_return,
            "sharpe_ratio": sharpe_ratio,
        },
        "trade_log": trade_log,
        "equity_curve": equity_curve,
        "signals_processed": len(historical_signals),
    }


def get_historical_signals(
    db: Session, strategy_name: str, start_date: datetime, end_date: datetime
) -> List[Dict[str, Any]]:
    """Get historical signals for a strategy in the given date range."""
    query = db.query(SignalHistoryRow).filter(
        SignalHistoryRow.timestamp.between(start_date, end_date),
        SignalHistoryRow.market_type.in_(["btc", "weather"]),
    )

    if strategy_name:
        query = query.filter(SignalHistoryRow.reasoning.contains(strategy_name))

    signals = query.all()

    historical_signals = []
    for signal in signals:
        historical_signals.append(
            {
                "id": signal.id,
                "market_ticker": signal.market_ticker,
                "platform": signal.platform,
                "market_type": signal.market_type,
                "direction": signal.direction,
                "model_probability": signal.model_probability,
                "market_probability": signal.market_price,
                "edge": signal.edge,
                "confidence": signal.confidence,
                "suggested_size": signal.suggested_size,
                "reasoning": signal.reasoning,
                "timestamp": signal.timestamp,
                "executed": signal.executed,
                "actual_outcome": signal.actual_outcome,
                "outcome_correct": signal.outcome_correct,
                "settlement_value": signal.settlement_value,
            }
        )

    return historical_signals


def calculate_kelly_size(
    edge: float, bankroll: float, max_bankroll_pct: float = 0.15
) -> float:
    """Calculate Kelly Criterion position size."""
    if edge <= 0:
        return 0
    kelly_fraction = edge
    max_size = bankroll * max_bankroll_pct
    kelly_size = bankroll * kelly_fraction
    return min(kelly_size, max_size)


async def execute_backtest_trade(
    strategy: BaseStrategy, signal: Dict[str, Any], size: float, current_bankroll: float
) -> Dict[str, Any]:
    """Simulate executing a trade and calculate P&L."""
    settlement_value = signal.get("settlement_value")

    if settlement_value is None:
        if signal.get("actual_outcome"):
            settlement_value = (
                1.0 if signal["actual_outcome"] == signal["direction"] else 0.0
            )
        else:
            return {
                "entry_price": signal.get("market_probability", 0.5),
                "exit_price": None,
                "size": size,
                "pnl": 0,
                "result": "pending",
                "edge_at_entry": signal.get("edge", 0),
            }

    entry_price = signal.get("market_probability", 0.5)
    direction = signal["direction"]
    if direction in ("up", "yes"):
        if settlement_value == 1.0:
            pnl = (size / entry_price) - size if entry_price > 0 else 0
            result = "win"
        else:
            pnl = -size
            result = "loss"
    else:
        no_price = 1.0 - entry_price if entry_price < 1.0 else 0.01
        if settlement_value == 0.0:
            pnl = (size / no_price) - size if no_price > 0 else 0
            result = "win"
        else:
            pnl = -size
            result = "loss"

    return {
        "entry_price": signal.get("market_probability", 0.5),
        "exit_price": settlement_value,
        "size": size,
        "pnl": pnl,
        "result": result,
        "edge_at_entry": signal.get("edge", 0),
    }


class HistoricalBacktestRequest(BaseModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    initial_bankroll: float = 100.0
    kelly_fraction: float = 0.0625
    max_trade_size: float = 10.0
    daily_loss_limit: float = 15.0


@router.post("/historical")
async def run_historical_backtest(
    body: HistoricalBacktestRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """Run backtest against historical resolved Polymarket markets."""
    from backend.core.backtester import BacktestEngine, BacktestConfig

    end_date = _parse_date(body.end_date, datetime.now(timezone.utc))
    start_date = _parse_date(body.start_date, end_date - timedelta(days=90))

    config = BacktestConfig(
        strategy_name="",
        start_date=start_date,
        end_date=end_date,
        initial_bankroll=body.initial_bankroll,
        kelly_fraction=body.kelly_fraction,
        max_trade_size=body.max_trade_size,
        daily_loss_limit=body.daily_loss_limit,
    )

    engine = BacktestEngine(config)
    result = await engine.run_from_historical_markets(db=db)

    cumulative_bankroll = body.initial_bankroll
    trade_log = []
    for bt in result.trades:
        pnl_val = bt.pnl if bt.pnl is not None else 0.0
        cumulative_bankroll += pnl_val
        trade_log.append({
            "timestamp": bt.timestamp.isoformat(),
            "market_ticker": bt.market_ticker,
            "direction": bt.direction,
            "entry_price": bt.entry_price,
            "size": bt.size,
            "pnl": pnl_val,
            "result": "win" if pnl_val > 0 else "loss",
            "edge_at_entry": bt.edge,
            "bankroll_after_trade": round(cumulative_bankroll, 4),
        })

    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "results": {
            "summary": {
                "total_trades": result.total_trades,
                "winning_trades": result.winning_trades,
                "win_rate": result.win_rate,
                "initial_bankroll": body.initial_bankroll,
                "final_equity": result.final_bankroll,
                "total_pnl": result.total_pnl,
                "total_return_pct": result.return_pct,
                "sharpe_ratio": result.sharpe_ratio,
                "max_drawdown": result.max_drawdown,
            },
            "trade_log": trade_log,
            "equity_curve": result.equity_curve,
        },
    }


@router.post("/collect-historical")
async def collect_historical_data(
    background_tasks: BackgroundTasks,
    _: None = Depends(require_admin),
):
    task_id = str(uuid.uuid4())[:8]
    _collection_tasks[task_id] = {"status": "running", "results": None}

    async def _run():
        from backend.core.historical_data_collector import historical_data_collector
        try:
            results = await historical_data_collector.run_collection_cycle()
            _collection_tasks[task_id] = {
                "status": "completed",
                "results": results,
                "total_rows": sum(results.values()),
            }
        except Exception as exc:
            _collection_tasks[task_id] = {"status": "failed", "error": str(exc)}

    background_tasks.add_task(_run)
    return {"task_id": task_id, "status": "started"}


@router.get("/collect-historical/{task_id}")
async def get_collection_status(
    task_id: str,
    _: None = Depends(require_admin),
):
    info = _collection_tasks.get(task_id)
    if not info:
        raise HTTPException(404, "Task not found")
    return info
