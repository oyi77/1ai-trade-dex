"""Configuration settings for the BTC 5-min trading bot."""

import os
from pydantic import model_validator, field_validator, ConfigDict
from pydantic_settings import BaseSettings
from typing import Dict, Optional
from dataclasses import dataclass, field

from loguru import logger

try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

# Project root directory
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT_DIR, "tradingbot.db")


# ============================================================================
# ConfigRegistry - Single source of truth for all configuration
# ============================================================================
# This dataclass organizes all config keys into logical categories:
# - api_endpoints: External API URLs
# - rate_limits: Rate limit and backoff settings
# - strategy_params: Strategy-specific thresholds and limits
# - system: Deployment and runtime settings
# - risk: Trading risk configuration
# - polling:Interval settings for jobs and tasks
# ============================================================================

@dataclass
class ConfigRegistry:
    """
    Centralized configuration registry with categorized access.

    This is the single source of truth for all configuration in PolyEdge.
    All settings are organized by domain (API_ENDPOINTS, RATE_LIMITS, etc.)
    and validated at startup to fail fast with clear error messages.

    Settings are read from environment variables (via .env file), falling
    back to the hardcoded class defaults when not set.
    """

    def __init__(self):
        import dataclasses
        from dataclasses import Field, MISSING

        all_fields = {}
        # Collect dataclass fields first (they carry type + default metadata)
        for f in dataclasses.fields(self):
            if f.default is not MISSING:
                all_fields[f.name] = f.default
            elif f.default_factory is not MISSING:
                all_fields[f.name] = f.default_factory()
            else:
                all_fields[f.name] = f.type() if f.type in (dict, list, set, str, int, float, bool) else None

        # Then collect plain class annotations (non-dataclass-field defaults)
        for name, value in self.__class__.__dict__.items():
            if name.startswith('_') or callable(value) or isinstance(value, (staticmethod, classmethod, property, Field)):
                continue
            if name not in all_fields:
                all_fields[name] = value

        for name, default in all_fields.items():
            env_val = os.environ.get(name)
            if env_val is not None:
                if isinstance(default, bool):
                    setattr(self, name, env_val.lower() in ('true', '1', 'yes'))
                elif isinstance(default, int):
                    setattr(self, name, int(env_val))
                elif isinstance(default, float):
                    setattr(self, name, float(env_val))
                elif isinstance(default, (dict, list)):
                    try:
                        setattr(self, name, eval(env_val))
                    except Exception:
                        setattr(self, name, default)
                else:
                    setattr(self, name, env_val)
            else:
                setattr(self, name, default)

    # --------------------------------------------------------------------------
    # API_ENDPOINTS - External API URLs
    # --------------------------------------------------------------------------
    # Polymarket APIs
    GAMMA_API_URL: str = "https://gamma-api.polymarket.com"
    DATA_API_URL: str = "https://data-api.polymarket.com"
    DATA_API_VERSION: str = "v1"
    CLOB_API_URL: str = "https://clob.polymarket.com"
    POLYMARKET_BASE_URL: str = "https://polymarket.com"
    POLYMARKET_RELAYER_URL: str = "https://relayer-v2.polymarket.com"

    # Polymarket WebSocket URLs
    POLYMARKET_WS_CLOB_URL: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    POLYMARKET_WS_USER_URL: str = "wss://ws-subscriptions-clob.polymarket.com/ws/user"
    POLYMARKET_WS_RTDS_URL: str = "wss://ws-live-data.polymarket.com"
    POLYMARKET_WS_WHALE_URL: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    POLYMARKET_WS_ORDERBOOK_URL: str = "wss://ws.polymarket.com/orderbook"

    # Kalshi API
    KALSHI_API_URL: str = "https://api.elections.kalshi.com/trade-api/v2"

    # Crypto exchange APIs
    BINANCE_API_URL: str = "https://api.binance.com/api/v3"
    BINANCE_KLINES_URL: str = "https://api.binance.com/api/v3/klines"
    BYBIT_KLINES_URL: str = "https://api.bybit.com/v5/market/kline"
    COINBASE_API_URL: str = "https://api.exchange.coinbase.com"
    KRAKEN_API_URL: str = "https://api.kraken.com/0/public"
    BYBIT_API_URL: str = "https://api.bybit.com/v5/market"
    COINGECKO_API_URL: str = "https://api.coingecko.com/api/v3"

    # Weather APIs
    OPEN_METEO_API_URL: str = "https://api.open-meteo.com/v1"
    OPEN_METEO_ARCHIVE_URL: str = "https://archive-api.open-meteo.com/v1/archive"
    OPEN_METEO_ENSEMBLE_URL: str = "https://ensemble-api.open-meteo.com/v1/ensemble"
    OPEN_METEO_GEOCODING_URL: str = "https://geocoding-api.open-meteo.com/v1/search"
    NWS_API_URL: str = "https://api.weather.gov/gridpoints"
    NWS_BASE_URL: str = "https://api.weather.gov"

    # Search APIs
    TAVILY_API_URL: str = "https://api.tavily.com/search"
    EXA_API_URL: str = "https://api.exa.ai/search"
    SERPER_API_URL: str = "https://google.serper.dev/search"
    DDG_HTML_URL: str = "https://html.duckduckgo.com/html/"
    CRW_API_URL: Optional[str] = None

    # Telegram API
    TELEGRAM_API_BASE: str = "https://api.telegram.org"

    # MiroFish API
    MIROFISH_API_URL: str = "https://polyedge-mirofish-api.aitradepulse.com"

    # Brain/BK-Hub API
    BK_BRAIN_URL: str = "http://localhost:9099"
    BRAIN_API_URL: str = "http://localhost:9099"

    # Goldsky GraphQL API (Polymarket historical order data)
    GOLDSKY_API_URL: str = "https://api.goldsky.com/api/public/project_cl6mb8i9h0003e201j6li0diw/subgraphs/orderbook-subgraph/0.0.1/gn"

    # API_BASE_URL - FastAPI server URL (constructed from API_HOST and API_PORT)
    API_HOST: str = "localhost"
    API_PORT: int = 8005
    API_BASE_URL: str = "http://localhost:8005"

    # RSS Feed URLs (comma-separated)
    RSS_FEED_URLS: str = "https://feeds.bbci.co.uk/news/rss.xml,https://feeds.reuters.com/reuters/businessNews,https://www.federalreserve.gov/feeds/press_all.xml,https://cointelegraph.com/rss,https://coindesk.com/arc/outboundfeeds/rss/"

    # --------------------------------------------------------------------------
    # RATE_LIMITS - Rate limit settings for API services
    # --------------------------------------------------------------------------
    RATE_LIMIT_GAMMA: int = 100  #requests per minute
    RATE_LIMIT_KALSHI: int = 30
    RATE_LIMIT_CRYPTO: int = 60
    RATE_LIMIT_BACKOFF_BASE: float = 2.0  #base multiplier for exponential backoff
    RATE_LIMIT_MAX_DELAY: float = 60.0  #maximum delay between retries
    # Circuit breaker thresholds (configurable per service)
    CB_FAILURE_THRESHOLD: int = 5  #failures before opening circuit
    CB_RECOVERY_TIMEOUT: float = 60.0  #seconds before attempting recovery
    CB_HALF_OPEN_MAX: int = 1  #max concurrent probes in half-open state

    # --------------------------------------------------------------------------
    # STRATEGY_PARAMS - Strategy-specific thresholds and limits
    # --------------------------------------------------------------------------
    # Trading parameters
    MIN_DEBATE_EDGE: float = 0.04  #debate threshold
    MIN_EDGE_THRESHOLD: float = 0.03  #minimum edge for signals
    MAX_ENTRY_PRICE: float = 0.80  #maximum entry price
    MAX_TRADES_PER_WINDOW: int = 20  #trades per scheduling window
    MAX_TRADES_PER_SCAN: int = 10  #trades per scan cycle
    AUTO_TRADER_BATCH_SIZE: int = 100  #batch size for auto-trader
    MAX_TOTAL_PENDING_TRADES: int = 50  #max pending trades
    STALE_TRADE_HOURS: int = 48  #hours before trade considered stale

    # Position sizing
    KELLY_FRACTION: float = 0.30  #Kelly fraction (0.30 = 30% Kelly)
    MAX_POSITION_FRACTION: float = 0.08  #max position as % of bankroll
    MAX_TOTAL_EXPOSURE_FRACTION: float = 0.70  #max total exposure
    MAX_TRADE_SIZE: float = 8.0  #max single trade size in USD
    MIN_ORDER_USDC: float = 5.0  #minimum order size (live)
    PAPER_MIN_ORDER_USDC: float = 1.0  #minimum order size (paper)

    # Confidence and signal weights
    AUTO_APPROVE_MIN_CONFIDENCE: float = float(os.getenv("AUTO_APPROVE_MIN_CONFIDENCE", "0.5"))
    PAPER_AUTO_APPROVE_MIN_CONFIDENCE: float = float(os.getenv("PAPER_AUTO_APPROVE_MIN_CONFIDENCE", "0.25"))
    AI_SIGNAL_WEIGHT: float = 0.30  #AI weight in ensemble (max 0.50)
    LONGSHOT_NO_BIAS_WEIGHT: float = 0.10  #bias weight for longshot markets

    # Indicator weights (must sum to ~1.0)
    WEIGHT_RSI: float = 0.20
    WEIGHT_MOMENTUM: float = 0.35
    WEIGHT_VWAP: float = 0.20
    WEIGHT_SMA: float = 0.15
    WEIGHT_MARKET_SKEW: float = 0.10

    # Volume filters
    MIN_MARKET_VOLUME: float = 100.0  #minimum market volume
    MIN_WHALE_TRADE_USD: float = 1000.0  #minimum whale trade size

    # Risk management
    DAILY_LOSS_LIMIT: float = 5.0  #maximum daily loss
    DAILY_LOSS_LIMIT_PCT: float = 0.10  #daily loss % (overrides flat limit)
    SLIPPAGE_TOLERANCE: float = 0.02  #max slippage (2%)
    DAILY_DRAWDOWN_LIMIT_PCT: float = 0.10  #max daily drawdown
    WEEKLY_DRAWDOWN_LIMIT_PCT: float = 0.20  #max weekly drawdown
    DAILY_LOSS_FLOOR_PCT: float = -0.10  #daily loss floor (auto-pause)
    WEEKLY_LOSS_FLOOR_PCT: float = -0.20  #weekly loss floor (revert to paper)

    # HFT parameters
    HFT_ENABLED: bool = True
    HFT_POSITION_SIZE_PCT: float = 0.25  #position size as % of bankroll
    HFT_MAX_POSITION_USD: float = 1000.0  #max position in USD
    SAFE_TUNER_MAX_CHANGE_PCT: float = 0.10  #max parameter drift per tuning
    SAFE_TUNER_MIN_TRADES_FOR_TUNING: int = 20
    SAFE_TUNER_REVERT_SIGMA_THRESHOLD: float = 2.0
    PAPER_SLIPPAGE_BPS: float = 0.0  #paper slippage in basis points
    PAPER_MIN_SLIPPAGE_BPS: float = 5.0  #minimum slippage (0.05%)
    HFT_MAX_SLIPPAGE_BPS: float = 20.0
    PAPER_RANDOM_SLIPPAGE: bool = False  #add random jitter to slippage

    # Weather parameters
    WEATHER_ENABLED: bool = True
    WEATHER_SCAN_INTERVAL_SECONDS: int = 60
    WEATHER_SETTLEMENT_INTERVAL_SECONDS: int = 1800
    WEATHER_MIN_EDGE_THRESHOLD: float = 0.05
    WEATHER_MAX_ENTRY_PRICE: float = 0.70
    WEATHER_MAX_TRADE_SIZE: float = 10.0
    WEATHER_CITIES: str = "nyc,chicago,miami,dallas,seattle,atlanta,los_angeles,denver,london,seoul,tokyo"
    WEATHER_KELLY_FRACTION: float = 0.15
    WEATHER_MAX_BANKROLL_FRACTION: float = 0.05

    # Whale detection
    WHALE_FRONTRUN_MIN_SIZE: float = 10000.0
    WHALE_FRONTRUN_MIN_SCORE: float = 0.8
    WHALE_FRONTRUN_MAX_RECONNECT: int = 5
    WHALE_FRONTRUN_DELAY_MS: int = 50
    WHALE_FRONTRUN_SELL_DELAY_MS: int = 1000

    # Scanner parameters
    SCANNER_PAGE_SIZE: int = 500
    SCANNER_SEMAPHORE_LIMIT: int = 50
    SCANNER_MIN_EDGE: float = 0.02
    SCANNER_STALE_THRESHOLD_SECONDS: float = 5.0
    SCANNER_MAX_MARKETS: int = 10000
    MARKET_UNIVERSE_CACHE_TTL_SECONDS: int = 300

    # Order executor
    ORDER_EXECUTOR_MIN_WHALE_SIZE: float = 50.0
    ORDER_EXECUTOR_MIN_DAYS_TO_RESOLUTION: int = 7

    #Line movement detector
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
    BOND_SCANNER_MIN_PRICE: float = 0.88
    BOND_SCANNER_MAX_PRICE: float = 0.97
    BOND_SCANNER_MIN_DAYS_TO_RESOLUTION: float = 0.5
    BOND_SCANNER_KELLY_FRACTION: float = 0.25
    BOND_SCANNER_BANKROLL_PCT: float = 0.08
    BOND_SCANNER_MIN_EDGE: float = 0.005
    BOND_SCANNER_PROXIMITY_BOOST_SCALE: float = 0.01
    BOND_SCANNER_MAX_POSITION_SIZE: float = 8.0
    BOND_SCANNER_MAX_CONCURRENT_BONDS: int = 8
    BOND_SCANNER_MIN_VOLUME: int = 1000
    BOND_SCANNER_MAX_DAYS_TO_RESOLUTION: int = 14
    BOND_SCANNER_MIN_SIZE_USD: float = 5.0

    # BTC Oracle
    BTC_ORACLE_MIN_POSITION_USD: float = 1.0
    BTC_ORACLE_MAX_POSITION_USD: float = 50.0
    BTC_ORACLE_EDGE_SCALE_THRESHOLD: float = 0.10
    BTC_ORACLE_MIN_EDGE: float = 0.03
    BTC_ORACLE_INTERVAL_SECONDS: int = 30
    BTC_ORACLE_MAX_MINUTES_TO_RESOLUTION: int = 5

    # CEX PM Lead-Lag
    CEX_PM_LEADLAG_MIN_MOMENTUM: float = 0.003
    CEX_PM_LEADLAG_MIN_EDGE: float = 0.05
    CEX_PM_LEADLAG_MAX_MINUTES_TO_RESOLUTION: int = 90
    CEX_PM_LEADLAG_MAX_POSITION_USD: float = 50.0
    CEX_PM_LEADLAG_INTERVAL_SECONDS: int = 15

    # Cross-Market Arbitrage
    CROSS_MARKET_ARB_RETRY_WAIT_BASE: float = 0.1
    CROSS_MARKET_ARB_DETECTION_INTERVAL_MS: int = 100
    CROSS_MARKET_ARB_MIN_PROFIT: float = 0.02
    CROSS_MARKET_ARB_MAX_SIZE: float = 100.0
    CROSS_MARKET_ARB_POLYMARKET_FEE: float = 0.01
    CROSS_MARKET_ARB_KALSHI_FEE: float = 0.01
    CROSS_MARKET_ARB_MIN_SPREAD: float = 0.03

    # General Market Scanner
    GENERAL_MARKET_SCANNER_MIN_EDGE: float = 0.02
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
    LINE_MOVE_MIN_CONFIDENCE_TO_SIGNAL: float = 0.6

    # BTC Momentum
    BTC_MOMENTUM_MAX_TRADE_FRACTION: float = 0.03

    # General Market Scanner - Category caps
    GM_SCANNER_CATEGORY_CAP_SPORTS: float = 0.75
    GM_SCANNER_CATEGORY_CAP_POLITICS: float = 1.50
    GM_SCANNER_CATEGORY_CAP_CRYPTO: float = 2.00

    # Order Executor - Leaderboard weights
    ORDER_EXECUTOR_WEIGHT_PROFIT_30D: float = 0.35
    ORDER_EXECUTOR_WEIGHT_WIN_RATE: float = 0.25
    ORDER_EXECUTOR_WEIGHT_MARKET_DIVERSITY: float = 0.20
    ORDER_EXECUTOR_WEIGHT_CONSISTENCY: float = 0.20

    # Probability Arbitrage - Retry backoff
    PROB_ARB_RETRY_BACKOFF_BASE: float = 0.1
    PROB_ARB_RETRY_BACKOFF_MULTIPLIER: float = 2.0

    # Market Maker
    MARKET_MAKER_DEFAULT_CONFIDENCE: float = 0.5

    # Market Maker
    MARKET_MAKER_BASE_SPREAD: float = 0.04
    MARKET_MAKER_MAX_INVENTORY: float = 500.0
    MARKET_MAKER_INVENTORY_SKEW_FACTOR: float = 0.5
    MARKET_MAKER_MIN_SPREAD: float = 0.02
    MARKET_MAKER_MAX_SPREAD: float = 0.15
    MARKET_MAKER_QUOTE_SIZE: float = 25.0
    MARKET_MAKER_LMSR_LIQUIDITY_PARAM: float = 10.0

    # Arb Executor (intra-market)
    ARB_EXECUTOR_MAX_SIZE: float = 100.0
    ARB_EXECUTOR_MIN_DEVIATION: float = 0.02

    # Universal Scanner - Retry backoff
    UNIVERSAL_SCANNER_RETRY_BACKOFF_BASE: float = 0.1
    UNIVERSAL_SCANNER_RETRY_BACKOFF_MULTIPLIER: float = 2.0

    # Wallet Sync - Exit threshold
    WALLET_SYNC_EXIT_THRESHOLD: float = 0.50

    # BTC Oracle - Algorithm constants
    BTC_ORACLE_ORACLE_IMPLIED_BASE: float = 0.50
    BTC_ORACLE_ORACLE_IMPLIED_SCALE: float = 0.10

    # Time filters
    MIN_TIME_REMAINING: int = 60  #min time remaining in seconds
    MAX_TIME_REMAINING: int = 1800  #max time remaining in seconds
    MAX_TIME_EXECUTION_MS: int = 500  #max execution time in ms

    # --------------------------------------------------------------------------
    # SYSTEM - Deployment and runtime settings
    # --------------------------------------------------------------------------
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./tradingbot.db")
    POSTGRES_POOL_SIZE: int = 10
    POSTGRES_MAX_OVERFLOW: int = 20
    POSTGRES_POOL_TIMEOUT: int = 30
    POSTGRES_POOL_RECYCLE: int = 3600
    POSTGRES_SSL_MODE: str = "prefer"

    @property
    def is_postgres(self) -> bool:
        return "postgresql" in self.DATABASE_URL

    @property
    def is_sqlite(self) -> bool:
        return "sqlite" in self.DATABASE_URL

    def validate_database_url(self) -> list[str]:
        issues = []

        if not self.DATABASE_URL:
            issues.append("DATABASE_URL is required")
            return issues

        if self.DATABASE_URL.startswith("mysql://") and "+pymysql" not in self.DATABASE_URL:
            logger.warning(
                "MySQL DATABASE_URL detected without '+pymysql'. "
                "Consider using 'mysql+pymysql://...' for better compatibility."
            )

        valid_schemes = ("sqlite://", "postgresql://", "mysql+pymysql://", "mysql://")
        if not any(self.DATABASE_URL.startswith(s) for s in valid_schemes):
            issues.append(f"Invalid DATABASE_URL scheme, got: {self.DATABASE_URL}")

        return issues

    # API keys and auth
    POLYMARKET_PRIVATE_KEY: Optional[str] = None
    POLYMARKET_API_KEY: Optional[str] = None
    POLYMARKET_API_SECRET: Optional[str] = None
    POLYMARKET_API_PASSPHRASE: Optional[str] = None
    POLYMARKET_SIGNATURE_TYPE: int = 0
    POLYMARKET_BUILDER_API_KEY: Optional[str] = None
    POLYMARKET_BUILDER_SECRET: Optional[str] = None
    POLYMARKET_BUILDER_PASSPHRASE: Optional[str] = None
    POLYMARKET_BUILDER_ADDRESS: Optional[str] = None
    POLYMARKET_WALLET_ADDRESS: Optional[str] = None
    POLYMARKET_RELAYER_API_KEY: Optional[str] = None
    POLYMARKET_RELAYER_API_KEY_ADDRESS: Optional[str] = None
    KALSHI_API_KEY_ID: Optional[str] = None
    KALSHI_PRIVATE_KEY_PATH: Optional[str] = None
    KALSHI_ENABLED: bool = False
    ADMIN_API_KEY: Optional[str] = None

    # Port and hosting
    PORT: int = 8100  #backend API port
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:5174,http://127.0.0.1:5173,http://127.0.0.1:5174,https://polyedge.aitradepulse.com,http://polyedge.aitradepulse.com"

    # Trading modes
    ACTIVE_MODES: str = "paper"
    TRADING_MODE: str = "paper"
    SHADOW_MODE: bool = True

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = False
    LOG_FILE: Optional[str] = None
    LOG_ROTATION: str = "500 MB"
    LOG_RETENTION: str = "10 days"
    API_LOG_ALL_CALLS: bool = True

    # WebSocket
    POLYMARKET_WS_ENABLED: bool = True
    POLYMARKET_USER_WS_ENABLED: bool = False
    POLYMARKET_WS_SUBSCRIPTION_LIMIT: int = 200
    API_REQUEST_TIMEOUT: float = 30.0
    DATABASE_QUERY_TIMEOUT: float = 10.0
    EXTERNAL_API_TIMEOUT: float = 15.0
    WS_HANDLER_TIMEOUT_MS: int = 100

    # Telegram
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_ADMIN_CHAT_IDS: str = ""
    TELEGRAM_HIGH_CONFIDENCE_ALERTS: bool = True

    # --------------------------------------------------------------------------
    # RISK - Trading risk configuration
    # --------------------------------------------------------------------------
    # Circuit breakers
    CIRCUIT_BREAKER_ENABLED: bool = True
    MAX_CONCURRENT_POSITIONS: int = 3
    CONSECUTIVE_LOSS_LIMIT: int = 3

    # Daily loss monitoring
    DAILY_LOSS_LIMIT_ENABLED: bool = True
    DRAWDOWN_BREAKER_ENABLED_PER_MODE: Dict[str, bool] = field(default_factory=lambda: {"paper": False, "testnet": True, "live": True})
    DAILY_LOSS_LIMIT_ENABLED_PER_MODE: Dict[str, bool] = field(default_factory=lambda: {"paper": False, "testnet": True, "live": True})

    # Risk limits per mode
    RISK_MAX_DAILY_LOSS_PCT: float = 0.10
    RISK_MAX_WEEKLY_LOSS_PCT: float = 0.20

    # HFT risk parameters (from config_hft.py)
    HFT_SCANNER_PARALLEL_LIMIT: int = 50
    HFT_SCANNER_MAX_MARKETS: int = 10000
    HFT_SCANNER_STALE_THRESHOLD_SEC: float = 5.0
    HFT_SCANNER_PAGE_SIZE: int = 500
    HFT_SCANNER_MIN_EDGE: float = 0.02
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

    HFT_ARB_MIN_PROFIT: float = 0.02
    HFT_ARB_POLYMARKET_FEE: float = 0.01
    HFT_ARB_KALSHI_FEE: float = 0.01
    HFT_ARB_EXECUTION_MAX_RETRIES: int = 3
    HFT_ARB_PENDING_QUEUE_TTL_SEC: int = 300

    HFT_LATENCY_MAX_SCAN_LATENCY_MS: float = 1000.0
    HFT_LATENCY_MAX_EXECUTION_LATENCY_MS: float = 50.0
    HFT_LATENCY_LATENCY_ALERT_THRESHOLD_MS: float = 100.0
    HFT_LATENCY_CACHE_TTL_SEC: float = 1.0

    # --------------------------------------------------------------------------
    # POLLING - Interval settings for jobs and tasks
    # --------------------------------------------------------------------------
    # Scan intervals
    SCAN_INTERVAL_SECONDS: int = 120
    SETTLEMENT_INTERVAL_SECONDS: int = 120
    WEATHER_SCAN_INTERVAL_SECONDS: int = 60
    WEATHER_SETTLEMENT_INTERVAL_SECONDS: int = 1800

    # Job intervals
    JOB_WORKER_ENABLED: bool = True
    JOB_QUEUE_URL: str = "sqlite:///./job_queue.db"
    JOB_TIMEOUT_SECONDS: int = 300
    MAX_CONCURRENT_JOBS: int = 1
    DB_EXECUTOR_MAX_WORKERS: int = 4

    # AGI intervals
    AGI_PROMOTION_INTERVAL_HOURS: int = 6
    AGI_HEALTH_CHECK_INTERVAL_MINUTES: int = 15
    AGI_BANKROLL_ALLOCATION_INTERVAL_DAYS: int = 1
    AGI_CALIBRATION_CHECK_INTERVAL_HOURS: int = 6
    AUTO_IMPROVE_INTERVAL_DAYS: int = 7
    SELF_REVIEW_INTERVAL_DAYS: int = 1
    RESEARCH_PIPELINE_INTERVAL_HOURS: int = 4
    AGI_IMPROVEMENT_CYCLE_INTERVAL_HOURS: int = 4
    HISTORICAL_DATA_COLLECTOR_INTERVAL_HOURS: int = 6
    ARBITRAGE_SCAN_INTERVAL_SECONDS: int = 30
    NEWS_FEED_INTERVAL_SECONDS: int = 600

    # Evolution engine intervals
    AGI_MUTATION_INTERVAL_HOURS: int = 6
    AGI_CROSSOVER_INTERVAL_HOURS: int = 24
    MUTATION_CYCLE_INTERVAL_HOURS: int = 6
    CROSSOVER_CYCLE_INTERVAL_HOURS: int = 168  #weekly
    NECROMANCY_INTERVAL_DAYS: int = 7

    # --------------------------------------------------------------------------
    # AGI - Self-improvement and autonomy features
    # --------------------------------------------------------------------------
    # AGI Autonomy
    AGI_AUTO_PROMOTE: bool = False
    AGI_AUTO_ENABLE: bool = False
    AGI_STRATEGY_HEALTH_ENABLED: bool = True
    AGI_HEALTH_CHECK_ENABLED: bool = True
    AGI_REHABILITATION_ENABLED: bool = True
    AGI_BANKROLL_ALLOCATION_ENABLED: bool = False
    REGIME_ROUTING_ENABLED: bool = True
    ENABLE_PAIR_COST_ARB: bool = True
    USE_EVENT_BUS_HANDLERS: bool = True

    # Promotion thresholds
    REGISTRY_MIN_WIN_RATE: float = 0.30
    REGISTRY_MIN_ROI: float = -0.30

    # Rehabilitation
    AGI_REHAB_COOLDOWN_DAYS: int = 7
    AGI_REHAB_MIN_TRADES: int = 10
    AGI_REHAB_WIN_RATE_THRESHOLD: float = 0.50
    AGI_REHAB_LITE_COOLDOWN_HOURS: int = 1
    AGI_REHAB_LITE_RE_DISABLE_HOURS: int = 4
    AGI_REHAB_LITE_WIN_RATE_THRESHOLD: float = 0.30
    AGI_AUTO_DISABLE_MIN_TRADES: int = 10

    # Promotion rules
    AGI_PROMOTER_SHADOW_MIN_TRADES: int = 100
    AGI_PROMOTER_SHADOW_MIN_DAYS: int = 7
    AGI_PROMOTER_SHADOW_MIN_WIN_RATE: float = 0.45
    AGI_PROMOTER_SHADOW_MAX_DRAWDOWN: float = 0.25
    AGI_PROMOTER_PAPER_MIN_TRADES: int = 50
    AGI_PROMOTER_PAPER_MIN_DAYS: int = 3
    AGI_PROMOTER_PAPER_MIN_WIN_RATE: float = 0.50
    AGI_PROMOTER_PAPER_MIN_SHARPE: float = 0.5
    AGI_PROMOTER_PAPER_MAX_DRAWDOWN: float = 0.20

    # Fronttest
    AGI_FRONTTEST_DAYS: int = 14
    AGI_FRONTTEST_MIN_TRADES: int = 10
    AGI_FRONTTEST_MIN_WIN_RATE: float = 0.40

    # Improvement cycles
    AGI_MAX_IMPROVEMENT_ATTEMPTS: int = 3
    AGI_DEMOTION_RETRY_LIMIT: int = 3
    AGI_BROKEN_STRATEGY_OVERHAUL_ENABLED: bool = True

    # Live trial
    LIVE_TRIAL_ENABLED: bool = True
    LIVE_TRIAL_BANKROLL_PCT: float = 0.01
    LIVE_TRIAL_DURATION_DAYS: int = 7
    LIVE_TRIAL_DEGRADATION_THRESHOLD: float = 0.80
    AGI_LIVE_TRIAL_DAYS: int = 7
    AGI_LIVE_TRIAL_MIN_TRADES: int = 10

    # LLM synthesis
    AGI_SYNTHESIS_DAILY_BUDGET: float = 2.00
    AGI_BUDGET_DAILY_LIMIT_USD: float = 2.00

    # Calibration
    AGI_BRIER_DRIFT_THRESHOLD: float = 0.25
    AGI_CALIBRATION_MIN_SAMPLES: int = 30

    # Forensics
    FORENSICS_AUTO_MUTATE: bool = False
    FORENSICS_MAX_MUTATIONS_PER_DAY: int = 3

    # Self-debugger
    SELF_DEBUGGER_MAX_RECOVERY_ATTEMPTS: int = 3

    # Monitoring
    MONITORING_BACKUP_MAX_AGE_HOURS: float = 2.0
    MONITORING_PNL_TOLERANCE_PCT: float = 0.02

    # --------------------------------------------------------------------------
    # WEB - Web search and research settings
    # --------------------------------------------------------------------------
    WEBSEARCH_ENABLED: bool = True
    WEBSEARCH_PROVIDER: str = "tavily"
    WEBSEARCH_FALLBACK_PROVIDER: str = "duckduckgo"
    WEBSEARCH_MAX_RESULTS: int = 5
    WEBSEARCH_TIMEOUT_SECONDS: float = 15.0
    WEBSEARCH_MIN_CONFIDENCE: float = 0.5

    # API keys
    TAVILY_API_KEY: Optional[str] = None
    EXA_API_KEY: Optional[str] = None
    SERPER_API_KEY: Optional[str] = None
    CRW_API_KEY: Optional[str] = None
    MIROFISH_API_KEY: Optional[str] = None
    POLYGON_RPC_URL: str = "https://polygon-bor-rpc.publicnode.com"
    POLYGON_PRIVATE_MEMPOOL_URL: str = "https://polygon-bor-rpc.publicnode.com"

    # --------------------------------------------------------------------------
    # AI - AI/LLM configuration
    # --------------------------------------------------------------------------
    AI_ENABLED: bool = True
    AI_PROVIDER: str = "groq"
    AI_DAILY_BUDGET_USD: float = 1.0
    AI_LOG_ALL_CALLS: bool = True
    AI_MODEL: Optional[str] = None
    AI_API_KEY: Optional[str] = None
    AI_BASE_URL: Optional[str] = None
    AI_SIGNAL_WEIGHT: float = 0.30

    # LLM routing
    LLM_DEFAULT_PROVIDER: str = "groq"
    LLM_DEBATE_PROVIDER: str = "groq"
    LLM_JUDGE_PROVIDER: str = "groq"
    ANTHROPIC_API_KEY: Optional[str] = None
    GROQ_API_KEY: Optional[str] = None
    GEMINI_API_KEY: str = ""

    # LLM models
    GROQ_MODEL: str = "llama-3.1-8b-instant"
    ANTHROPIC_MODEL: str = "claude-sonnet-4-20250514"
    GEMINI_MODEL: str = "gemini-1.5-pro"

    # Debate
    MULTI_AGENT_DEBATE_ENABLED: bool = True
    DEBATE_TIMEOUT_SECONDS: float = 10.0
    BULL_AGENT_ENABLED: bool = True
    BEAR_AGENT_ENABLED: bool = True
    RESEARCH_AGENT_ENABLED: bool = True

    # --------------------------------------------------------------------------
    # BLOCKCHAIN - Polygon and blockchain settings
    # --------------------------------------------------------------------------
    POLYGON_AMOY_RPC: str = "https://rpc-amoy.polygon.technology"
    POLYGON_AMOY_CHAIN_ID: int = 80002
    POLYGON_WS_URL: str = "wss://polygon-rpc.com"
    CONDITIONAL_TOKENS_ADDRESS: str = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
    QUICKNODE_RPC_URL: str = "https://rpc-mainnet.matic.quiknode.pro"

    # Token addresses
    USDC_E_ADDRESS: str = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
    USDC_NATIVE_ADDRESS: str = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
    PUSD_ADDRESS: str = "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb"

    # --------------------------------------------------------------------------
    # DATABASE - Database and caching
    # --------------------------------------------------------------------------
    CACHE_URL: str = "sqlite:///./cache.db"
    CACHE_TTL_SECONDS: int = 300
    REDIS_DEFAULT_URL: str = "redis://localhost:6379"
    REDIS_URL: str = "redis://localhost:6379"
    REDIS_ENABLED: bool = False

    # --------------------------------------------------------------------------
    # BOT - Bot state and trading
    # --------------------------------------------------------------------------
    INITIAL_BANKROLL: float = 100.0
    PAPER_MIN_BANKROLL: float = 50.0
    PAPER_TOPUP_AMOUNT: float = 500.0
    MAX_TOPUPS: int = 10

    # Trading
    AUTO_TRADER_ENABLED: bool = True
    SIGNAL_APPROVAL_MODE: str = "manual"
    SIGNAL_NOTIFICATION_DURATION_MS: int = 10000

    # Jobs
    AUTO_IMPROVE_ENABLED: bool = True
    AUTO_IMPROVE_TRADE_LIMIT: int = 100
    SELF_REVIEW_ENABLED: bool = True
    RESEARCH_PIPELINE_ENABLED: bool = True
    HISTORICAL_DATA_COLLECTOR_ENABLED: bool = True
    DB_BACKUP_ENABLED: bool = True
    DB_BACKUP_INTERVAL_HOURS: int = 6
    DB_BACKUP_DIR: str = "backups"
    DB_BACKUP_RETENTION_DAYS: int = 30

    # Shadow mode
    SHADOW_VALIDATE_ENABLED: bool = True
    SHADOW_USES_REAL_SIGNALS: bool = True

    # Evolution engine
    EVOLUTION_ENGINE_ENABLED: bool = False
    AGI_POPULATION_SIZE: int = 20
    AGI_MUTATION_RATE: float = 0.10
    GENOME_POPULATION_TARGET: int = 25
    GENOME_RAMP_MIN_TRADES: int = 10
    GENOME_INITIAL_ALLOCATION_PCT: float = 0.02

    # --------------------------------------------------------------------------
    # MiroFish - External signal API
    # --------------------------------------------------------------------------
    MIROFISH_ENABLED: bool = True
    MIROFISH_API_TIMEOUT: float = 10.0
    ACTIVITY_LOG_RETENTION_DAYS: int = 90
    PROPOSAL_APPROVAL_REQUIRED: bool = True
    PROPOSAL_EXECUTION_TIMEOUT: int = 5
    DEBATE_CYCLE_TIMEOUT: int = 30
    ACTIVITY_DB_TRANSACTION_TIMEOUT: int = 3
    WEBSOCKET_ACTIVITY_LATENCY_SLA: int = 500

    # --------------------------------------------------------------------------
    # ALERTS - Webhook notifications
    # --------------------------------------------------------------------------
    SLACK_WEBHOOK_URL: Optional[str] = None
    DISCORD_WEBHOOK_URL: Optional[str] = None

    # --------------------------------------------------------------------------
    # BTC - BTC-specific settings
    # --------------------------------------------------------------------------
    BTC_PRICE_SOURCE: str = "coinbase"

    # --------------------------------------------------------------------------
    # POLYMARKET_TOKENS - Token contract addresses
    # --------------------------------------------------------------------------
    # Already defined above, but documented here for clarity
    USDC_E_ADDRESS_TOKENS: str = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
    USDC_NATIVE_ADDRESS_TOKENS: str = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
    PUSD_ADDRESS_TOKENS: str = "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb"

    # --------------------------------------------------------------------------
    # CATEGORY_CONFIDENCE - Category-specific confidence multipliers
    # --------------------------------------------------------------------------
    CATEGORY_CONFIDENCE_ENABLED: bool = True
    CATEGORY_CONFIDENCE_MULTIPLIER: Dict[str, float] = field(default_factory=lambda: {
        "finance": 0.85,
        "politics": 0.95,
        "sports": 1.10,
        "crypto": 1.10,
        "weather": 1.15,
        "entertainment": 1.15,
    })

    # --------------------------------------------------------------------------
    # ARBITRAGE - Arbitrage detection parameters
    # --------------------------------------------------------------------------
    ARBITRAGE_DETECTOR_ENABLED: bool = False
    ARB_MIN_PROFIT: float = 0.02
    ARB_MAX_RETRIES: int = 3
    ARB_CIRCUIT_BREAKER_THRESHOLD: int = 5
    ARB_CIRCUIT_BREAKER_TIMEOUT: float = 60.0
    ARB_POLYMARKET_FEE: float = 0.01
    ARB_KALSHI_FEE: float = 0.01
    ARB_DEFAULT_FEE_RATE: float = 0.02
    ARB_DEFAULT_MIN_SPREAD: float = 0.03
    SPREAD_MODE: str = "static"
    TAKER_FEE_RATE: float = 0.02
    MIN_ARB_SPREAD: float = 0.005
    SSE_EVENT_TYPE_FILTER_ENABLED: bool = True

    # --------------------------------------------------------------------------
    # NEWS - News feed settings
    # --------------------------------------------------------------------------
    NEWS_FEED_ENABLED: bool = False
    RSS_FEEDS: str = "https://feeds.bbci.co.uk/news/rss.xml,https://feeds.reuters.com/reuters/businessNews,https://www.federalreserve.gov/feeds/press_all.xml,https://cointelegraph.com/rss,https://coindesk.com/arc/outboundfeeds/rss/"

    # --------------------------------------------------------------------------
    # DATA_AGGREGATOR - Data freshness settings
    # --------------------------------------------------------------------------
    DATA_AGGREGATOR_MAX_STALE_AGE: float = 300.0
    MIN_WHALE_TRADE_USD_CONFIG: float = 1000.0
    WHALE_LISTENER_ENABLED: bool = False
    MIN_TIME_REMAINING_CONFIG: int = 60
    MAX_TIME_REMAINING_CONFIG: int = 1800
    HFT_MAX_SLIPPAGE_BPS_CONFIG: float = 20.0
    PAPER_MIN_SLIPPAGE_BPS_CONFIG: float = 5.0
    PAPER_SLIPPAGE_BPS_CONFIG: float = 0.0
    PAPER_RANDOM_SLIPPAGE_CONFIG: bool = False
    HFT_ENABLED_CONFIG: bool = True
    HFT_MAX_POSITION_USD_CONFIG: float = 1000.0
    HFT_POSITION_SIZE_PCT_CONFIG: float = 0.25
    SAFE_TUNER_MAX_CHANGE_PCT_CONFIG: float = 0.10
    SAFE_TUNER_MIN_TRADES_FOR_TUNING_CONFIG: int = 20
    SAFE_TUNER_REVERT_SIGMA_THRESHOLD_CONFIG: float = 2.0

    # --------------------------------------------------------------------------
    # BANKROLL - Bankroll management
    # --------------------------------------------------------------------------
    INITIAL_BANKROLL_MANAGEMENT: float = 100.0
    PAPER_MIN_BANKROLL_CONFIG: float = 50.0
    PAPER_TOPUP_AMOUNT_CONFIG: float = 500.0
    MAX_TOPUPS_CONFIG: int = 10

    # --------------------------------------------------------------------------
    # AGI_HEALTH - AGI health check parameters
    # --------------------------------------------------------------------------
    AGI_HEALTH_STALE_STRATEGY_HOURS: float = 2.0
    AGI_HEALTH_DATA_FRESHNESS_HOURS: float = 24.0
    AGI_HEALTH_BUDGET_NEAR_LIMIT_PCT: float = 0.8
    AGI_HEALTH_ORPHAN_MAX_AGE_DAYS: int = 7

    # --------------------------------------------------------------------------
    # RISK_LIMITS - Risk limit configuration
    # --------------------------------------------------------------------------
    RISK_CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = 5
    RISK_DAILY_LOSS_LIMIT: float = 5.0
    RISK_MAX_DAILY_LOSS_PCT_CONFIG: float = 0.10
    RISK_MAX_WEEKLY_LOSS_PCT_CONFIG: float = 0.20

    # --------------------------------------------------------------------------
    # POLLING_INTERVALS - Polling interval configuration
    # --------------------------------------------------------------------------
    POLLING_FAST_MS: int = 2000
    POLLING_NORMAL_MS: int = 10000
    POLLING_SLOW_MS: int = 30000
    POLLING_VERY_SLOW_MS: int = 60000

    # --------------------------------------------------------------------------
    # VALIDATION - Validation methods
    # --------------------------------------------------------------------------

    def validate(self) -> list[str]:
        """
        Validate all configuration values.

        Returns:
            List of validation issues (empty if valid)
        """
        issues: list[str] = []

        # Check required values
        if not self.DATABASE_URL:
            issues.append("DATABASE_URL is required")

        if not self.GAMMA_API_URL:
            issues.append("GAMMA_API_URL is required")

        # Check API endpoints are valid URLs
        api_urls = [
            self.GAMMA_API_URL,
            self.DATA_API_URL,
            self.CLOB_API_URL,
            self.KALSHI_API_URL,
            self.BINANCE_API_URL,
            self.COINBASE_API_URL,
            self.TAVILY_API_URL,
            self.MIROFISH_API_URL,
        ]

        for url in api_urls:
            if url and not url.startswith(('http://', 'https://', 'wss://', 'ws://')):
                issues.append(f"Invalid URL format: {url}")

        # Check rate limits are positive
        if self.RATE_LIMIT_GAMMA <= 0:
            issues.append("RATE_LIMIT_GAMMA must be positive")
        if self.RATE_LIMIT_KALSHI <= 0:
            issues.append("RATE_LIMIT_KALSHI must be positive")
        if self.RATE_LIMIT_CRYPTO <= 0:
            issues.append("RATE_LIMIT_CRYPTO must be positive")

        # Check rate limit backoff parameters
        if self.RATE_LIMIT_BACKOFF_BASE < 1.0:
            issues.append("RATE_LIMIT_BACKOFF_BASE must be >= 1.0")
        if self.RATE_LIMIT_MAX_DELAY < self.RATE_LIMIT_BACKOFF_BASE:
            issues.append("RATE_LIMIT_MAX_DELAY must be >= RATE_LIMIT_BACKOFF_BASE")

        # Check port numbers are valid
        if self.PORT < 1 or self.PORT > 65535:
            issues.append(f"PORT must be between 1 and 65535, got {self.PORT}")

        # Check percentages are in valid range (0-1)
        risky_floats = [
            ('KELLY_FRACTION', self.KELLY_FRACTION, 0.0, 0.5),
            ('MAX_POSITION_FRACTION', self.MAX_POSITION_FRACTION, 0.0, 1.0),
            ('MAX_TOTAL_EXPOSURE_FRACTION', self.MAX_TOTAL_EXPOSURE_FRACTION, 0.0, 1.0),
            ('SLIPPAGE_TOLERANCE', self.SLIPPAGE_TOLERANCE, 0.0, 0.1),
            ('DAILY_DRAWDOWN_LIMIT_PCT', self.DAILY_DRAWDOWN_LIMIT_PCT, 0.0, 0.5),
            ('WEEKLY_DRAWDOWN_LIMIT_PCT', self.WEEKLY_DRAWDOWN_LIMIT_PCT, 0.0, 0.5),
            ('DAILY_LOSS_FLOOR_PCT', self.DAILY_LOSS_FLOOR_PCT, -0.5, 0.0),
            ('WEEKLY_LOSS_FLOOR_PCT', self.WEEKLY_LOSS_FLOOR_PCT, -0.5, 0.0),
            ('AI_SIGNAL_WEIGHT', self.AI_SIGNAL_WEIGHT, 0.0, 0.5),
            ('HFT_POSITION_SIZE_PCT', self.HFT_POSITION_SIZE_PCT, 0.01, 0.25),
            ('WEATHER_MAX_BANKROLL_FRACTION', self.WEATHER_MAX_BANKROLL_FRACTION, 0.0, 1.0),
            ('HFT_ARB_MIN_PROFIT', self.HFT_ARB_MIN_PROFIT, 0.0, 1.0),
            ('HFT_WHALE_MIN_SCORE', self.HFT_WHALE_MIN_SCORE, 0.0, 1.0),
            ('HFT_EXECUTION_AUTO_EXECUTE_MIN_CONFIDENCE', self.HFT_EXECUTION_AUTO_EXECUTE_MIN_CONFIDENCE, 0.0, 1.0),
        ]

        for name, value, min_val, max_val in risky_floats:
            if not (min_val <= value <= max_val):
                issues.append(f"{name} must be between {min_val} and {max_val}, got {value}")

        # Check integer ranges
        risky_ints = [
            ('HFT_MAX_POSITION_USD', self.HFT_MAX_POSITION_USD, 100, 100000),
            ('MAX_TRADES_PER_WINDOW', self.MAX_TRADES_PER_WINDOW, 1, 1000),
            ('MAX_TRADES_PER_SCAN', self.MAX_TRADES_PER_SCAN, 1, 1000),
            ('AUTO_TRADER_BATCH_SIZE', self.AUTO_TRADER_BATCH_SIZE, 1, 1000),
            ('MAX_TOTAL_PENDING_TRADES', self.MAX_TOTAL_PENDING_TRADES, 1, 1000),
            ('STALE_TRADE_HOURS', self.STALE_TRADE_HOURS, 1, 720),
            ('SCANNER_PAGE_SIZE', self.SCANNER_PAGE_SIZE, 100, 1000),
            ('SCANNER_SEMAPHORE_LIMIT', self.SCANNER_SEMAPHORE_LIMIT, 10, 100),
            ('SCANNER_MAX_MARKETS', self.SCANNER_MAX_MARKETS, 1000, 100000),
            ('MIN_TIME_REMAINING', self.MIN_TIME_REMAINING, 1, 3600),
            ('MAX_TIME_REMAINING', self.MAX_TIME_REMAINING, 60, 7200),
        ]

        for name, value, min_val, max_val in risky_ints:
            if not (min_val <= value <= max_val):
                issues.append(f"{name} must be between {min_val} and {max_val}, got {value}")

        # Check scan intervals are reasonable
        if self.SCAN_INTERVAL_SECONDS < 5:
            issues.append(f"SCAN_INTERVAL_SECONDS too aggressive: {self.SCAN_INTERVAL_SECONDS}s (min: 5s)")
        if self.SETTLEMENT_INTERVAL_SECONDS < 30:
            issues.append(f"SETTLEMENT_INTERVAL_SECONDS too aggressive: {self.SETTLEMENT_INTERVAL_SECONDS}s (min: 30s)")

        # Check HFT parameters
        if self.HFT_SCANNER_CIRCUIT_BREAKER_THRESHOLD < 1:
            issues.append("HFT_SCANNER_CIRCUIT_BREAKER_THRESHOLD must be >= 1")
        if self.HFT_SCANNER_CIRCUIT_BREAKER_TIMEOUT < 1:
            issues.append("HFT_SCANNER_CIRCUIT_BREAKER_TIMEOUT must be >= 1s")

        # Check AGI thresholds
        if self.REGISTRY_MIN_WIN_RATE < 0 or self.REGISTRY_MIN_WIN_RATE > 1:
            issues.append(f"REGISTRY_MIN_WIN_RATE must be 0-1, got {self.REGISTRY_MIN_WIN_RATE}")
        if self.REGISTRY_MIN_ROI < -1:
            issues.append(f"REGISTRY_MIN_ROI must be >= -1, got {self.REGISTRY_MIN_ROI}")

        # Check intervals are positive
        positive_ints = [
            ('SCAN_INTERVAL_SECONDS', self.SCAN_INTERVAL_SECONDS),
            ('SETTLEMENT_INTERVAL_SECONDS', self.SETTLEMENT_INTERVAL_SECONDS),
            ('AGI_PROMOTION_INTERVAL_HOURS', self.AGI_PROMOTION_INTERVAL_HOURS),
            ('AGI_HEALTH_CHECK_INTERVAL_MINUTES', self.AGI_HEALTH_CHECK_INTERVAL_MINUTES),
            ('JOB_TIMEOUT_SECONDS', self.JOB_TIMEOUT_SECONDS),
            ('MAX_CONCURRENT_JOBS', self.MAX_CONCURRENT_JOBS),
            ('DB_EXECUTOR_MAX_WORKERS', self.DB_EXECUTOR_MAX_WORKERS),
            ('AGI_CALIBRATION_CHECK_INTERVAL_HOURS', self.AGI_CALIBRATION_CHECK_INTERVAL_HOURS),
            ('AUTO_IMPROVE_INTERVAL_DAYS', self.AUTO_IMPROVE_INTERVAL_DAYS),
            ('SELF_REVIEW_INTERVAL_DAYS', self.SELF_REVIEW_INTERVAL_DAYS),
            ('RESEARCH_PIPELINE_INTERVAL_HOURS', self.RESEARCH_PIPELINE_INTERVAL_HOURS),
            ('AGI_IMPROVEMENT_CYCLE_INTERVAL_HOURS', self.AGI_IMPROVEMENT_CYCLE_INTERVAL_HOURS),
            ('HISTORICAL_DATA_COLLECTOR_INTERVAL_HOURS', self.HISTORICAL_DATA_COLLECTOR_INTERVAL_HOURS),
            ('ARBITRAGE_SCAN_INTERVAL_SECONDS', self.ARBITRAGE_SCAN_INTERVAL_SECONDS),
            ('NEWS_FEED_INTERVAL_SECONDS', self.NEWS_FEED_INTERVAL_SECONDS),
            ('AGI_MUTATION_INTERVAL_HOURS', self.AGI_MUTATION_INTERVAL_HOURS),
            ('AGI_CROSSOVER_INTERVAL_HOURS', self.AGI_CROSSOVER_INTERVAL_HOURS),
            ('MUTATION_CYCLE_INTERVAL_HOURS', self.MUTATION_CYCLE_INTERVAL_HOURS),
            ('CROSSOVER_CYCLE_INTERVAL_HOURS', self.CROSSOVER_CYCLE_INTERVAL_HOURS),
            ('NECROMANCY_INTERVAL_DAYS', self.NECROMANCY_INTERVAL_DAYS),
            ('AGI_REHAB_COOLDOWN_DAYS', self.AGI_REHAB_COOLDOWN_DAYS),
            ('AGI_REHAB_MIN_TRADES', self.AGI_REHAB_MIN_TRADES),
            ('AGI_PROMOTER_SHADOW_MIN_TRADES', self.AGI_PROMOTER_SHADOW_MIN_TRADES),
            ('AGI_PROMOTER_SHADOW_MIN_DAYS', self.AGI_PROMOTER_SHADOW_MIN_DAYS),
            ('AGI_PROMOTER_PAPER_MIN_TRADES', self.AGI_PROMOTER_PAPER_MIN_TRADES),
            ('AGI_PROMOTER_PAPER_MIN_DAYS', self.AGI_PROMOTER_PAPER_MIN_DAYS),
            ('AGI_FRONTTEST_DAYS', self.AGI_FRONTTEST_DAYS),
            ('AGI_FRONTTEST_MIN_TRADES', self.AGI_FRONTTEST_MIN_TRADES),
            ('AGI_MAX_IMPROVEMENT_ATTEMPTS', self.AGI_MAX_IMPROVEMENT_ATTEMPTS),
            ('AGI_DEMOTION_RETRY_LIMIT', self.AGI_DEMOTION_RETRY_LIMIT),
            ('AGI_LIVE_TRIAL_DAYS', self.AGI_LIVE_TRIAL_DAYS),
            ('AGI_LIVE_TRIAL_MIN_TRADES', self.AGI_LIVE_TRIAL_MIN_TRADES),
            ('AGI_REHAB_LITE_COOLDOWN_HOURS', self.AGI_REHAB_LITE_COOLDOWN_HOURS),
            ('AGI_REHAB_LITE_RE_DISABLE_HOURS', self.AGI_REHAB_LITE_RE_DISABLE_HOURS),
            ('AGI_AUTO_DISABLE_MIN_TRADES', self.AGI_AUTO_DISABLE_MIN_TRADES),
            ('CACHE_TTL_SECONDS', self.CACHE_TTL_SECONDS),
            ('DB_BACKUP_INTERVAL_HOURS', self.DB_BACKUP_INTERVAL_HOURS),
            ('DB_BACKUP_RETENTION_DAYS', self.DB_BACKUP_RETENTION_DAYS),
            ('HISTORICAL_DATA_COLLECTOR_INTERVAL_HOURS', self.HISTORICAL_DATA_COLLECTOR_INTERVAL_HOURS),
            ('AGI_HEALTH_ORPHAN_MAX_AGE_DAYS', self.AGI_HEALTH_ORPHAN_MAX_AGE_DAYS),
            ('MAX_TOPUPS', self.MAX_TOPUPS),
            ('DEBATE_CYCLE_TIMEOUT', self.DEBATE_CYCLE_TIMEOUT),
            ('ACTIVITY_DB_TRANSACTION_TIMEOUT', self.ACTIVITY_DB_TRANSACTION_TIMEOUT),
            ('WEBSOCKET_ACTIVITY_LATENCY_SLA', self.WEBSOCKET_ACTIVITY_LATENCY_SLA),
            ('PAPER_MIN_ORDER_USDC', self.PAPER_MIN_ORDER_USDC),
            ('MIN_ORDER_USDC', self.MIN_ORDER_USDC),
            ('SCANNER_MIN_EDGE', int(self.SCANNER_MIN_EDGE * 100)),
            ('SCANNER_STALE_THRESHOLD_SECONDS', int(self.SCANNER_STALE_THRESHOLD_SECONDS * 10)),
            ('SCANNER_MAX_MARKETS', self.SCANNER_MAX_MARKETS),
        ]

        for name, value in positive_ints:
            if value < 1:
                issues.append(f"{name} must be >= 1, got {value}")

        # Check timeouts are positive
        positive_floats = [
            ('RATE_LIMIT_BACKOFF_BASE', self.RATE_LIMIT_BACKOFF_BASE),
            ('RATE_LIMIT_MAX_DELAY', self.RATE_LIMIT_MAX_DELAY),
            ('DEBATE_TIMEOUT_SECONDS', self.DEBATE_TIMEOUT_SECONDS),
            ('MIROFISH_API_TIMEOUT', self.MIROFISH_API_TIMEOUT),
            ('MIN_DEBATE_EDGE', self.MIN_DEBATE_EDGE),
            ('MIN_EDGE_THRESHOLD', self.MIN_EDGE_THRESHOLD),
            ('MAX_ENTRY_PRICE', self.MAX_ENTRY_PRICE),
            ('KELLY_FRACTION', self.KELLY_FRACTION),
            ('DAILY_LOSS_LIMIT', self.DAILY_LOSS_LIMIT),
            ('MAX_TRADE_SIZE', self.MAX_TRADE_SIZE),
            ('INITIAL_BANKROLL', self.INITIAL_BANKROLL),
        ]

        for name, value in positive_floats:
            if value < 0:
                issues.append(f"{name} must be >= 0, got {value}")

        return issues

    # ------------------------------------------------------------------
    # Derived Properties
    # ------------------------------------------------------------------

    @property
    def active_modes_set(self) -> set[str]:
        valid = {"paper", "testnet", "live"}
        modes = {m.strip() for m in self.ACTIVE_MODES.split(",") if m.strip()}
        return modes & valid or {"paper"}

    def is_mode_active(self, mode: str) -> bool:
        return mode in self.active_modes_set


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database (supports SQLite for development, PostgreSQL for production, MySQL also supported)
    # Recommended MySQL URL format: mysql+pymysql://user:password@host:3306/mydatabase
    # Recommended PostgreSQL URL format: postgresql+psycopg2://user:password@host:5432/mydatabase
    DATABASE_URL: str = f"sqlite:///{DB_PATH}"

    @property
    def is_postgres(self) -> bool:
        return "postgresql" in self.DATABASE_URL

    @property
    def is_sqlite(self) -> bool:
        return "sqlite" in self.DATABASE_URL

    @field_validator("DATABASE_URL")
    @classmethod
    def validate_mysql_url(cls, v: str) -> str:
        if v.startswith("mysql://") and "+pymysql" not in v:
            logger.warning(
                "MySQL DATABASE_URL detected without '+pymysql'. "
                "Consider using 'mysql+pymysql://...' for better compatibility."
            )
        return v

    # PostgreSQL pool settings (used when DATABASE_URL starts with postgresql://)
    POSTGRES_POOL_SIZE: int = 20
    POSTGRES_MAX_OVERFLOW: int = 40
    POSTGRES_POOL_TIMEOUT: int = 30
    POSTGRES_POOL_RECYCLE: int = 3600
    POSTGRES_SSL_MODE: str = "prefer"

    # Polymarket Token Addresses
    USDC_E_ADDRESS: str = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
    USDC_NATIVE_ADDRESS: str = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
    PUSD_ADDRESS: str = "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb"

    # API Keys (optional)
    POLYMARKET_API_KEY: Optional[str] = None

    # Polymarket auth (for live trading)
    POLYMARKET_PRIVATE_KEY: Optional[str] = None
    POLYMARKET_API_SECRET: Optional[str] = None
    POLYMARKET_API_PASSPHRASE: Optional[str] = None
    POLYMARKET_SIGNATURE_TYPE: int = 0  # 0=EOA, 1=Poly-Proxy (email login), 2=Poly-EOA

    # Polymarket Builder Program credentials (for testnet/live gasless trading)
    POLYMARKET_BUILDER_API_KEY: Optional[str] = None
    POLYMARKET_BUILDER_SECRET: Optional[str] = None
    POLYMARKET_BUILDER_PASSPHRASE: Optional[str] = None
    POLYMARKET_BUILDER_ADDRESS: Optional[str] = (
        None  # Builder proxy address (funder for CLOB orders)
    )
    POLYMARKET_WALLET_ADDRESS: Optional[str] = None

    # Polymarket Relayer API (gasless on-chain operations)
    POLYMARKET_RELAYER_API_KEY: Optional[str] = None
    POLYMARKET_RELAYER_API_KEY_ADDRESS: Optional[str] = None

    # Kalshi API
    KALSHI_API_KEY_ID: Optional[str] = None
    KALSHI_PRIVATE_KEY_PATH: Optional[str] = None
    KALSHI_ENABLED: bool = False

    # AI API Keys
    GROQ_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None

    # AI Model Configuration
    GROQ_MODEL: str = "llama-3.1-8b-instant"
    ANTHROPIC_MODEL: str = "claude-sonnet-4-20250514"

    # AI Provider Selection: groq, claude, omniroute, custom
    AI_PROVIDER: str = "groq"

    # LLM Router — role-based provider routing
    LLM_DEFAULT_PROVIDER: str = "groq"
    LLM_DEBATE_PROVIDER: str = "groq"
    LLM_JUDGE_PROVIDER: str = "groq"

    # Custom / OmniRoute provider settings (OpenAI-compatible API)
    AI_BASE_URL: Optional[str] = None  # e.g. https://api.omniroute.ai/v1
    AI_MODEL: Optional[str] = None  # overrides provider default
    AI_API_KEY: Optional[str] = None  # API key for custom/omniroute providers

    # AI Feature Flags
    AI_ENABLED: bool = True  # Master toggle for AI-enhanced signals
    job_worker_enabled: bool = True  # Enable background jobs (scheduler/worker)
    shadow_mode: bool = True  # Global shadow mode (no live trades)
    AI_LOG_ALL_CALLS: bool = True
    AI_DAILY_BUDGET_USD: float = 1.0
    AI_SIGNAL_WEIGHT: float = 0.30  # Weight of AI in ensemble (0 = disabled, max 0.50)

    # Debate engine gate — only invoke Bull/Bear/Judge debate when initial
    # single-pass edge exceeds this threshold.  Lower values mean more debates
    # (more LLM calls, better accuracy); higher values skip debate for
    # borderline signals and save tokens.
    MIN_DEBATE_EDGE: float = 0.04

    # Trading modes: comma-separated list of active modes (e.g. "paper,testnet")
    # Each mode can run independently. At least one must be active.
    ACTIVE_MODES: str = "paper"

    # Testnet / network config
    POLYGON_AMOY_RPC: str = "https://rpc-amoy.polygon.technology"
    POLYGON_AMOY_CHAIN_ID: int = 80002

    INITIAL_BANKROLL: float = 100.0
    KELLY_FRACTION: float = 0.30  # 30% Kelly - more aggressive (winners used bigger positions)

    # BTC 5-min specific settings
    SCAN_INTERVAL_SECONDS: int = 120  # Scan every 2 min (was 10s — reduced to avoid Polymarket 429)
    SETTLEMENT_INTERVAL_SECONDS: int = 120  # Check settlements every 2 min
    BTC_PRICE_SOURCE: str = "coinbase"
    MIN_EDGE_THRESHOLD: float = (
        0.03  # 3% edge required - permissive default; BTC strategies typically show 3-6% edge
    )
    MAX_ENTRY_PRICE: float = 0.80  # Allow entries up to 80c for bond-like trades
    MAX_TRADES_PER_WINDOW: int = 20
    MAX_TRADES_PER_SCAN: int = int(os.getenv("MAX_TRADES_PER_SCAN", "10"))  # type: ignore[assignment]
    AUTO_TRADER_BATCH_SIZE: int = int(os.getenv("AUTO_TRADER_BATCH_SIZE", "100"))  # type: ignore[assignment]
    MAX_TOTAL_PENDING_TRADES: int = 50
    STALE_TRADE_HOURS: int = 48

    # Risk management — tuned for $100 bankroll
    DAILY_LOSS_LIMIT: float = 5.0
    DAILY_LOSS_LIMIT_PCT: float = 0.10  # Percentage of bankroll for daily loss limit (overrides flat DAILY_LOSS_LIMIT when set)
    LONGSHOT_NO_BIAS_WEIGHT: float = 0.10
    HFT_ENABLED: bool = True
    CATEGORY_CONFIDENCE_ENABLED: bool = True
    CATEGORY_CONFIDENCE_MULTIPLIER: dict = {
        "finance": 0.85,
        "politics": 0.95,
        "sports": 1.10,
        "crypto": 1.10,
        "weather": 1.15,
        "entertainment": 1.15,
    }
    MAX_TRADE_SIZE: float = 8.0  # Global absolute ceiling on any single trade size (USD)
    MIN_ORDER_USDC: float = 5.0  # Polymarket minimum order size (live mode)
    PAPER_MIN_ORDER_USDC: float = 1.0  # Simulated minimum for paper/testing
    MIN_TIME_REMAINING: int = 60  # Don't trade windows closing in < 60s
    MAX_TIME_REMAINING: int = 1800  # Trade windows up to 30min out

    # Indicator weights for composite signal (must sum to ~1.0)
    WEIGHT_RSI: float = 0.20
    WEIGHT_MOMENTUM: float = 0.35
    WEIGHT_VWAP: float = 0.20
    WEIGHT_SMA: float = 0.15
    WEIGHT_MARKET_SKEW: float = 0.10

    # Volume filter
    MIN_MARKET_VOLUME: float = 100.0  # Low volume for 5-min markets

    # HFT risk parameters
    HFT_POSITION_SIZE_PCT: float = 0.25
    HFT_MAX_POSITION_USD: float = 1000.0

    @field_validator('HFT_POSITION_SIZE_PCT')
    @classmethod
    def validate_hft_position_size_pct(cls, v):
        if not (0.01 <= v <= 0.25):
            raise ValueError(f"HFT_POSITION_SIZE_PCT must be between 0.01 and 0.25 (inclusive), got {v}")
        return v

    @field_validator('HFT_MAX_POSITION_USD')
    @classmethod
    def validate_hft_max_position_usd(cls, v):
        if not (100 <= v <= 100000):
            raise ValueError(f"HFT_MAX_POSITION_USD must be between 100 and 100000 (inclusive), got {v}")
        return v


    # Parameter tuning safeguards (safe_param_tuner)
    SAFE_TUNER_MAX_CHANGE_PCT: float = 0.10  # Max 10% parameter drift per tuning cycle
    SAFE_TUNER_MIN_TRADES_FOR_TUNING: int = 20  # Require at least 20 trades before tuning
    SAFE_TUNER_REVERT_SIGMA_THRESHOLD: float = 2.0  # Degrade >2σ triggers parameter revert
    WEATHER_ENABLED: bool = True
    WEATHER_SCAN_INTERVAL_SECONDS: int = 60  # 1 min
    WEATHER_SETTLEMENT_INTERVAL_SECONDS: int = 1800  # 30 min
    WEATHER_MIN_EDGE_THRESHOLD: float = 0.05
    WEATHER_MAX_ENTRY_PRICE: float = 0.70
    WEATHER_MAX_TRADE_SIZE: float = 10.0
    WEATHER_CITIES: str = (
        "nyc,chicago,miami,dallas,seattle,atlanta,los_angeles,denver,london,seoul,tokyo"
    )

    # Data aggregator staleness guard (seconds; None = unlimited)
    DATA_AGGREGATOR_MAX_STALE_AGE: float = 300.0

    # Admin API security
    ADMIN_API_KEY: Optional[str] = None
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:5174,http://127.0.0.1:5173,http://127.0.0.1:5174,https://polyedge.aitradepulse.com,http://polyedge.aitradepulse.com"

    # Telegram bot
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_ADMIN_CHAT_IDS: str = ""  # comma-separated chat IDs
    TELEGRAM_HIGH_CONFIDENCE_ALERTS: bool = (
        True  # Send alerts for high-confidence signals (>=75%)
    )

    # Polygon blockchain listener
    POLYGON_WS_URL: str = "wss://polygon-rpc.com"
    CONDITIONAL_TOKENS_ADDRESS: str = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
    MIN_WHALE_TRADE_USD: float = 1000.0
    WHALE_LISTENER_ENABLED: bool = False

    # Polymarket WebSocket (real-time market data)
    POLYMARKET_WS_ENABLED: bool = True
    POLYMARKET_USER_WS_ENABLED: bool = False
    POLYMARKET_WS_SUBSCRIPTION_LIMIT: int = 200
    WS_HANDLER_TIMEOUT_MS: int = 100

    # Job Queue Settings
    JOB_WORKER_ENABLED: bool = True  # Required for trading — enables APScheduler strategy cycles
    JOB_QUEUE_URL: str = "sqlite:///./job_queue.db"  # or "redis://localhost:6379"
    JOB_TIMEOUT_SECONDS: int = 300  # 5 minutes
    MAX_CONCURRENT_JOBS: int = 1
    DB_EXECUTOR_MAX_WORKERS: int = 4

    MAX_POSITION_FRACTION: float = 0.08
    MAX_TOTAL_EXPOSURE_FRACTION: float = 0.70
    SLIPPAGE_TOLERANCE: float = 0.02
    DAILY_DRAWDOWN_LIMIT_PCT: float = (
        0.10  # Pause trading if 24h loss > 10% of bankroll
    )
    WEEKLY_DRAWDOWN_LIMIT_PCT: float = (
        0.20  # Pause trading if 7d loss > 20% of bankroll
    )
    DAILY_LOSS_FLOOR_PCT: float = (
        -0.10  # Pause all strategies for 24h if daily PnL < -10% of bankroll
    )
    WEEKLY_LOSS_FLOOR_PCT: float = (
        -0.20  # Revert to PAPER mode for 7 days if weekly PnL < -20% of bankroll
    )

    DRAWDOWN_BREAKER_ENABLED_PER_MODE: dict = {
        "paper": False,
        "testnet": True,
        "live": True,
    }
    DAILY_LOSS_LIMIT_ENABLED_PER_MODE: dict = {
        "paper": False,
        "testnet": True,
        "live": True,
    }

    AUTO_APPROVE_MIN_CONFIDENCE: float = 0.5
    AUTO_TRADER_ENABLED: bool = True

    # Signal approval mode: "manual", "auto_approve", "auto_deny"
    # manual: always show popup for user approval
    # auto_approve: auto-approve signals above AUTO_APPROVE_MIN_CONFIDENCE
    # auto_deny: auto-deny all signals
    SIGNAL_APPROVAL_MODE: str = "manual"

    # Signal notification duration (milliseconds)
    SIGNAL_NOTIFICATION_DURATION_MS: int = 10000

    # Auto-improve job (weekly learning from outcomes)
    AUTO_IMPROVE_ENABLED: bool = True
    AUTO_IMPROVE_INTERVAL_DAYS: int = 7  # Run weekly
    AUTO_IMPROVE_TRADE_LIMIT: int = 100  # Analyze last N trades

    # Self-review job (daily attribution, postmortems, degradation detection)
    SELF_REVIEW_ENABLED: bool = True
    SELF_REVIEW_INTERVAL_DAYS: int = 1  # Run daily

    # Research pipeline job (continuous market research)
    RESEARCH_PIPELINE_ENABLED: bool = True
    RESEARCH_PIPELINE_INTERVAL_HOURS: int = 4  # Run every 4 hours

    # AGI Autonomy Controls (full automatic operation)
    USE_EVENT_BUS_HANDLERS: bool = True  # Enable reactive event-driven AGI handlers (scheduler jobs become heartbeat fallback)
    AGI_AUTO_PROMOTE: bool = False  # Allow paper→live without human approval (default: off for safety)
    AGI_AUTO_ENABLE: bool = False  # Auto-enable strategies upon promotion to live
    AGI_PROMOTION_INTERVAL_HOURS: int = 6  # How often to evaluate experiments for promotion
    AGI_STRATEGY_HEALTH_ENABLED: bool = True  # Auto-disable underperforming strategies

    REGISTRY_MIN_WIN_RATE: float = 0.30
    REGISTRY_MIN_ROI: float = -0.30
    AGI_BANKROLL_ALLOCATION_ENABLED: bool = False  # Auto-reallocate capital by strategy rank
    AGI_BANKROLL_ALLOCATION_INTERVAL_DAYS: int = 1  # Rebalance frequency
    REGIME_ROUTING_ENABLED: bool = True  # Enable regime-adjusted confidence thresholds
    ENABLE_PAIR_COST_ARB: bool = True  # Enable pair cost arbitrage monitoring
    MIN_ARB_SPREAD: float = 0.005  # Minimum arbitrage spread (0.5%) to trigger
    TAKER_FEE_RATE: float = 0.02  # Polymarket taker fee rate (2%)
    SHADOW_VALIDATE_ENABLED: bool = True  # Validate shadow genomes every 5 minutes
    SHADOW_USES_REAL_SIGNALS: bool = True  # Shadow experiments use real trade data, never fabricate

    AGI_HEALTH_CHECK_ENABLED: bool = True
    AGI_HEALTH_CHECK_INTERVAL_MINUTES: int = 15
    AGI_NIGHTLY_REVIEW_ENABLED: bool = True
    AGI_NIGHTLY_REVIEW_HOUR: int = 2
    AGI_REHABILITATION_ENABLED: bool = True
    AGI_FRONTTEST_DAYS: int = 14
    AGI_FRONTTEST_MIN_TRADES: int = 10
    AGI_IMPROVEMENT_CYCLE_ENABLED: bool = True
    AGI_IMPROVEMENT_CYCLE_INTERVAL_HOURS: int = 4

    HISTORICAL_DATA_COLLECTOR_ENABLED: bool = True
    PAPER_MIN_BANKROLL: float = 50.0
    PAPER_TOPUP_AMOUNT: float = 500.0

    # Paper trading slippage simulation (defaults = disabled for backward compatibility)
    PAPER_SLIPPAGE_BPS: float = 0.0  # Base slippage in basis points (0 = disabled)
    PAPER_MIN_SLIPPAGE_BPS: float = 5.0  # Minimum slippage even for small orders (0.05%)
    HFT_MAX_SLIPPAGE_BPS: float = 20.0
    PAPER_RANDOM_SLIPPAGE: bool = False  # Add random ±20% jitter to slippage

    MAX_TOPUPS: int = 10
    HISTORICAL_DATA_COLLECTOR_INTERVAL_HOURS: int = 6

    AGI_HEALTH_STALE_STRATEGY_HOURS: float = 2.0
    AGI_HEALTH_DATA_FRESHNESS_HOURS: float = 24.0
    AGI_HEALTH_BUDGET_NEAR_LIMIT_PCT: float = 0.8
    AGI_HEALTH_ORPHAN_MAX_AGE_DAYS: int = 7

    # Wave 9: Meta-Learning Layer
    FORENSICS_AUTO_MUTATE: bool = False  # Auto-apply forensics-driven mutations
    EVOLUTION_ENGINE_ENABLED: bool = False  # Enable evolution engine jobs
    AGI_MUTATION_INTERVAL_HOURS: int = 6
    AGI_CROSSOVER_INTERVAL_HOURS: int = 24
    AGI_POPULATION_SIZE: int = 20
    AGI_MUTATION_RATE: float = 0.10
    GENOME_POPULATION_TARGET: int = 25
    MUTATION_CYCLE_INTERVAL_HOURS: int = 6
    CROSSOVER_CYCLE_INTERVAL_HOURS: int = 168  # weekly
    NECROMANCY_INTERVAL_DAYS: int = 7
    GENOME_RAMP_MIN_TRADES: int = 10
    GENOME_INITIAL_ALLOCATION_PCT: float = 0.02
    FORENSICS_MAX_MUTATIONS_PER_DAY: int = 3
    AGI_NIGHTLY_REVIEW_OUTPUT_DIR: str = "docs/agi-log"
    AGI_NIGHTLY_REVIEW_LOOKBACK_DAYS: int = 7
    AGI_REHAB_COOLDOWN_DAYS: int = 7
    AGI_REHAB_MIN_TRADES: int = 10
    AGI_REHAB_WIN_RATE_THRESHOLD: float = 0.50
    # Lite rehabilitation (T7): lighter path for auto-disabled strategies
    AGI_REHAB_LITE_COOLDOWN_HOURS: int = 1       # re-enable after 1h in paper mode
    AGI_REHAB_LITE_RE_DISABLE_HOURS: int = 4      # re-disable for 4h if still bad
    AGI_REHAB_LITE_WIN_RATE_THRESHOLD: float = 0.30  # keep enabled if WR >= 30%
    AGI_AUTO_DISABLE_MIN_TRADES: int = 10          # exempt strategies with <10 trades
    # LIVE_TRIAL phase configuration (AGI-2)
    LIVE_TRIAL_ENABLED: bool = True
    LIVE_TRIAL_BANKROLL_PCT: float = 0.01   # fraction of bankroll during live trial
    LIVE_TRIAL_DURATION_DAYS: int = 7       # minimum trial period before full promotion
    LIVE_TRIAL_DEGRADATION_THRESHOLD: float = 0.80  # live perf must be >= paper perf * this
    AGI_LIVE_TRIAL_BANKROLL_PCT: float = 0.01  # legacy alias — kept for compatibility
    AGI_LIVE_TRIAL_DAYS: int = 7  # minimum trial period before full promotion
    AGI_LIVE_TRIAL_MIN_TRADES: int = 10
    AGI_DEMOTION_RETRY_LIMIT: int = 3  # max improvement cycles before permanent retirement
    # Demotion → improvement loop (AGI-3)
    AGI_MAX_IMPROVEMENT_ATTEMPTS: int = 3   # max improvement cycles before RETIRED
    # LLM strategy synthesis (AGI-4)
    AGI_SYNTHESIS_DAILY_BUDGET: float = 2.00  # max USD/day for LLM synthesis calls
    # Forensics overhaul for broken strategies (AGI-7)
    AGI_BROKEN_STRATEGY_OVERHAUL_ENABLED: bool = True
    # Calibration drift detection (AI-3)
    AGI_BRIER_DRIFT_THRESHOLD: float = 0.25   # Brier score above this triggers retrain
    AGI_CALIBRATION_MIN_SAMPLES: int = 30     # min settled trades before checking calibration
    AGI_CALIBRATION_CHECK_INTERVAL_HOURS: int = 6  # how often to run calibration check job
    AGI_FRONTTEST_MIN_WIN_RATE: float = 0.40
    AGI_PROMOTER_SHADOW_MIN_TRADES: int = 100
    AGI_PROMOTER_SHADOW_MIN_DAYS: int = 7
    AGI_PROMOTER_SHADOW_MIN_WIN_RATE: float = 0.45
    AGI_PROMOTER_SHADOW_MAX_DRAWDOWN: float = 0.25
    AGI_PROMOTER_PAPER_MIN_TRADES: int = 50
    AGI_PROMOTER_PAPER_MIN_DAYS: int = 3
    AGI_PROMOTER_PAPER_MIN_WIN_RATE: float = 0.50
    AGI_PROMOTER_PAPER_MIN_SHARPE: float = 0.5
    AGI_PROMOTER_PAPER_MAX_DRAWDOWN: float = 0.20
    SELF_DEBUGGER_MAX_RECOVERY_ATTEMPTS: int = 3
    MONITORING_BACKUP_MAX_AGE_HOURS: float = 2.0
    MONITORING_PNL_TOLERANCE_PCT: float = 0.02
    SLACK_WEBHOOK_URL: Optional[str] = None
    DISCORD_WEBHOOK_URL: Optional[str] = None

    DB_BACKUP_INTERVAL_HOURS: int = 6  # Run every 6 hours (0 to disable)
    DB_BACKUP_DIR: str = "backups"
    DB_BACKUP_RETENTION_DAYS: int = 30

    # Phase 2 feature flags
    NEWS_FEED_ENABLED: bool = False
    ARBITRAGE_DETECTOR_ENABLED: bool = False
    SSE_EVENT_TYPE_FILTER_ENABLED: bool = True
    NEWS_FEED_INTERVAL_SECONDS: int = 600
    ARBITRAGE_SCAN_INTERVAL_SECONDS: int = 30

    # Cache Settings
    CACHE_URL: str = "sqlite:///./cache.db"  # or "redis://localhost:6379/0"
    CACHE_TTL_SECONDS: int = 300  # 5 minutes

    # Redis Pub/Sub for WebSocket (multi-instance support)
    REDIS_URL: str = "redis://localhost:6379"
    REDIS_ENABLED: bool = False  # Enable for multi-instance deployments

    # Web Search Provider Settings
    # Primary: "tavily", "crw", "duckduckgo", "exa", "serper"
    # Fallback: "duckduckgo" (free, no API key required)
    WEBSEARCH_PROVIDER: str = "tavily"
    WEBSEARCH_FALLBACK_PROVIDER: str = "duckduckgo"
    WEBSEARCH_ENABLED: bool = True
    TAVILY_API_KEY: Optional[str] = None
    CRW_API_URL: Optional[str] = None  # e.g. https://fastcrw.com/api
    CRW_API_KEY: Optional[str] = None
    EXA_API_KEY: Optional[str] = None
    SERPER_API_KEY: Optional[str] = None
    WEBSEARCH_MAX_RESULTS: int = 5
    WEBSEARCH_TIMEOUT_SECONDS: float = 15.0

    # MiroFish Integration
    MIROFISH_ENABLED: bool = True
    # MIROFISH_API_URL defined below with production default
    MIROFISH_API_KEY: Optional[str] = None
    MIROFISH_API_TIMEOUT: float = 10.0

    # Request Timeout Settings
    API_REQUEST_TIMEOUT: float = 30.0
    DATABASE_QUERY_TIMEOUT: float = 10.0
    EXTERNAL_API_TIMEOUT: float = 15.0

    # Polygon RPC (for on-chain balance checks)
    POLYGON_RPC_URL: str = "https://polygon-bor-rpc.publicnode.com"
    POLYGON_PRIVATE_MEMPOOL_URL: str = "https://polygon-bor-rpc.publicnode.com"

    # Brain / BK-Hub integration
    BRAIN_API_URL: str = "http://localhost:9099"

    # RSS News Feeds (comma-separated URLs)
    RSS_FEED_URLS: str = "https://feeds.bbci.co.uk/news/rss.xml,https://feeds.reuters.com/reuters/businessNews,https://www.federalreserve.gov/feeds/press_all.xml,https://cointelegraph.com/rss,https://coindesk.com/arc/outboundfeeds/rss/"

    # Arb / probability arb thresholds
    ARB_MIN_PROFIT: float = 0.02
    ARB_MAX_RETRIES: int = 3
    ARB_CIRCUIT_BREAKER_THRESHOLD: int = 5
    ARB_CIRCUIT_BREAKER_TIMEOUT: float = 60.0
    ARB_POLYMARKET_FEE: float = 0.01
    ARB_KALSHI_FEE: float = 0.01
    ARB_DEFAULT_FEE_RATE: float = 0.02
    ARB_DEFAULT_MIN_SPREAD: float = 0.03
    SPREAD_MODE: str = "static"  # "static" | "lmsr"
    GEMINI_API_KEY: str = ""
    GEMINI_ENABLED: bool = False
    GEMINI_MODEL: str = "gemini-1.5-pro"

    # Whale frontrun thresholds
    WHALE_FRONTRUN_MIN_SIZE: float = 10000.0
    WHALE_FRONTRUN_MIN_SCORE: float = 0.8
    WHALE_FRONTRUN_MAX_RECONNECT: int = 5
    WHALE_FRONTRUN_DELAY_MS: int = 50
    WHALE_FRONTRUN_SELL_DELAY_MS: int = 1000

    # Universal scanner thresholds
    SCANNER_PAGE_SIZE: int = 500
    SCANNER_SEMAPHORE_LIMIT: int = 50
    SCANNER_MIN_EDGE: float = 0.02
    SCANNER_STALE_THRESHOLD_SECONDS: float = 5.0
    SCANNER_MAX_MARKETS: int = 10000
    MARKET_UNIVERSE_CACHE_TTL_SECONDS: int = int(os.getenv("MARKET_UNIVERSE_CACHE_TTL_SECONDS", "300"))

    # Order executor thresholds
    ORDER_EXECUTOR_MIN_WHALE_SIZE: float = 50.0
    ORDER_EXECUTOR_MIN_DAYS_TO_RESOLUTION: int = 7

    # Line movement detector confidence weights
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

    # Weather EMOS thresholds
    WEATHER_KELLY_FRACTION: float = 0.15
    WEATHER_MAX_BANKROLL_FRACTION: float = 0.05
    WEATHER_DB_PERSISTENCE: bool = False

    # External API base URLs
    GAMMA_API_URL: str = "https://gamma-api.polymarket.com"
    DATA_API_URL: str = "https://data-api.polymarket.com"
    DATA_API_VERSION: str = "v1"
    CLOB_API_URL: str = "https://clob.polymarket.com"
    POLYMARKET_BASE_URL: str = "https://polymarket.com"
    BINANCE_API_URL: str = "https://api.binance.com/api/v3"
    COINBASE_API_URL: str = "https://api.exchange.coinbase.com"
    KRAKEN_API_URL: str = "https://api.kraken.com/0/public"
    BYBIT_API_URL: str = "https://api.bybit.com/v5/market"
    COINGECKO_API_URL: str = "https://api.coingecko.com/api/v3"
    OPEN_METEO_API_URL: str = "https://api.open-meteo.com/v1"
    NWS_API_URL: str = "https://api.weather.gov/gridpoints"
    NWS_BASE_URL: str = "https://api.weather.gov"
    BINANCE_KLINES_URL: str = "https://api.binance.com/api/v3/klines"
    OPEN_METEO_ARCHIVE_URL: str = "https://archive-api.open-meteo.com/v1/archive"
    KALSHI_API_URL: str = "https://api.elections.kalshi.com/trade-api/v2"
    GOLDSKY_API_URL: str = "https://api.goldsky.com/api/public/project_cl6mb8i9h0003e201j6li0diw/subgraphs/orderbook-subgraph/0.0.1/gn"
    RESEARCH_RSS_FEEDS: str = (
        "https://feeds.bbci.co.uk/news/rss.xml,"
        "https://feeds.reuters.com/reuters/businessNews,"
        "https://www.federalreserve.gov/feeds/press_all.xml,"
        "https://cointelegraph.com/rss,"
        "https://coindesk.com/arc/outboundfeeds/rss/"
    )
    POLYMARKET_RELAYER_URL: str = "https://relayer-v2.polymarket.com"
    POLYMARKET_WS_CLOB_URL: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    POLYMARKET_WS_USER_URL: str = "wss://ws-subscriptions-clob.polymarket.com/ws/user"
    POLYMARKET_WS_RTDS_URL: str = "wss://ws-live-data.polymarket.com"
    POLYMARKET_WS_WHALE_URL: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    POLYMARKET_WS_ORDERBOOK_URL: str = "wss://ws.polymarket.com/orderbook"
    QUICKNODE_RPC_URL: str = "https://rpc-mainnet.matic.quiknode.pro"
    OPEN_METEO_ENSEMBLE_URL: str = "https://ensemble-api.open-meteo.com/v1/ensemble"
    OPEN_METEO_GEOCODING_URL: str = "https://geocoding-api.open-meteo.com/v1/search"
    TELEGRAM_API_BASE: str = "https://api.telegram.org"
    MIROFISH_API_URL: str = "https://polyedge-mirofish-api.aitradepulse.com"
    TAVILY_API_URL: str = "https://api.tavily.com/search"
    EXA_API_URL: str = "https://api.exa.ai/search"
    SERPER_API_URL: str = "https://google.serper.dev/search"
    DDG_HTML_URL: str = "https://html.duckduckgo.com/html/"

    @model_validator(mode="after")
    def _validate_trading_credentials(self) -> "Settings":
        for mode in self.active_modes_set:
            if mode == "live":
                if not self.POLYMARKET_PRIVATE_KEY:
                    raise ValueError(
                        "ACTIVE_MODES contains 'live' but POLYMARKET_PRIVATE_KEY is not set. "
                        "API credentials (api_key, api_secret, api_passphrase) are "
                        "auto-derived from the private key at startup."
                    )
            if mode == "testnet":
                if not self.POLYMARKET_PRIVATE_KEY:
                    raise ValueError(
                        "ACTIVE_MODES contains 'testnet' but POLYMARKET_PRIVATE_KEY is not set."
                    )
                if not self.POLYMARKET_BUILDER_API_KEY:
                    logger.warning(
                        "ACTIVE_MODES contains 'testnet' without POLYMARKET_BUILDER_API_KEY — "
                        "CLOB order placement will use standard auth (gas fees apply). "
                        "Set Builder credentials for gasless trading via Builder Program."
                    )
        return self

    @property
    def SIMULATION_MODE(self) -> bool:
        return "live" not in self.active_modes_set

    @property
    def TRADING_MODE(self) -> str:
        first = self.ACTIVE_MODES.split(",")[0].strip() if self.ACTIVE_MODES else "paper"
        return first if first in ("paper", "testnet", "live") else "paper"

    @property
    def active_modes_set(self) -> set[str]:
        valid = {"paper", "testnet", "live"}
        modes = {m.strip() for m in self.ACTIVE_MODES.split(",") if m.strip()}
        return modes & valid or {"paper"}

    def is_mode_active(self, mode: str) -> bool:
        return mode in self.active_modes_set

    @model_validator(mode="after")
    def _validate_trading_params(self) -> "Settings":
        if not (0.0 < self.WEEKLY_DRAWDOWN_LIMIT_PCT <= 1.0):
            raise ValueError(f"WEEKLY_DRAWDOWN_LIMIT_PCT must be in (0.0, 1.0], got {self.WEEKLY_DRAWDOWN_LIMIT_PCT}")
        return self

    @field_validator('AI_SIGNAL_WEIGHT')
    @classmethod
    def validate_ai_signal_weight(cls, v):
        if not (0.0 <= v <= 0.5):
            raise ValueError(f"AI_SIGNAL_WEIGHT must be between 0.0 and 0.5 (inclusive), got {v}")
        return v

    @field_validator('KELLY_FRACTION')
    @classmethod
    def validate_kelly_fraction(cls, v):
        if not (0.0 <= v <= 0.5):
            raise ValueError(f"KELLY_FRACTION must be between 0.0 and 0.5 (inclusive), got {v}. "
                             f"Values above 0.5 (half-Kelly) are highly aggressive and unsafe for automated trading.")
        return v

    @field_validator('DAILY_DRAWDOWN_LIMIT_PCT')
    @classmethod
    def validate_daily_drawdown_limit_pct(cls, v):
        if not (0.0 <= v <= 0.5):
            raise ValueError(f"DAILY_DRAWDOWN_LIMIT_PCT must be between 0.0 and 0.5 (inclusive), got {v}")
        return v

    @model_validator(mode="after")
    def _warn_missing_admin_key(self) -> "Settings":
        """Warn loudly when ADMIN_API_KEY is unset outside shadow/dev mode.

        Does not raise — allows dev environments to run without a key.
        In production (SHADOW_MODE=false, TRADING_MODE=live) an unset key
        leaves all admin endpoints open, which is a security risk.
        """
        if not self.ADMIN_API_KEY:
            _mode = getattr(self, "TRADING_MODE", "paper")
            _shadow = getattr(self, "SHADOW_MODE", True)
            if not _shadow and str(_mode).lower() == "live":
                logger.critical(
                    "ADMIN_API_KEY is not set — all admin endpoints are UNAUTHENTICATED. "
                    "Set ADMIN_API_KEY in your .env file before running in live mode."
                )
        return self

    RATE_LIMIT_GAMMA: int = 100
    RATE_LIMIT_KALSHI: int = 30
    RATE_LIMIT_CRYPTO: int = 60
    RATE_LIMIT_BACKOFF_BASE: float = 2.0
    RATE_LIMIT_MAX_DELAY: float = 60.0
    CB_FAILURE_THRESHOLD: int = 5  # failures before opening circuit
    CB_RECOVERY_TIMEOUT: float = 60.0  # seconds before attempting recovery
    CB_HALF_OPEN_MAX: int = 1  # max concurrent probes in half-open state

    model_config = ConfigDict(env_file=".env", extra="ignore")


