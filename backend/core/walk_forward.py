"""Walk-forward backtesting engine with parameter sweep support."""

import itertools
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from backend.core.backtester import BacktestConfig, BacktestEngine, BacktestResult

from loguru import logger


@dataclass
class WalkForwardWindow:
    """A single in-sample / out-of-sample window."""

    window_num: int
    in_sample_start: datetime
    in_sample_end: datetime
    out_sample_start: datetime
    out_sample_end: datetime
    in_sample_result: Optional[BacktestResult] = None
    out_sample_result: Optional[BacktestResult] = None


@dataclass
class WalkForwardResult:
    """Results from walk-forward validation."""

    strategy: str
    windows: list[WalkForwardWindow]
    in_sample_sharpe: float = 0.0
    out_sample_sharpe: float = 0.0
    overfit_ratio: float = 0.0  # out_sample / in_sample (closer to 1.0 = less overfit)
    total_out_sample_pnl: float = 0.0
    out_sample_win_rate: float = 0.0
    params: dict = field(default_factory=dict)


@dataclass
class SweepResult:
    """Result of a single parameter combination sweep."""

    params: dict
    walk_forward: WalkForwardResult
    rank_score: float = 0.0  # out-of-sample Sharpe


class WalkForwardEngine:
    """Walk-forward validation with rolling windows and parameter sweeps."""

    def __init__(
        self,
        initial_bankroll: float = 100.0,
        kelly_fraction: float = 0.05,
        max_trade_size: float = 8.0,
        slippage: float = 0.01,
    ):
        self.initial_bankroll = initial_bankroll
        self.kelly_fraction = kelly_fraction
        self.max_trade_size = max_trade_size
        self.slippage = slippage

    async def run(
        self,
        db: Session,
        strategy: str,
        start_date: datetime,
        end_date: datetime,
        in_sample_days: int = 60,
        out_sample_days: int = 14,
    ) -> WalkForwardResult:
        """Run walk-forward validation with rolling windows.

        Splits the date range into rolling windows:
        [in_sample_days training | out_sample_days testing]
        Then rolls forward by out_sample_days and repeats.
        """
        windows = []
        window_num = 0
        current_start = start_date

        while (
            current_start + timedelta(days=in_sample_days + out_sample_days) <= end_date
        ):
            in_start = current_start
            in_end = current_start + timedelta(days=in_sample_days)
            out_start = in_end
            out_end = out_start + timedelta(days=out_sample_days)

            window = WalkForwardWindow(
                window_num=window_num,
                in_sample_start=in_start,
                in_sample_end=in_end,
                out_sample_start=out_start,
                out_sample_end=out_end,
            )

            # Run in-sample backtest
            in_config = BacktestConfig(
                strategy_name=strategy,
                start_date=in_start,
                end_date=in_end,
                initial_bankroll=self.initial_bankroll,
                kelly_fraction=self.kelly_fraction,
                max_trade_size=self.max_trade_size,
                slippage=self.slippage,
            )
            in_engine = BacktestEngine(in_config)
            window.in_sample_result = await in_engine.run(db)

            # Run out-of-sample backtest
            out_config = BacktestConfig(
                strategy_name=strategy,
                start_date=out_start,
                end_date=out_end,
                initial_bankroll=self.initial_bankroll,
                kelly_fraction=self.kelly_fraction,
                max_trade_size=self.max_trade_size,
                slippage=self.slippage,
            )
            out_engine = BacktestEngine(out_config)
            window.out_sample_result = await out_engine.run(db)

            windows.append(window)
            window_num += 1
            current_start = out_end  # Roll forward

        # Aggregate results
        in_sharpes = [
            w.in_sample_result.sharpe_ratio
            for w in windows
            if w.in_sample_result and w.in_sample_result.total_trades > 0
        ]
        out_sharpes = [
            w.out_sample_result.sharpe_ratio
            for w in windows
            if w.out_sample_result and w.out_sample_result.total_trades > 0
        ]

        avg_in_sharpe = sum(in_sharpes) / len(in_sharpes) if in_sharpes else 0.0
        avg_out_sharpe = sum(out_sharpes) / len(out_sharpes) if out_sharpes else 0.0
        overfit_ratio = avg_out_sharpe / avg_in_sharpe if avg_in_sharpe != 0 else 0.0

        total_oos_pnl = sum(
            w.out_sample_result.total_pnl for w in windows if w.out_sample_result
        )

        total_oos_trades = sum(
            w.out_sample_result.total_trades for w in windows if w.out_sample_result
        )
        total_oos_wins = sum(
            w.out_sample_result.winning_trades for w in windows if w.out_sample_result
        )
        oos_win_rate = (
            total_oos_wins / total_oos_trades if total_oos_trades > 0 else 0.0
        )

        result = WalkForwardResult(
            strategy=strategy,
            windows=windows,
            in_sample_sharpe=round(avg_in_sharpe, 4),
            out_sample_sharpe=round(avg_out_sharpe, 4),
            overfit_ratio=round(overfit_ratio, 4),
            total_out_sample_pnl=round(total_oos_pnl, 4),
            out_sample_win_rate=round(oos_win_rate, 4),
        )

        logger.info(
            f"Walk-forward {strategy}: {len(windows)} windows, "
            f"IS Sharpe={avg_in_sharpe:.2f}, OOS Sharpe={avg_out_sharpe:.2f}, "
            f"overfit={overfit_ratio:.2f}, OOS PnL=${total_oos_pnl:.2f}"
        )

        return result

    async def sweep(
        self,
        db: Session,
        strategy: str,
        param_grid: dict,
        start_date: datetime,
        end_date: datetime,
        in_sample_days: int = 60,
        out_sample_days: int = 14,
        max_combinations: int = 50,
    ) -> list[SweepResult]:
        """Run walk-forward validation across a grid of parameters.

        param_grid: dict of {param_name: [value1, value2, ...]}
        Returns results sorted by out-of-sample Sharpe (best first).
        """
        # Generate all parameter combinations
        keys = list(param_grid.keys())
        values = list(param_grid.values())
        combinations = list(itertools.product(*values))

        if len(combinations) > max_combinations:
            logger.warning(
                f"Parameter grid has {len(combinations)} combinations, "
                f"capping at {max_combinations}"
            )
            combinations = combinations[:max_combinations]

        results = []
        for combo in combinations:
            params = dict(zip(keys, combo))

            # Apply params to walk-forward config
            config_overrides = {}
            if "kelly_fraction" in params:
                config_overrides["kelly_fraction"] = params["kelly_fraction"]
            if "max_trade_size" in params:
                config_overrides["max_trade_size"] = params["max_trade_size"]
            if "slippage" in params:
                config_overrides["slippage"] = params["slippage"]

            engine = WalkForwardEngine(
                initial_bankroll=self.initial_bankroll,
                kelly_fraction=config_overrides.get(
                    "kelly_fraction", self.kelly_fraction
                ),
                max_trade_size=config_overrides.get(
                    "max_trade_size", self.max_trade_size
                ),
                slippage=config_overrides.get("slippage", self.slippage),
            )

            wf_result = await engine.run(
                db,
                strategy,
                start_date,
                end_date,
                in_sample_days,
                out_sample_days,
            )
            wf_result.params = params

            results.append(
                SweepResult(
                    params=params,
                    walk_forward=wf_result,
                    rank_score=wf_result.out_sample_sharpe,
                )
            )

        # Sort by out-of-sample Sharpe (best first)
        results.sort(key=lambda r: r.rank_score, reverse=True)

        if results:
            best = results[0]
            logger.info(
                f"Sweep complete: {len(results)} combinations tested. "
                f"Best params: {best.params} (OOS Sharpe={best.rank_score:.4f})"
            )

        return results


