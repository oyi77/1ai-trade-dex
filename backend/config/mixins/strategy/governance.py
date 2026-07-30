"""Strategy governance, kill thresholds, evolution, and health monitoring."""
from dataclasses import dataclass
from typing import Optional


@dataclass
class StrategyGovernanceMixin:
    """Governance thresholds, crash protection, auto-improve, evolution, and mesh health."""

    # Strategy governance thresholds
    KILL_WIN_RATE: float = (
        0.30  # win rate below which strategy is auto-killed (was 0.05 — crypto_oracle disaster)
    )
    KILL_SHARPE: float = -2.0  # Sharpe ratio below which strategy is auto-killed
    KILL_DRAWDOWN: float = 0.50  # drawdown fraction above which strategy is auto-killed
    KILL_CUMULATIVE_LOSS: float = -500.0  # cumulative PnL below which strategy is auto-killed
    KILL_AVG_LOSS_RATIO: float = 5.0  # avg_loss/avg_win ratio above which strategy is auto-killed
    KILL_CONSECUTIVE_LOSSES: int = 7  # consecutive losses before auto-kill
    KILL_ZERO_WR_AFTER_N: int = 20  # auto-kill if 0% win rate after N trades
    WARN_WIN_RATE: float = 0.15  # win rate below which strategy gets warning flag
    WARN_SHARPE: float = -1.0  # Sharpe below which strategy gets warning
    WARN_BRIER: float = 0.4  # calibration threshold
    WARN_PSI: float = 0.25  # drift detection threshold
    MIN_WARMUP_TRADES: int = 20  # trades before strategy governance activates
    DEGRADATION_WR_THRESHOLD: float = (
        0.35  # win rate drop triggering degradation review
    )
    DEGRADATION_SHARPE_THRESHOLD: float = (
        -0.5
    )  # Sharpe drop triggering degradation review
    MAX_DEGRADATIONS_BEFORE_REVIEW: int = (
        2  # consecutive degradations before forced review
    )

    REHAB_CATASTROPHIC_WR_FLOOR: float = 0.05  # min WR to enter strategy rehabilitation
    REHAB_CATASTROPHIC_MIN_TRADES: int = 30  # min trades before rehab evaluation
    STRATEGY_MIN_WIN_RATE: float = 0.45  # circuit breaker kill threshold per strategy
    STRATEGY_MIN_PNL_RATIO: float = 0.05  # circuit breaker PnL kill threshold
    STRATEGY_WINRATE_LOOKBACK_TRADES: int = 20  # trade lookback for WR calculation
    STRATEGY_PNL_LOOKBACK_DAYS: int = 30  # day lookback for PnL evaluation
    RISK_MAX_DAILY_LOSS_PER_STRATEGY_USD: float = (
        50.0  # hard-dollar daily stop per strategy
    )
    RISK_MAX_TOTAL_DRAWDOWN_PCT: float = 10.0  # % of total balance drawdown limit
    PER_TRADE_MAX_LOSS_PCT: float = 0.05  # no single trade > 5% of bankroll
    MAX_DAILY_TRADES_PER_STRATEGY: int = 0  # 0 = unlimited (profitable strategies only)
    PORTFOLIO_CIRCUIT_BREAKER_PCT: float = (
        0.25  # disable ALL strategies if portfolio down >25% from peak
    )
    PROPOSAL_ROLLBACK_THRESHOLD: float = -0.1  # Sharpe rollback trigger
    PROPOSAL_IMPACT_WINDOW_HOURS: int = 48  # hours to monitor after proposal exec
    PROPOSAL_MIN_TRADES_FOR_IMPACT: int = 5  # min trades for impact measurement
    WR_MONITOR_MIN_TRADES: int = 10  # min trades for win-rate monitoring
    WR_MONITOR_WR_THRESHOLD: float = 0.50  # win-rate alert threshold
    WR_MONITOR_CHECK_INTERVAL_HOURS: int = 6  # polling interval for WR monitor
    WR_MONITOR_LOOKBACK_DAYS: int = 3  # data window for WR calculation
    AGI_TUNER_MIN_TRADES_FOR_TUNING: int = 15  # min trades before auto-tuning
    AGI_TUNER_WIN_RATE_FLOOR: float = 0.40  # trigger tuning below this WR
    AGI_TUNER_WIN_RATE_CEILING: float = 0.60  # consider loosening above this WR
    AGI_TUNER_MAX_PARAM_CHANGE_PCT: float = 0.30  # hard cap on any single param change
    AGI_TUNER_ROLLBACK_WINDOW: int = 10  # trades to monitor after tuning change
    AGI_TUNER_ROLLBACK_DEGRADATION: float = 0.15  # >15% WR drop triggers revert

    # Position sizing
    POSITION_MIN_USD: float = 5.0  # minimum position size
    POSITION_MAX_USD: float = 50.0  # maximum position size

    # Strategy executor
    MAX_CONCURRENT_TRADES: int = 6  # max parallel trade executions

    # Crash guardian
    CRASH_CHECK_INTERVAL: int = 30  # seconds between health checks
    CRASH_MEMORY_WARN_MB: int = 1024  # MB threshold for memory warning
    CRASH_MEMORY_RESTART_MB: int = 2048  # MB threshold for restart
    CRASH_MAX_UNHEALTHY: int = 3  # consecutive unhealthy checks before action

    # Auto-improve (learning pipeline)
    AUTO_IMPROVE_MIN_CONFIDENCE: float = 0.8  # confidence threshold for auto-apply
    AUTO_IMPROVE_MAX_PARAM_CHANGE: float = 0.30  # max fraction change per param
    AUTO_IMPROVE_ROLLBACK_WINDOW: int = 10  # trades to monitor post-change
    AUTO_IMPROVE_ROLLBACK_DEGRADATION: float = 0.15  # perf drop triggering rollback

    # LLM cost tracking
    LLM_DAILY_BUDGET_DEFAULT: float = 10.0  # default daily LLM budget in USD

    # Evolution promotion thresholds
    EVOLUTION_SHADOW_PAPER_MIN_TRADES: int = 20
    EVOLUTION_SHADOW_PAPER_MIN_WIN_RATE: float = 0.45
    EVOLUTION_SHADOW_PAPER_MIN_SHARPE: float = 0.5
    EVOLUTION_PAPER_LIVE_MIN_TRADES: int = 50
    EVOLUTION_PAPER_LIVE_MIN_WIN_RATE: float = 0.50
    EVOLUTION_PAPER_LIVE_MIN_SHARPE: float = 0.8
    EVOLUTION_PAPER_LIVE_MAX_DRAWDOWN: float = 0.20
    EVOLUTION_AUTO_KILL_MAX_DRAWDOWN: float = 0.50
    EVOLUTION_AUTO_KILL_MIN_SHARPE: float = -2.0
    EVOLUTION_AUTO_KILL_MIN_WIN_RATE: float = 0.05

    # Auto-research evolver
    EVOLVER_WIN_RATE_FLOOR: float = 0.0
    EVOLVER_WIN_RATE_CEIL: float = 0.45
    EVOLVER_MIN_OUTCOMES: int = 10
    EVOLVER_BROKEN_WIN_RATE: float = 0.0
    EVOLVER_BROKEN_MIN_TRADES: int = 30
    EVOLVER_VARIANTS_PER_STRATEGY: int = 3
    EVOLVER_PARAM_PERTURBATION: float = 0.25

    # Mesh health monitoring
    MESH_SUCCESS_RATE_WINDOW: int = 20
    MESH_DEGRADED_THRESHOLD: float = 0.90
    MESH_FAILED_THRESHOLD: float = 0.50
    MESH_CONSECUTIVE_FAILURE_THRESHOLD: int = 5
    MESH_RECOVERY_PROBE_INTERVAL: int = 60
    MESH_RECOVERY_SUCCESSES_NEEDED: int = 3