# Global settings instance - provides access to all config via dataclass
settings = ConfigRegistry()

# Startup validation - fail fast if config is invalid
def _validate_startup():
    issues = settings.validate()
    if issues:
        print("Configuration validation errors:")
        for issue in issues:
            print(f"  - {issue}")
        raise ValueError(f"Configuration validation failed: {issues[:3]}")
    print("PolyEdge Configuration Loaded Successfully")

_validate_startup()

# Backwards compatibility: Settings still exists for existing code
# This provides a bridge during migration to the new registry system
# New code should use the ConfigRegistry directly or through settings


if __name__ == "__main__":
    # Validation check on startup
    issues = settings.validate()
    if issues:
        print("Configuration validation errors:")
        for issue in issues:
            print(f"  - {issue}")
        raise ValueError(f"Configuration validation failed: {issues[:3]}")

    # Print configuration summary
    print("PolyEdge Configuration Loaded Successfully")
    print(f"  Trading mode: {settings.TRADING_MODE}")
    print(f"  Bankroll: ${settings.INITIAL_BANKROLL:.2f}")
    print(f"  API endpoints configured: {len([k for k in dir(settings) if k.endswith('_URL') and not k.startswith('_')])}")
    print(f"  Jobs enabled: {settings.JOB_WORKER_ENABLED}")
    print(f"  AGI autonomy: {settings.AGI_AUTO_PROMOTE}")

