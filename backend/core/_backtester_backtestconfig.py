"""Carved verbatim out of ``backend/core/backtester.py`` — statements moved, no logic changed."""

from __future__ import annotations

from .backtester import (
    dataclass,
)

from . import backtester as _facade

@dataclass
class BacktestConfig:
    strategy_name: str
    start_date: _facade.datetime
    end_date: _facade.datetime
    initial_bankroll: float = 100.0
    kelly_fraction: float = 0.0625
    max_trade_size: float = 10.0
    max_position_fraction: float = 0.10
    max_total_exposure: float = 0.60
    daily_loss_limit: float = 15.0
    slippage: float = 0.01  # Spread cost per trade in dollars (flat mode)
    # Cost-model fidelity: binary-market spread scales with price level —
    # a flat $0.01 is 2% at entry 0.50 but 20% at entry 0.05. "bps" mode
    # charges slippage_bps × entry_price, the realistic convention.
    slippage_mode: str = "flat"  # "flat" | "bps"
    slippage_bps: float = 100.0  # bps of entry price when slippage_mode="bps"
    # --- Sizing doctrine (autoresearch iteration 1) ---
    # "binary_kelly": f* = ((p*(1/price)-q)/(1/price)) via
    #   learning.calibration.kelly_fraction — the mathematically correct
    #   Kelly stake for binary markets. "edge_proportional": legacy
    #   bankroll*kelly*edge heuristic.
    sizing_mode: str = "binary_kelly"
    kelly_cap: float = 0.25  # max fraction of bankroll per trade
    drawdown_throttle: bool = True  # scale size down as drawdown deepens
    drawdown_throttle_floor: float = 0.25  # min size multiplier under throttle
    # --- Entry quality gates (iteration 2) ---
    # Skip signals below these floors before sizing. 0.0 = legacy behavior.
    min_edge_threshold: float = 0.0
    min_model_probability: float = 0.0
    # Walk-forward bucket calibration (iteration 5): blend raw model
    # probability with realized win-rate of PRIOR settled trades in the same
    # entry-price bucket (Laplace shrinkage, strictly past-only). 0 disables.
    calibration_shrinkage: float = 0.0
    calibration_bucket: float = 0.1
    calibration_key: str = "price"  # "price" | "edge" | "price_dir" — bucket key
    # Volatility-scaled Kelly (segment 2): scale f* by
    # clip(target_vol / rolling_vol, floor, 1.0) where rolling_vol is the
    # stdev of the last `vol_lookback` settled per-trade returns as a
    # fraction of bankroll. Normalizes risk-taking to realized volatility.
    vol_scaling: bool = False
    vol_target: float = 0.02      # target per-trade return volatility
    vol_lookback: int = 20
    vol_scale_floor: float = 0.5
@dataclass
class BacktestTrade:
    timestamp: _facade.datetime
    market_ticker: str
    direction: str
    entry_price: float
    size: float
    edge: float
    settlement_value: float | None = None
    pnl: float | None = None
    settled: bool = False
@dataclass
class BacktestResult:
    config: BacktestConfig
    trades: list[BacktestTrade]
    equity_curve: list[dict]  # [{timestamp, bankroll}]
    total_pnl: float
    total_trades: int
    winning_trades: int
    win_rate: float
    max_drawdown: float
    sharpe_ratio: float
    sortino_ratio: float
    profit_factor: float
    avg_edge: float
    avg_trade_size: float
    final_bankroll: float
    return_pct: float
