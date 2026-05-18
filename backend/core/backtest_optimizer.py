"""
Backtest Parameter Optimizer — grid search + Bayesian optimization.

Provides parameter optimization for trading strategies using:
- Grid search over parameter combinations
- Walk-forward validation for each combination
- Ranking by out-of-sample Sharpe ratio
- Integration with PyBrokerEngine for fast vectorized backtests

Optimal parameters are validated through walk-forward analysis
to avoid overfitting.
"""

import itertools
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

import numpy as np

from backend.core.pybroker_backtest import (
    PyBrokerConfig,
    PyBrokerEngine,
    PyBrokerResult,
    TradeRecord,
    WalkForwardResult,
)

from loguru import logger


@dataclass
class OptimizationResult:
    """Result for a single parameter combination."""

    params: dict[str, Any]
    backtest: PyBrokerResult
    walk_forward: Optional[WalkForwardResult] = None
    oos_sharpe: float = 0.0  # out-of-sample Sharpe (primary ranking metric)
    is_sharpe: float = 0.0  # in-sample Sharpe
    overfit_ratio: float = 0.0
    score: float = 0.0  # composite ranking score


@dataclass
class OptimizationRun:
    """Full optimization run results."""

    strategy_name: str
    param_grid: dict[str, list]
    results: list[OptimizationResult]
    best_params: dict[str, Any]
    best_oos_sharpe: float
    total_combinations: int
    n_windows_avg: float  # average walk-forward windows per combo


