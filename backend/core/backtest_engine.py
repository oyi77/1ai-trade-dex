"""Enhanced Backtesting Engine — multi-strategy comparison with walk-forward validation.

Extends the base BacktestEngine with:
- Side-by-side strategy comparison
- Walk-forward validation (train/test splits)
- Monte Carlo simulation for confidence intervals
- Transaction cost modeling (fees + slippage)
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from loguru import logger


@dataclass
class StrategyComparisonResult:
    """Result of comparing multiple strategies on the same data."""
    strategy_name: str
    total_trades: int
    winning_trades: int
    win_rate: float
    total_pnl: float
    sharpe_ratio: float
    max_drawdown: float
    profit_factor: float
    avg_trade_size: float
    avg_edge: float
    return_pct: float
    equity_curve: list[dict] = field(default_factory=list)
    transaction_costs: float = 0.0


@dataclass
class WalkForwardResult:
    """Result of walk-forward validation for a single strategy."""
    strategy_name: str
    folds: list[StrategyComparisonResult]
    avg_sharpe: float
    avg_win_rate: float
    avg_pnl: float
    consistency_score: float  # fraction of profitable folds


@dataclass
class MonteCarloResult:
    """Monte Carlo simulation output."""
    strategy_name: str
    simulations: int
    mean_pnl: float
    median_pnl: float
    std_pnl: float
    percentile_5: float
    percentile_95: float
    probability_of_profit: float
    max_drawdown_mean: float
    max_drawdown_95: float


@dataclass
class EnhancedBacktestConfig:
    """Configuration for enhanced backtesting."""
    strategies: list[str]
    start_date: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc) - timedelta(days=90)
    )
    end_date: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    initial_bankroll: float = 100.0
    kelly_fraction: float = 0.0625
    max_trade_size: float = 10.0
    slippage_pct: float = 0.01
    platform_fee_pct: float = 0.01
    walk_forward_folds: int = 5
    train_ratio: float = 0.7
    monte_carlo_sims: int = 1000


class EnhancedBacktestEngine:
    """Multi-strategy backtesting engine with comparison, walk-forward, and Monte Carlo."""

    def __init__(self, config: EnhancedBacktestConfig):
        self.config = config

    async def compare_strategies(self, db=None) -> list[StrategyComparisonResult]:
        """Run backtests for all configured strategies and return comparison results."""
        results: list[StrategyComparisonResult] = []
        for name in self.config.strategies:
            try:
                result = await self._backtest_single(name, db)
                results.append(result)
            except Exception:
                logger.exception(f"Backtest failed for strategy {name}")
        results.sort(key=lambda r: r.sharpe_ratio, reverse=True)
        return results

    async def walk_forward_validate(
        self, strategy_name: str, db=None
    ) -> WalkForwardResult:
        """Run walk-forward validation for a single strategy."""
        signals = self._fetch_signals(strategy_name, db)
        if not signals:
            logger.warning(f"No signals for {strategy_name} walk-forward")
            return WalkForwardResult(
                strategy_name=strategy_name,
                folds=[],
                avg_sharpe=0.0,
                avg_win_rate=0.0,
                avg_pnl=0.0,
                consistency_score=0.0,
            )

        folds = self._split_walk_forward(signals)
        fold_results: list[StrategyComparisonResult] = []

        for i, (_train, test) in enumerate(folds):
            result = self._simulate_signals(test, f"{strategy_name}_fold{i}")
            fold_results.append(result)

        profitable = sum(1 for r in fold_results if r.total_pnl > 0)
        return WalkForwardResult(
            strategy_name=strategy_name,
            folds=fold_results,
            avg_sharpe=statistics.mean(r.sharpe_ratio for r in fold_results) if fold_results else 0.0,
            avg_win_rate=statistics.mean(r.win_rate for r in fold_results) if fold_results else 0.0,
            avg_pnl=statistics.mean(r.total_pnl for r in fold_results) if fold_results else 0.0,
            consistency_score=profitable / len(fold_results) if fold_results else 0.0,
        )

    async def monte_carlo_simulate(
        self, strategy_name: str, db=None
    ) -> MonteCarloResult:
        """Run Monte Carlo simulation to estimate PnL distribution."""
        signals = self._fetch_signals(strategy_name, db)
        if not signals:
            return MonteCarloResult(
                strategy_name=strategy_name,
                simulations=0,
                mean_pnl=0, median_pnl=0, std_pnl=0,
                percentile_5=0, percentile_95=0,
                probability_of_profit=0,
                max_drawdown_mean=0, max_drawdown_95=0,
            )

        pnls = [s.get("pnl", 0.0) for s in signals if s.get("pnl") is not None]
        if not pnls:
            pnls = [0.0]

        sim_results: list[float] = []
        drawdowns: list[float] = []

        for _ in range(self.config.monte_carlo_sims):
            shuffled = random.sample(pnls, len(pnls))
            cumulative = 0.0
            peak = 0.0
            max_dd = 0.0
            for p in shuffled:
                cumulative += p
                peak = max(peak, cumulative)
                max_dd = min(max_dd, cumulative - peak)
            sim_results.append(cumulative)
            drawdowns.append(abs(max_dd))

        sim_results.sort()
        drawdowns.sort()
        n = len(sim_results)
        profitable = sum(1 for p in sim_results if p > 0)

        return MonteCarloResult(
            strategy_name=strategy_name,
            simulations=self.config.monte_carlo_sims,
            mean_pnl=statistics.mean(sim_results),
            median_pnl=statistics.median(sim_results),
            std_pnl=statistics.stdev(sim_results) if len(sim_results) > 1 else 0.0,
            percentile_5=sim_results[int(n * 0.05)],
            percentile_95=sim_results[int(n * 0.95)],
            probability_of_profit=profitable / n,
            max_drawdown_mean=statistics.mean(drawdowns),
            max_drawdown_95=drawdowns[int(n * 0.95)],
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _backtest_single(
        self, strategy_name: str, db=None
    ) -> StrategyComparisonResult:
        """Run a single-strategy backtest."""
        signals = self._fetch_signals(strategy_name, db)
        if not signals:
            return self._empty_result(strategy_name)
        return self._simulate_signals(signals, strategy_name)

    def _fetch_signals(self, strategy_name: str, db=None) -> list[dict]:
        """Fetch historical signals/trades from DB for backtesting."""
        from backend.models.database import Trade, Signal, SessionLocal

        _owned = db is None
        if _owned:
            db = SessionLocal()
        try:
            signals = (
                db.query(Signal)
                .filter(
                    Signal.strategy == strategy_name,
                    Signal.timestamp >= self.config.start_date,
                    Signal.timestamp <= self.config.end_date,
                )
                .all()
            )
            if signals:
                return [
                    {
                        "timestamp": s.timestamp,
                        "price": getattr(s, "price", 0.5),
                        "edge": getattr(s, "edge", 0.0),
                        "size": getattr(s, "size", self.config.max_trade_size),
                        "pnl": getattr(s, "pnl", None),
                        "result": getattr(s, "result", None),
                    }
                    for s in signals
                ]

            # Fallback to trades
            trades = (
                db.query(Trade)
                .filter(
                    Trade.strategy == strategy_name,
                    Trade.timestamp >= self.config.start_date,
                    Trade.timestamp <= self.config.end_date,
                    Trade.settled,
                )
                .all()
            )
            return [
                {
                    "timestamp": t.timestamp,
                    "price": getattr(t, "entry_price", 0.5),
                    "edge": getattr(t, "edge", 0.0),
                    "size": getattr(t, "size", self.config.max_trade_size),
                    "pnl": getattr(t, "pnl", 0.0),
                    "result": getattr(t, "result", None),
                }
                for t in trades
            ]
        finally:
            if _owned:
                db.close()

    def _simulate_signals(
        self, signals: list[dict], label: str
    ) -> StrategyComparisonResult:
        """Simulate trades from signals and compute metrics."""
        bankroll = self.config.initial_bankroll
        equity = [{"timestamp": signals[0].get("timestamp"), "bankroll": bankroll}] if signals else []
        trades: list[dict] = []
        wins = 0
        total_costs = 0.0

        for sig in signals:
            price = sig.get("price", 0.5)
            size = min(sig.get("size", self.config.max_trade_size), bankroll * 0.25)
            edge = sig.get("edge", 0.0)
            pnl = sig.get("pnl")

            # Transaction costs
            fee = size * self.config.platform_fee_pct
            slip = size * self.config.slippage_pct
            cost = fee + slip
            total_costs += cost

            if pnl is None:
                pnl = (edge - cost / size) * size if edge > 0 else -cost

            net_pnl = pnl - cost
            bankroll += net_pnl
            if net_pnl > 0:
                wins += 1
            trades.append({"pnl": net_pnl, "size": size, "edge": edge})
            equity.append({
                "timestamp": sig.get("timestamp"),
                "bankroll": bankroll,
            })

        n = len(trades)
        if n == 0:
            return self._empty_result(label)

        pnl_values = [t["pnl"] for t in trades]
        total_pnl = sum(pnl_values)
        win_rate = wins / n
        avg_edge = statistics.mean(t["edge"] for t in trades)
        avg_size = statistics.mean(t["size"] for t in trades)

        # Sharpe ratio (annualized, assuming daily)
        mean_ret = statistics.mean(pnl_values)
        std_ret = statistics.stdev(pnl_values) if n > 1 else 1.0
        sharpe = (mean_ret / std_ret) * (252 ** 0.5) if std_ret > 0 else 0.0

        # Max drawdown
        peak = self.config.initial_bankroll
        max_dd = 0.0
        for eq in equity:
            if eq["bankroll"] > peak:
                peak = eq["bankroll"]
            dd = (peak - eq["bankroll"]) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)

        # Profit factor
        gross_profit = sum(p for p in pnl_values if p > 0)
        gross_loss = abs(sum(p for p in pnl_values if p < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        return StrategyComparisonResult(
            strategy_name=label,
            total_trades=n,
            winning_trades=wins,
            win_rate=win_rate,
            total_pnl=total_pnl,
            sharpe_ratio=sharpe,
            max_drawdown=max_dd,
            profit_factor=profit_factor,
            avg_trade_size=avg_size,
            avg_edge=avg_edge,
            return_pct=(bankroll - self.config.initial_bankroll) / self.config.initial_bankroll * 100,
            equity_curve=equity,
            transaction_costs=total_costs,
        )

    def _split_walk_forward(
        self, signals: list[dict]
    ) -> list[tuple[list[dict], list[dict]]]:
        """Split signals into walk-forward train/test folds."""
        n = len(signals)
        fold_size = n // self.config.walk_forward_folds
        folds: list[tuple[list[dict], list[dict]]] = []

        for i in range(self.config.walk_forward_folds):
            start = i * fold_size
            end = min(start + fold_size, n)
            fold_signals = signals[start:end]
            split_idx = int(len(fold_signals) * self.config.train_ratio)
            train = fold_signals[:split_idx]
            test = fold_signals[split_idx:]
            if train and test:
                folds.append((train, test))

        return folds

    @staticmethod
    def _empty_result(name: str) -> StrategyComparisonResult:
        return StrategyComparisonResult(
            strategy_name=name,
            total_trades=0,
            winning_trades=0,
            win_rate=0.0,
            total_pnl=0.0,
            sharpe_ratio=0.0,
            max_drawdown=0.0,
            profit_factor=0.0,
            avg_trade_size=0.0,
            avg_edge=0.0,
            return_pct=0.0,
        )
