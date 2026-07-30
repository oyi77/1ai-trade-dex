"""Per-strategy parameters, scanner settings, and oracle tuning."""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StrategySpecificMixin:
    """Scanner, per-strategy, oracle, and executor-specific parameters."""

    # Scanner parameters
    SCANNER_PAGE_SIZE: int = 500
    SCANNER_SEMAPHORE_LIMIT: int = 50
    SCANNER_MIN_EDGE: float = 0.05
    SCANNER_STALE_THRESHOLD_SECONDS: float = 5.0
    SCANNER_MAX_MARKETS: int = 10000
    MARKET_UNIVERSE_CACHE_TTL_SECONDS: int = 300

    # Order executor thresholds
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

    # Bond Scanner
    BOND_SCANNER_MIN_PRICE: float = 0.05
    BOND_SCANNER_MAX_PRICE: float = 0.50
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

    # Mid-Range NO
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

    # Ultra-Cheap NO
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

    # BTC Fade
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

    # Order Executor - Leaderboard weights
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

    # Wallet Sync - Exit threshold
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