class BacktestOptimizer:
    """
    Grid search optimizer for strategy parameters.

    Tests all parameter combinations via walk-forward analysis
    and ranks by out-of-sample performance to find robust settings.
    """

    def __init__(
        self,
        initial_bankroll: float = 1000.0,
        train_days: int = 60,
        test_days: int = 14,
        max_combinations: int = 100,
        min_trades_per_window: int = 3,
    ):
        self.initial_bankroll = initial_bankroll
        self.train_days = train_days
        self.test_days = test_days
        self.max_combinations = max_combinations
        self.min_trades_per_window = min_trades_per_window

    def grid_search(
        self,
        trades: list[TradeRecord],
        param_grid: dict[str, list],
        strategy_name: str = "optimizer",
        use_walk_forward: bool = True,
    ) -> OptimizationRun:
        """
        Grid search over parameter combinations.

        For each combination:
        1. Optionally run walk-forward analysis
        2. Run full backtest with those params
        3. Rank by OOS Sharpe (or in-sample if no walk-forward)

        Args:
            trades: Historical trade records.
            param_grid: Dict of param_name -> list of values to test.
            strategy_name: Name for logging.
            use_walk_forward: Whether to use walk-forward validation.

        Returns:
            OptimizationRun with all results ranked by OOS Sharpe.
        """
        if not trades:
            return OptimizationRun(
                strategy_name=strategy_name,
                param_grid=param_grid,
                results=[],
                best_params={},
                best_oos_sharpe=0.0,
                total_combinations=0,
                n_windows_avg=0.0,
            )

        # Generate combinations
        keys = list(param_grid.keys())
        values = list(param_grid.values())
        combinations = list(itertools.product(*values))

        if len(combinations) > self.max_combinations:
            logger.warning(
                f"Grid has {len(combinations)} combos, capping at {self.max_combinations}"
            )
            combinations = combinations[:self.max_combinations]

        results: list[OptimizationResult] = []
        engine = PyBrokerEngine()

        for combo in combinations:
            params = dict(zip(keys, combo))

            # Build config from params
            config = self._build_config(params)

            # Apply parameter-based filtering to trades
            filtered_trades = self._filter_trades(trades, params)

            if not filtered_trades:
                continue

            # Walk-forward validation
            wf_result = None
            oos_sharpe = 0.0
            is_sharpe = 0.0
            overfit_ratio = 0.0

            if use_walk_forward:
                wf_result = engine.walk_forward(
                    filtered_trades,
                    train_days=self.train_days,
                    test_days=self.test_days,
                )
                oos_sharpe = wf_result.oos_sharpe
                overfit_ratio = wf_result.overfit_ratio
                # Compute avg in-sample Sharpe from windows
                is_sharpes = [
                    w.train_result.sharpe_ratio
                    for w in wf_result.windows
                    if w.train_result and w.train_result.total_trades > 0
                ]
                is_sharpe = sum(is_sharpes) / len(is_sharpes) if is_sharpes else 0.0

            # Full backtest
            engine_with_config = PyBrokerEngine(config)
            bt_result = engine_with_config.run_from_trades(filtered_trades)

            if not use_walk_forward:
                oos_sharpe = bt_result.sharpe_ratio
                is_sharpe = bt_result.sharpe_ratio

            # Composite score: OOS Sharpe penalized by overfitting
            score = oos_sharpe
            if overfit_ratio > 1.5:
                score *= 0.5  # Heavy penalty for overfitting

            results.append(OptimizationResult(
                params=params,
                backtest=bt_result,
                walk_forward=wf_result,
                oos_sharpe=oos_sharpe,
                is_sharpe=is_sharpe,
                overfit_ratio=overfit_ratio,
                score=score,
            ))

        # Sort by composite score (best first)
        results.sort(key=lambda r: r.score, reverse=True)

        best_params = results[0].params if results else {}
        best_oos = results[0].oos_sharpe if results else 0.0
        n_windows = 0.0
        if results and results[0].walk_forward:
            n_windows = len(results[0].walk_forward.windows)

        run = OptimizationRun(
            strategy_name=strategy_name,
            param_grid=param_grid,
            results=results,
            best_params=best_params,
            best_oos_sharpe=best_oos,
            total_combinations=len(combinations),
            n_windows_avg=n_windows,
        )

        logger.info(
            f"Grid search [{strategy_name}]: {len(combinations)} combos, "
            f"best OOS Sharpe={best_oos:.4f}, best params={best_params}"
        )

        return run

    def random_search(
        self,
        trades: list[TradeRecord],
        param_distributions: dict[str, tuple[float, float]],
        n_trials: int = 50,
        strategy_name: str = "optimizer",
        seed: Optional[int] = None,
    ) -> OptimizationRun:
        """
        Random search over parameter space.

        More efficient than grid search for high-dimensional spaces.
        Samples uniformly from parameter ranges.

        Args:
            trades: Historical trade records.
            param_distributions: Dict of param_name -> (min_val, max_val).
            n_trials: Number of random samples.
            strategy_name: Name for logging.
            seed: Random seed for reproducibility.
        """
        import random as rng

        rng_gen = rng.Random(seed)
        results: list[OptimizationResult] = []
        engine = PyBrokerEngine()

        for trial in range(n_trials):
            params = {}
            for name, (lo, hi) in param_distributions.items():
                params[name] = round(rng_gen.uniform(lo, hi), 4)

            config = self._build_config(params)
            filtered_trades = self._filter_trades(trades, params)

            if not filtered_trades:
                continue

            wf_result = engine.walk_forward(
                filtered_trades,
                train_days=self.train_days,
                test_days=self.test_days,
            )

            engine_cfg = PyBrokerEngine(config)
            bt_result = engine_cfg.run_from_trades(filtered_trades)

            oos_sharpe = wf_result.oos_sharpe
            is_sharpes = [
                w.train_result.sharpe_ratio
                for w in wf_result.windows
                if w.train_result and w.train_result.total_trades > 0
            ]
            is_sharpe = sum(is_sharpes) / len(is_sharpes) if is_sharpes else 0.0
            overfit = wf_result.overfit_ratio

            score = oos_sharpe
            if overfit > 1.5:
                score *= 0.5

            results.append(OptimizationResult(
                params=params,
                backtest=bt_result,
                walk_forward=wf_result,
                oos_sharpe=oos_sharpe,
                is_sharpe=is_sharpe,
                overfit_ratio=overfit,
                score=score,
            ))

        results.sort(key=lambda r: r.score, reverse=True)

        best_params = results[0].params if results else {}
        best_oos = results[0].oos_sharpe if results else 0.0
        n_windows = 0.0
        if results and results[0].walk_forward:
            n_windows = len(results[0].walk_forward.windows)

        run = OptimizationRun(
            strategy_name=strategy_name,
            param_grid={k: [v] for k, v in best_params.items()},
            results=results,
            best_params=best_params,
            best_oos_sharpe=best_oos,
            total_combinations=n_trials,
            n_windows_avg=n_windows,
        )

        logger.info(
            f"Random search [{strategy_name}]: {n_trials} trials, "
            f"best OOS Sharpe={best_oos:.4f}, best params={best_params}"
        )

        return run

    def _build_config(self, params: dict[str, Any]) -> PyBrokerConfig:
        """Build PyBrokerConfig from parameter dict."""
        config = PyBrokerConfig(initial_bankroll=self.initial_bankroll)
        if "kelly_fraction" in params:
            config.kelly_fraction = float(params["kelly_fraction"])
        if "max_trade_size" in params:
            config.max_trade_size = float(params["max_trade_size"])
        if "slippage_bps" in params:
            config.slippage_bps = float(params["slippage_bps"])
        if "min_edge" in params:
            config.min_edge = float(params["min_edge"])
        if "commission_bps" in params:
            config.commission_bps = float(params["commission_bps"])
        if "daily_loss_limit" in params:
            config.daily_loss_limit = float(params["daily_loss_limit"])
        return config

    def _filter_trades(
        self, trades: list[TradeRecord], params: dict[str, Any]
    ) -> list[TradeRecord]:
        """Filter trades based on parameter constraints (e.g., min_edge)."""
        min_edge = float(params.get("min_edge", 0.0))
        if min_edge > 0:
            return [t for t in trades if t.edge >= min_edge]
        return trades