import math  # noqa: E402
from dataclasses import dataclass  # noqa: E402


@dataclass
class ValidationResult:
    approved: bool
    old_sharpe: float
    new_sharpe: float
    old_drawdown: float
    new_drawdown: float
    reason: str


def _compute_sharpe(pnls: list) -> float:
    if len(pnls) < 2:
        return 0.0
    mean = sum(pnls) / len(pnls)
    variance = sum((p - mean) ** 2 for p in pnls) / len(pnls)
    std = math.sqrt(variance) if variance > 0 else 1e-9
    return (mean / std) * math.sqrt(len(pnls))


def _compute_max_drawdown(pnls: list) -> float:
    if not pnls:
        return 0.0
    peak = 0.0
    cumulative = 0.0
    max_dd = 0.0
    for p in pnls:
        cumulative += p
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd
    return max_dd


class WalkForwardValidator:
    SHARPE_IMPROVEMENT_THRESHOLD = 0.1
    DRAWDOWN_TOLERANCE = 1.05

    def validate_param_change(
        self,
        strategy: str,
        old_params: dict,
        new_params: dict,
        db,
    ) -> ValidationResult:
        from backend.core.outcome_repository import get_recent_outcomes

        outcomes = get_recent_outcomes(strategy, 30, db)
        if len(outcomes) < 10:
            return ValidationResult(
                approved=True,
                old_sharpe=0.0,
                new_sharpe=0.0,
                old_drawdown=0.0,
                new_drawdown=0.0,
                reason="insufficient data — change approved by default",
            )

        old_threshold = old_params.get("edge_threshold", 0.0)
        new_threshold = new_params.get("edge_threshold", 0.0)

        old_pnls = [
            o.pnl
            for o in outcomes
            if o.pnl is not None and (o.edge_at_entry or 0.0) >= old_threshold
        ]
        new_pnls = [
            o.pnl
            for o in outcomes
            if o.pnl is not None and (o.edge_at_entry or 0.0) >= new_threshold
        ]

        old_sharpe = _compute_sharpe(old_pnls)
        new_sharpe = _compute_sharpe(new_pnls)
        old_dd = _compute_max_drawdown(old_pnls)
        new_dd = _compute_max_drawdown(new_pnls)

        if new_sharpe < old_sharpe + self.SHARPE_IMPROVEMENT_THRESHOLD:
            reason = (
                f"Sharpe did not improve enough: {old_sharpe:.3f} -> {new_sharpe:.3f} "
                f"(need +{self.SHARPE_IMPROVEMENT_THRESHOLD})"
            )
            logger.warning(f"[WalkForwardValidator] {strategy}: {reason}")
            return ValidationResult(
                approved=False,
                old_sharpe=old_sharpe,
                new_sharpe=new_sharpe,
                old_drawdown=old_dd,
                new_drawdown=new_dd,
                reason=reason,
            )

        if old_dd > 0 and new_dd > old_dd * self.DRAWDOWN_TOLERANCE:
            reason = (
                f"Drawdown increased too much: {old_dd:.3f} -> {new_dd:.3f} "
                f"(max allowed {old_dd * self.DRAWDOWN_TOLERANCE:.3f})"
            )
            logger.warning(f"[WalkForwardValidator] {strategy}: {reason}")
            return ValidationResult(
                approved=False,
                old_sharpe=old_sharpe,
                new_sharpe=new_sharpe,
                old_drawdown=old_dd,
                new_drawdown=new_dd,
                reason=reason,
            )

        reason = f"approved: Sharpe {old_sharpe:.3f} -> {new_sharpe:.3f}, drawdown {old_dd:.3f} -> {new_dd:.3f}"
        logger.info(f"[WalkForwardValidator] {strategy}: {reason}")
        return ValidationResult(
            approved=True,
            old_sharpe=old_sharpe,
            new_sharpe=new_sharpe,
            old_drawdown=old_dd,
            new_drawdown=new_dd,
            reason=reason,
        )
