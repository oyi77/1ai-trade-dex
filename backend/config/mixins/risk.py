"""Risk settings mixin — trading risk, HFT, weather, whale detection, auto-sell, arbitrage, and APEX."""

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class RiskMixin:
    """Trading risk configuration — circuit breakers, position sizing limits, HFT, arbitrage, and APEX."""

    # --------------------------------------------------------------------------
    # Risk config (canonical source)
    # --------------------------------------------------------------------------
    DEFAULT_KELLY_FRACTION: float = 0.25
    MAX_KELLY_FRACTION: float = 0.15
    DEFAULT_MAX_DAILY_LOSS_USD: float = 100.0
    DEFAULT_MAX_DRAWDOWN_PCT: float = 0.20
    TERMINAL_DRAWDOWN_PCT: float = 0.50
    DAILY_DRAWDOWN_LIMIT_PCT: float = 0.10  # max daily drawdown
    WEEKLY_DRAWDOWN_LIMIT_PCT: float = 0.20  # max weekly drawdown
    DAILY_LOSS_FLOOR_PCT: float = -0.10  # daily loss floor (auto-pause)
    WEEKLY_LOSS_FLOOR_PCT: float = -0.20  # weekly loss floor (revert to paper)
    MAX_STRATEGY_DRAWDOWN_PCT: float = (
        0.30  # per-strategy max drawdown: block if strategy loses 30% of bankroll
    )
    # LIVE_STRATEGY_ALLOWLIST: only strategies in this list can execute live.
    # Promoters, schedulers, and risk checks will respect this.
    # Empty list = ALL strategies allowed (permissive mode).
    LIVE_STRATEGY_ALLOWLIST: list = field(default_factory=lambda: ["bond_scanner", "longshot_bias"])
    VOLATILITY_SIZE_SCALE: bool = False  # reduce size in high volatility
    COOLDOWN_CONSECUTIVE_LOSSES: int = 3  # losses before cooldown
    COOLDOWN_MINUTES: int = 60  # strategy cooldown after consecutive losses
    DUPLICATE_TRADE_COOLDOWN_SEC: int = 15  # cooldown between trades on the same market
    MAX_CONCENTRATION_PCT: float = 1.0  # max exposure to single event (% of bankroll)
    DISK_USAGE_ALERT_PCT: float = 0.90  # disk usage alert threshold

    # HFT parameters
    HFT_ENABLED: bool = True
    HFT_POSITION_SIZE_PCT: float = 1.0  # position size as % of bankroll
    HFT_MAX_POSITION_USD: float = 5000.0  # max position in USD
    SAFE_TUNER_MAX_CHANGE_PCT: float = 1.0  # max parameter drift per tuning
    SAFE_TUNER_MIN_TRADES_FOR_TUNING: int = 20
    SAFE_TUNER_REVERT_SIGMA_THRESHOLD: float = 2.0
    PAPER_SLIPPAGE_BPS: float = 20.0  # paper slippage in basis points
    PAPER_MIN_SLIPPAGE_BPS: float = 5.0  # minimum slippage (0.05%)
    HFT_MAX_SLIPPAGE_BPS: float = 20.0
    SLIPPAGE_TOLERANCE: float = 0.02  # max acceptable price slippage (2%)
    PAPER_RANDOM_SLIPPAGE: bool = True  # add random jitter to slippage
    PAPER_SIZE_IMPACT_FACTOR: float = 0.5  # logarithmic size impact on slippage
    PAPER_CLOB_FEE_RATE: float = 0.02  # Polymarket fee rate (2%)
    PAPER_MIN_DEPTH_USD: float = 100.0  # reject if orderbook depth below this
    PAPER_MAX_DEPTH_CONSUMPTION_PCT: float = 0.20
    PAPER_LONGSHOT_SLIPPAGE_MULTIPLIER: float = 2.0
    PAPER_LONGSHOT_PRICE_THRESHOLD: float = 0.10

    # Weather parameters
    WEATHER_ENABLED: bool = True
    WEATHER_SCAN_INTERVAL_SECONDS: int = 60
    WEATHER_SETTLEMENT_INTERVAL_SECONDS: int = 1800
    WEATHER_MIN_EDGE_THRESHOLD: float = 0.05
    WEATHER_MAX_ENTRY_PRICE: float = 0.70
    WEATHER_MAX_TRADE_SIZE: float = 10.0
    WEATHER_CITIES: str = (
        "nyc,chicago,miami,dallas,seattle,atlanta,los_angeles,denver,london,seoul,tokyo"
    )
    WEATHER_KELLY_FRACTION: float = 0.15
    WEATHER_MAX_BANKROLL_FRACTION: float = 0.05

    # Whale detection
    WHALE_FRONTRUN_MIN_SIZE: float = 10000.0
    WHALE_FRONTRUN_MIN_SCORE: float = 0.8
    WHALE_FRONTRUN_MAX_RECONNECT: int = 5
    WHALE_FRONTRUN_DELAY_MS: int = 50
    WHALE_FRONTRUN_SELL_DELAY_MS: int = 1000

    # --------------------------------------------------------------------------
    # RISK - Trading risk configuration
    # --------------------------------------------------------------------------
    # Circuit breakers
    CIRCUIT_BREAKER_ENABLED: bool = True
    MAX_CONCURRENT_POSITIONS: int = 3
    CONSECUTIVE_LOSS_LIMIT: int = 5

    # Daily loss monitoring
    DAILY_LOSS_LIMIT_ENABLED: bool = True
    DAILY_LOSS_LIMIT: float = 100.0  # max daily loss in USD
    DRAWDOWN_BREAKER_ENABLED_PER_MODE: Dict[str, bool] = field(
        default_factory=lambda: {"paper": False, "testnet": True, "live": True}
    )
    DAILY_LOSS_LIMIT_ENABLED_PER_MODE: Dict[str, bool] = field(
        default_factory=lambda: {"paper": False, "testnet": True, "live": True}
    )

    # Risk limits per mode
    RISK_MAX_DAILY_LOSS_PCT: float = 0.10
    RISK_MAX_WEEKLY_LOSS_PCT: float = 0.20

    # HFT risk parameters (from config_hft.py)
    HFT_SCANNER_PARALLEL_LIMIT: int = 50
    HFT_SCANNER_MAX_MARKETS: int = 10000
    HFT_SCANNER_STALE_THRESHOLD_SEC: float = 5.0
    HFT_SCANNER_PAGE_SIZE: int = 500
    HFT_SCANNER_MIN_EDGE: float = 0.05
    HFT_SCANNER_MIN_VOLUME: float = 1000.0
    HFT_SCANNER_MAX_RETRIES: int = 3
    HFT_SCANNER_CIRCUIT_BREAKER_THRESHOLD: int = 5
    HFT_SCANNER_CIRCUIT_BREAKER_TIMEOUT: float = 60.0

    HFT_EXECUTION_AUTO_EXECUTE: bool = True
    HFT_EXECUTION_AUTO_EXECUTE_MIN_CONFIDENCE: float = 0.7
    HFT_EXECUTION_POSITION_SIZE_PCT: float = 0.25
    HFT_EXECUTION_MAX_POSITION_USD: float = 1000.0
    HFT_EXECUTION_MAX_TOTAL_EXPOSURE: float = 5000.0
    HFT_EXECUTION_IDEMPOTENCY_TTL_SEC: int = 30

    HFT_WHALE_MIN_SIZE_USD: float = 10000.0
    HFT_WHALE_MIN_SCORE: float = 0.8
    HFT_WHALE_FRONTRUN_DELAY_MS: int = 50
    HFT_WHALE_SELL_DELAY_MS: int = 1000
    HFT_WHALE_MAX_RECONNECT_RETRIES: int = 5
    HFT_WHALE_WS_RECONNECT_DELAY_BASE: float = 0.1

    HFT_ARB_MIN_PROFIT: float = 0.01
    HFT_ARB_POLYMARKET_FEE: float = 0.01
    HFT_ARB_KALSHI_FEE: float = 0.01
    HFT_ARB_EXECUTION_MAX_RETRIES: int = 3
    HFT_ARB_PENDING_QUEUE_TTL_SEC: int = 300

    HFT_LATENCY_MAX_SCAN_LATENCY_MS: float = 1000.0
    HFT_LATENCY_MAX_EXECUTION_LATENCY_MS: float = 50.0
    HFT_LATENCY_LATENCY_ALERT_THRESHOLD_MS: float = 100.0
    HFT_LATENCY_CACHE_TTL_SEC: float = 1.0

    # --------------------------------------------------------------------------
    # AUTO-SELL — Pre-settlement profit-taking
    # --------------------------------------------------------------------------
    AUTO_SELL_PROFIT_TARGET_PCT: float = (
        0.06  # 6% profit target (net ~4% after 2% round-trip PM fee)
    )
    AUTO_SELL_STOP_LOSS_PCT: float = 0.04  # 4% stop-loss
    AUTO_SELL_MAX_HOLD_SECONDS: int = 600  # 10 min max hold
    AUTO_SELL_INTERVAL_SECONDS: int = 30  # Check every 30s

    # --------------------------------------------------------------------------
    # ARBITRAGE - Arbitrage detection parameters
    # --------------------------------------------------------------------------
    ARBITRAGE_DETECTOR_ENABLED: bool = False
    ARB_EXECUTOR_ENABLED: bool = True
    ARB_MIN_PROFIT: float = 0.02
    ARB_MAX_RETRIES: int = 3
    ARB_CIRCUIT_BREAKER_THRESHOLD: int = 5
    ARB_CIRCUIT_BREAKER_TIMEOUT: float = 60.0
    ARB_POLYMARKET_FEE: float = 0.01
    ARB_KALSHI_FEE: float = 0.01
    ARB_DEFAULT_FEE_RATE: float = 0.02
    ARB_DEFAULT_MIN_SPREAD: float = 0.03
    SPREAD_MODE: str = "static"
    TAKER_FEE_RATE: float = 0.01
    MIN_ARB_SPREAD: float = 0.005
    SSE_EVENT_TYPE_FILTER_ENABLED: bool = True

    # --------------------------------------------------------------------------
    # APEX - Advanced Polymarket Edge eXecution
    # --------------------------------------------------------------------------
    APEX_ENABLED: bool = True
    APEX_MIN_EDGE_PP: float = 6.0
    APEX_MIN_CONFIDENCE: float = 0.5
    APEX_SCAN_INTERVAL: int = 120
    APEX_MAX_POSITIONS: int = 5
    APEX_POSITION_SIZE_PCT: float = 0.08
    APEX_PROFIT_TARGET_PCT: float = 0.025
    APEX_STOP_LOSS_PCT: float = 0.04
    APEX_MAX_HOLD_HOURS: float = 72.0
    APEX_CALIBRATION_MIN_SAMPLES: int = 20
    APEX_CALIBRATION_MAX_ADJUSTMENT: float = 5.0
    APEX_VOLATILITY_SOURCE: str = "market"
    APEX_NEAR_RESOLUTION_MIN_HOURS: float = 1.0
    APEX_NEAR_RESOLUTION_MAX_HOURS: float = 72.0
    APEX_NEAR_RESOLUTION_MIN_PRICE: float = 0.85
    APEX_STALE_ODDS_THRESHOLD_MINUTES: int = 30
    APEX_LIQUIDITY_GAP_MIN_SPREAD: float = 0.03
    APEX_LIQUIDITY_GAP_MIN_VOLUME: float = 5000.0
