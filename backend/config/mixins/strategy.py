"""Strategy params mixin — trading thresholds, indicators, governance, and strategy-specific settings."""

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StrategyParamsMixin:
    """Strategy-specific thresholds, limits, and parameters for all trading strategies."""

    # --------------------------------------------------------------------------
    # STRATEGY_PARAMS - Strategy-specific thresholds and limits
    # --------------------------------------------------------------------------
    # Trading parameters
    MIN_DEBATE_EDGE: float = 0.04  # debate threshold
    MIN_EDGE_THRESHOLD: float = 0.03  # minimum edge for signals
    MIN_EDGE_PP: float = 0.0  # minimum edge in percentage points for risk_manager
    MAX_ENTRY_PRICE: float = 0.80  # maximum entry price
    MAX_TRADES_PER_WINDOW: int = 20  # trades per scheduling window
    MAX_TRADES_PER_SCAN: int = 10  # trades per scan cycle
    AUTO_TRADER_BATCH_SIZE: int = 100  # batch size for auto-trader
    MAX_TOTAL_PENDING_TRADES: int = 50  # max pending trades
    STALE_TRADE_HOURS: int = 24  # hours before trade considered stale

    # Position sizing
    KELLY_FRACTION: float = 0.10  # Kelly fraction (0.10 = 10% Kelly)
    MAX_POSITION_FRACTION: float = 0.30  # max position as % of bankroll
    MAX_TOTAL_EXPOSURE_FRACTION: float = 0.70  # max total exposure
    CORRELATION_MULTIPLIER: float = (
        1.0  # same-category exposure multiplier (1.0=no inflation)
    )
    MAX_CORRELATED_EXPOSURE_PCT: float = (
        0.80  # max correlation-adjusted exposure % of bankroll
    )
    MAX_TRADE_SIZE: float = 100.0  # max single trade size in USD
    MIN_ORDER_USDC: float = 1.0  # minimum order size (CLOB minimum)
    PAPER_MIN_ORDER_USDC: float = (
        5.0  # minimum order size (paper — matches CLOB $5 minimum)
    )

    # Confidence and signal weights
    AUTO_APPROVE_MIN_CONFIDENCE: float = float(
        os.getenv("AUTO_APPROVE_MIN_CONFIDENCE", "0.25")
    )
    PAPER_AUTO_APPROVE_MIN_CONFIDENCE: float = float(
        os.getenv("PAPER_AUTO_APPROVE_MIN_CONFIDENCE", "0.20")  # Lower for bond_scanner cheap-token strategy
    )
    AI_SIGNAL_WEIGHT: float = 0.30  # AI weight in ensemble (max 0.50)
    LONGSHOT_NO_BIAS_WEIGHT: float = 0.10  # bias weight for longshot markets

    # Longshot Bias Strategy
    LONGSHOT_BIAS_MAX_PRICE: float = 0.30  # only trade below 30c
    LONGSHOT_BIAS_MIN_EV: float = 0.05  # minimum expected value
    LONGSHOT_BIAS_MAX_POSITION_USD: float = 20.0  # max position in USD
    LONGSHOT_BIAS_ENABLED: bool = False  # start disabled

    # Indicator weights (must sum to ~1.0)
    WEIGHT_RSI: float = 0.20
    WEIGHT_MOMENTUM: float = 0.35
    WEIGHT_VWAP: float = 0.20
    WEIGHT_SMA: float = 0.15
    WEIGHT_MARKET_SKEW: float = 0.10

    # Volume filters
    MIN_MARKET_VOLUME: float = 100.0  # minimum market volume
    MIN_WHALE_TRADE_USD: float = 1000.0  # minimum whale trade size

    # Strategy governance thresholds
    KILL_WIN_RATE: float = (
        0.30  # win rate below which strategy is auto-killed (was 0.05 — crypto_oracle disaster)
    )
    KILL_SHARPE: float = -2.0  # Sharpe ratio below which strategy is auto-killed
    KILL_DRAWDOWN: float = 0.50  # drawdown fraction above which strategy is auto-killed
    KILL_CUMULATIVE_LOSS: float = -500.0  # cumulative PnL below which strategy is auto-killed
    KILL_AVG_LOSS_RATIO: float = 5.0  # avg_loss/avg_win ratio above which strategy is auto-killed
    KILL_CONSECUTIVE_LOSSES: int = 7  # consecutive losses before auto-kill
    KILL_ZERO_WR_AFTER_N: int = 20  # auto-kill if 0% win rate after N trades (catches broken strategies fast)
    WARN_WIN_RATE: float = 0.15  # win rate below which strategy gets warning flag
    WARN_SHARPE: float = -1.0  # Sharpe below which strategy gets warning
    WARN_BRIER: float = 0.4  # calibration threshold
    WARN_PSI: float = 0.25  # drift detection threshold
    MIN_WARMUP_TRADES: int = 20  # trades before strategy governance activates (was 30 — too slow)
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

    # Scanner parameters
    SCANNER_PAGE_SIZE: int = 500
    SCANNER_SEMAPHORE_LIMIT: int = 50
    SCANNER_MIN_EDGE: float = 0.05
    SCANNER_STALE_THRESHOLD_SECONDS: float = 5.0
    SCANNER_MAX_MARKETS: int = 10000
    MARKET_UNIVERSE_CACHE_TTL_SECONDS: int = 300

    # Order executor thresholds (Phase 3: stricter copy-trade filtering)
    ORDER_EXECUTOR_MIN_WHALE_SIZE: float = 100.0
    ORDER_EXECUTOR_MIN_DAYS_TO_RESOLUTION: int = 7

    # Line movement detector
    LINE_MOVE_BASE_CONFIDENCE: float = 0.5
    LINE_MOVE_HUGE_THRESHOLD: float = 15.0
    LINE_MOVE_HUGE_BOOST: float = 0.2
    LINE_MOVE_LARGE_THRESHOLD: float = 10.0
    LINE_MOVE_LARGE_BOOST: float = 0.15
    LINE_MOVE_MEDIUM_THRESHOLD: float = 7.0
    LINE_MOVE_MEDIUM_BOOST: float = 0.1
    LINE_MOVE_SMALL_BOOST: float = 0.05
    LINE_MOVE_HIGH_VOL_THRESHOLD: float = 100000.0
    LINE_MOVE_HIGH_VOL_BOOST: float = 0.1
    LINE_MOVE_MED_VOL_THRESHOLD: float = 50000.0
    LINE_MOVE_MED_VOL_BOOST: float = 0.05
    LINE_MOVE_NEWS_BOOST: float = 0.1
    LINE_MOVE_MAX_CONFIDENCE: float = 0.95

    # Bond Scanner — tuned for tighter entry criteria (Phase 3)
    BOND_SCANNER_MIN_PRICE: float = 0.05  # Buy cheap tokens (5c-50c) for 10:1 risk/reward
    BOND_SCANNER_MAX_PRICE: float = 0.50  # Cap at 50c — above that, risk/reward is terrible
    BOND_SCANNER_MIN_DAYS_TO_RESOLUTION: float = 0.5
    BOND_SCANNER_KELLY_FRACTION: float = 0.15
    BOND_SCANNER_BANKROLL_PCT: float = 0.05
    BOND_SCANNER_MIN_EDGE: float = 0.05
    BOND_SCANNER_PROXIMITY_BOOST_SCALE: float = 0.01
    BOND_SCANNER_MAX_POSITION_SIZE: float = 5.0
    BOND_SCANNER_MAX_CONCURRENT_BONDS: int = 20
    BOND_SCANNER_MIN_VOLUME: int = 5000
    BOND_SCANNER_MAX_DAYS_TO_RESOLUTION: int = 14
    BOND_SCANNER_MIN_SIZE_USD: float = 1.0

    # Mid-Range NO — bet NO on outcomes priced $0.30-0.50 (paper-only)
    MID_RANGE_NO_MIN_PRICE: float = 0.30
    MID_RANGE_NO_MAX_PRICE: float = 0.50
    MID_RANGE_NO_MIN_VOLUME: int = 1000
    MID_RANGE_NO_MAX_DAYS_TO_RESOLUTION: int = 60
    MID_RANGE_NO_MIN_DAYS_TO_RESOLUTION: float = 0.0
    MID_RANGE_NO_MAX_POSITION_SIZE: float = 5.0
    MID_RANGE_NO_MAX_CONCURRENT: int = 10
    MID_RANGE_NO_KELLY_FRACTION: float = 0.25
    MID_RANGE_NO_MIN_SIZE_USD: float = 1.0
    MID_RANGE_NO_BANKROLL_PCT: float = 0.02
    MID_RANGE_NO_MIN_EDGE: float = 0.05

    # Ultra-Cheap NO — bet NO on ultra-cheap outcomes (<$0.10) (paper-only)
    ULTRA_CHEAP_NO_MIN_PRICE: float = 0.01
    ULTRA_CHEAP_NO_MAX_PRICE: float = 0.10
    ULTRA_CHEAP_NO_MIN_VOLUME: int = 500
    ULTRA_CHEAP_NO_MAX_DAYS_TO_RESOLUTION: int = 30
    ULTRA_CHEAP_NO_MIN_DAYS_TO_RESOLUTION: float = 0.0
    ULTRA_CHEAP_NO_MAX_POSITION_SIZE: float = 5.0
    ULTRA_CHEAP_NO_MAX_CONCURRENT: int = 10
    ULTRA_CHEAP_NO_KELLY_FRACTION: float = 0.25
    ULTRA_CHEAP_NO_MIN_SIZE_USD: float = 1.0
    ULTRA_CHEAP_NO_BANKROLL_PCT: float = 0.02
    ULTRA_CHEAP_NO_MIN_EDGE: float = 0.05

    # BTC Fade — fade crypto event outcomes (paper-only)
    BTC_FADE_MIN_PRICE: float = 0.01
    BTC_FADE_MAX_PRICE: float = 0.30
    BTC_FADE_MIN_VOLUME: int = 2000
    BTC_FADE_MAX_DAYS_TO_RESOLUTION: int = 14
    BTC_FADE_MIN_DAYS_TO_RESOLUTION: float = 0.0
    BTC_FADE_MAX_POSITION_SIZE: float = 5.0
    BTC_FADE_MAX_CONCURRENT: int = 8
    BTC_FADE_KELLY_FRACTION: float = 0.20
    BTC_FADE_MIN_SIZE_USD: float = 1.0
    BTC_FADE_BANKROLL_PCT: float = 0.02
    BTC_FADE_MIN_EDGE: float = 0.05

    # BTC Oracle
    BTC_ORACLE_MIN_POSITION_USD: float = 1.0
    BTC_ORACLE_MAX_POSITION_USD: float = 50.0
    BTC_ORACLE_EDGE_SCALE_THRESHOLD: float = 0.10
    BTC_ORACLE_MIN_EDGE: float = (
        0.08  # raised from 0.03 — WR 40.7% loss-making, need stronger conviction
    )
    BTC_ORACLE_INTERVAL_SECONDS: int = 30
    BTC_ORACLE_MAX_MINUTES_TO_RESOLUTION: int = 5

    # CEX PM Lead-Lag
    CEX_PM_LEADLAG_MIN_MOMENTUM: float = 0.001
    CEX_PM_LEADLAG_MIN_EDGE: float = (
        0.10  # 10% minimum raw divergence (was 5% — too low for 50/50 markets)
    )
    CEX_PM_LEADLAG_MAX_MINUTES_TO_RESOLUTION: int = 90
    CEX_PM_LEADLAG_MAX_POSITION_USD: float = 20.0
    CEX_PM_LEADLAG_INTERVAL_SECONDS: int = 15

    # Cross-Market Arbitrage
    CROSS_MARKET_ARB_RETRY_WAIT_BASE: float = 0.1
    CROSS_MARKET_ARB_DETECTION_INTERVAL_MS: int = 100
    CROSS_MARKET_ARB_MIN_PROFIT: float = 0.02
    CROSS_MARKET_ARB_MAX_SIZE: float = 100.0
    CROSS_MARKET_ARB_POLYMARKET_FEE: float = 0.01
    CROSS_MARKET_ARB_KALSHI_FEE: float = 0.01
    CROSS_MARKET_ARB_MIN_SPREAD: float = 0.03
    CROSS_ARB_MIN_SPREAD_PCT: float = 0.013  # 1.3% minimum spread to cover fees

    # General Market Scanner
    GENERAL_MARKET_SCANNER_MIN_EDGE: float = 0.03
    GENERAL_MARKET_SCANNER_MAX_PRICE: float = 0.80
    GENERAL_MARKET_SCANNER_MIN_PRICE: float = 0.10
    GENERAL_MARKET_SCANNER_MIN_REWARD_RISK: float = 0.3
    GENERAL_MARKET_SCANNER_MAX_LOW_PROB_SIZE: float = 0.25
    GENERAL_MARKET_SCANNER_LOW_PROB_THRESHOLD: float = 0.20
    GENERAL_MARKET_SCANNER_EDGE_DAMPENING: float = 0.6
    GENERAL_MARKET_SCANNER_SPORTS_EDGE_MULTIPLIER: float = 1.5
    GENERAL_MARKET_SCANNER_MAX_RAW_EDGE: float = 0.25
    GENERAL_MARKET_SCANNER_MARKET_ANCHOR_WEIGHT: float = 0.35
    GENERAL_MARKET_SCANNER_MIN_AI_CONFIDENCE: float = 0.60
    GENERAL_MARKET_SCANNER_HARVEST_YES_CEILING: float = 0.35
    GENERAL_MARKET_SCANNER_HARVEST_AI_OVERRIDE_THRESHOLD: float = 0.65
    GENERAL_MARKET_SCANNER_MARKET_AGREE_LOW: float = 0.50
    GENERAL_MARKET_SCANNER_MARKET_AGREE_HIGH: float = 0.65
    GENERAL_MARKET_SCANNER_MIN_EXPECTED_PROFIT: float = 0.08
    GENERAL_MARKET_SCANNER_LOW_PROB_YES_CAP: float = 0.25
    GENERAL_MARKET_SCANNER_MAX_MARKETS_PER_CYCLE: int = 10

    # Line Movement Detector
    LINE_MOVE_MIN_PRICE_CHANGE_PCT: float = 5.0
    LINE_MOVE_MIN_VOLUME_24H: float = 10000.0
    LINE_MOVE_MIN_LIQUIDITY: float = 5000.0
    LINE_MOVE_LOOKBACK_HOURS: float = 1.0
    LINE_MOVE_WEB_SEARCH_ENABLED: bool = True
    LINE_MOVE_MIN_CONFIDENCE_TO_SIGNAL: float = 0.5

    # BTC Momentum
    BTC_MOMENTUM_MAX_TRADE_FRACTION: float = 0.03

    # General Market Scanner - Category caps
    GM_SCANNER_CATEGORY_CAP_SPORTS: float = 0.75
    GM_SCANNER_CATEGORY_CAP_POLITICS: float = 1.50
    GM_SCANNER_CATEGORY_CAP_CRYPTO: float = 2.00

    # Order Executor - Leaderboard weights (Phase 3: favor win-rate traders)
    ORDER_EXECUTOR_WEIGHT_PROFIT_30D: float = 0.25
    ORDER_EXECUTOR_WEIGHT_WIN_RATE: float = 0.40
    ORDER_EXECUTOR_WEIGHT_MARKET_DIVERSITY: float = 0.15
    ORDER_EXECUTOR_WEIGHT_CONSISTENCY: float = 0.20

    # Probability Arbitrage - Retry backoff
    PROB_ARB_RETRY_BACKOFF_BASE: float = 0.1
    PROB_ARB_RETRY_BACKOFF_MULTIPLIER: float = 2.0

    # Market Maker
    MARKET_MAKER_DEFAULT_CONFIDENCE: float = 0.5
    MARKET_MAKER_BASE_SPREAD: float = 0.06
    MARKET_MAKER_MAX_INVENTORY: float = 250.0
    MARKET_MAKER_INVENTORY_SKEW_FACTOR: float = 0.7
    MARKET_MAKER_MIN_SPREAD: float = 0.03
    MARKET_MAKER_MAX_SPREAD: float = 0.18
    MARKET_MAKER_QUOTE_SIZE: float = 15.0
    MARKET_MAKER_LMSR_LIQUIDITY_PARAM: float = 10.0

    # Arb Executor (intra-market)
    ARB_EXECUTOR_MAX_SIZE: float = 100.0
    ARB_EXECUTOR_MIN_DEVIATION: float = 0.02

    # Universal Scanner - Retry backoff
    UNIVERSAL_SCANNER_RETRY_BACKOFF_BASE: float = 0.1
    UNIVERSAL_SCANNER_RETRY_BACKOFF_MULTIPLIER: float = 2.0

    # Wallet Sync - Exit threshold (Phase 3: exit earlier on partial sells)
    WALLET_SYNC_EXIT_THRESHOLD: float = 0.40

    # BTC Oracle - Algorithm constants
    BTC_ORACLE_ORACLE_IMPLIED_BASE: float = 0.50
    BTC_ORACLE_ORACLE_IMPLIED_SCALE: float = 0.10

    # Crypto Oracle (multi-asset generalization of BTC Oracle)
    CRYPTO_ORACLE_ASSETS: str = (
        "bitcoin,ethereum,solana"  # comma-separated CoinGecko IDs
    )
    CRYPTO_ORACLE_MIN_EDGE: float = 0.02
    CRYPTO_ORACLE_MAX_MINUTES_TO_RESOLUTION: float = 10.0
    CRYPTO_ORACLE_INTERVAL_SECONDS: int = 15
    CRYPTO_ORACLE_MAX_POSITION_USD: float = 50.0
    CRYPTO_ORACLE_MIN_POSITION_USD: float = 1.0
    CRYPTO_ORACLE_EDGE_SCALE_THRESHOLD: float = 0.05
    CRYPTO_ORACLE_ORACLE_IMPLIED_BASE: float = 0.50
    CRYPTO_ORACLE_ORACLE_IMPLIED_SCALE: float = 0.30
    CRYPTO_ORACLE_MIN_PRICE_BUCKET: float = (
        0.35  # reject trades below 35c (negative EV territory)
    )
    CRYPTO_ORACLE_MAX_PRICE_BUCKET: float = (
        0.65  # reject trades above 65c (negative EV territory)
    )
    CRYPTO_ORACLE_MAX_DAILY_LOSS: float = (
        50.0  # cumulative daily loss in USD — stop trading if exceeded
    )

    # Crypto Oracle — dynamic allocation & time-of-day optimization
    CRYPTO_ORACLE_TRACKER_ENABLED: bool = True
    CRYPTO_ORACLE_DYNAMIC_ALLOCATION: bool = True
    CRYPTO_ORACLE_TIME_WEIGHTS: dict = field(
        default_factory=lambda: {"peak": 1.0, "normal": 0.5, "off_peak": 0.25}
    )
    CRYPTO_ORACLE_PEAK_HOURS: list = field(
        default_factory=lambda: [17, 18]
    )  # UTC hours
    CRYPTO_ORACLE_NORMAL_HOURS: list = field(
        default_factory=lambda: [13, 14, 15, 16, 19, 20, 21]
    )

    # Time filters
    MIN_TIME_REMAINING: int = 60  # min time remaining in seconds
    MAX_TIME_REMAINING: int = 1800  # max time remaining in seconds
    MAX_TIME_EXECUTION_MS: int = 500  # max execution time in ms
