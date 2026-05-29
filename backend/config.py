"""Configuration settings for the BTC 5-min trading bot."""

import os
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
        for f in dataclasses.fields(self):
            if f.default is not MISSING:
                all_fields[f.name] = f.default
            elif f.default_factory is not MISSING:
                all_fields[f.name] = f.default_factory()
            else:
                all_fields[f.name] = (
                    f.type()
                    if f.type in (dict, list, set, str, int, float, bool)
                    else None
                )

        for name, value in self.__class__.__dict__.items():
            if (
                name.startswith("_")
                or callable(value)
                or isinstance(value, (staticmethod, classmethod, property, Field))
            ):
                continue
            if name not in all_fields:
                all_fields[name] = value

        for name, default in all_fields.items():
            env_val = os.environ.get(name)
            if env_val is not None:
                if isinstance(default, bool):
                    setattr(self, name, env_val.lower() in ("true", "1", "yes"))
                elif isinstance(default, int):
                    setattr(self, name, int(env_val))
                elif isinstance(default, float):
                    setattr(self, name, float(env_val))
                elif isinstance(default, (dict, list)):
                    try:
                        import ast

                        setattr(self, name, ast.literal_eval(env_val))
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
    POLYMARKET_WS_WHALE_URL: str = (
        "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    )
    POLYMARKET_WS_ORDERBOOK_URL: str = "wss://ws.polymarket.com/orderbook"

    # Kalshi API
    KALSHI_API_URL: str = "https://api.elections.kalshi.com/trade-api/v2"

    # --------------------------------------------------------------------------
    # MARKET_PROVIDERS - Configurable prediction market provider registry
    # --------------------------------------------------------------------------
    # Each provider is a dict with url, ws_url, enabled, priority, and kwargs.
    # To add a new provider, just add an entry here. The MarketProviderRegistry
    # will auto-discover and register any provider with a matching manifest.
    MARKET_PROVIDERS: dict = field(
        default_factory=lambda: {
            "polymarket": {
                "enabled": True,
                "priority": 1,
                "api_url": os.getenv(
                    "POLYMARKET_API_URL", "https://clob.polymarket.com"
                ),
                "gamma_url": os.getenv(
                    "GAMMA_API_URL", "https://gamma-api.polymarket.com"
                ),
                "data_url": os.getenv(
                    "DATA_API_URL", "https://data-api.polymarket.com"
                ),
                "ws_url": os.getenv(
                    "POLYMARKET_WS_URL",
                    "wss://ws-subscriptions-clob.polymarket.com/ws/market",
                ),
                "min_order_usd": 5.0,
            },
            "kalshi": {
                "enabled": True,
                "priority": 2,
                "api_url": os.getenv(
                    "KALSHI_API_URL", "https://api.elections.kalshi.com/trade-api/v2"
                ),
                "min_order_usd": 10.0,
            },
        }
    )

    # Default venue for order placement when strategy doesn't specify one
    DEFAULT_VENUE: str = "polymarket"

    # Provider fallback behavior
    PROVIDER_FALLBACK_ENABLED: bool = (
        os.getenv("PROVIDER_FALLBACK_ENABLED", "true").lower() == "true"
    )
    PROVIDER_FALLBACK_ORDER: list[str] = field(
        default_factory=lambda: ["polymarket", "kalshi"]
    )

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
    LIMITLESS_API_URL: str = "https://api.limitless.exchange"
    SXBET_API_URL: str = "https://api.sx.bet"
    # EIP-712 Contract Addresses (override dynamic fetching if provided)
    SXBET_EXCHANGE_CONTRACT_ADDRESS: Optional[str] = None
    LIMITLESS_EXCHANGE_CONTRACT_ADDRESS: Optional[str] = None
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
    GOLDSKY_API_URL: str = (
        "https://api.goldsky.com/api/public/project_cl6mb8i9h0003e201j6li0diw/subgraphs/orderbook-subgraph/0.0.1/gn"
    )

    # API_BASE_URL - FastAPI server URL (constructed from API_HOST and API_PORT)
    API_HOST: str = "localhost"
    API_PORT: int = 8005
    API_BASE_URL: str = "http://localhost:8005"

    # RSS Feed URLs (comma-separated)
    RSS_FEED_URLS: str = (
        "https://feeds.bbci.co.uk/news/rss.xml,https://feeds.reuters.com/reuters/businessNews,https://www.federalreserve.gov/feeds/press_all.xml,https://cointelegraph.com/rss,https://coindesk.com/arc/outboundfeeds/rss/"
    )

    # --------------------------------------------------------------------------
    # RATE_LIMITS - Rate limit settings for API services
    # --------------------------------------------------------------------------
    RATE_LIMIT_GAMMA: int = 100  # requests per minute
    RATE_LIMIT_KALSHI: int = 30
    RATE_LIMIT_CRYPTO: int = 60
    RATE_LIMIT_BACKOFF_BASE: float = 2.0  # base multiplier for exponential backoff
    RATE_LIMIT_MAX_DELAY: float = 60.0  # maximum delay between retries
    # Circuit breaker thresholds (configurable per service)
    CB_FAILURE_THRESHOLD: int = 5  # failures before opening circuit
    CB_RECOVERY_TIMEOUT: float = 60.0  # seconds before attempting recovery
    CB_HALF_OPEN_MAX: int = 1  # max concurrent probes in half-open state

    # --------------------------------------------------------------------------
    # STRATEGY_PARAMS - Strategy-specific thresholds and limits
    # --------------------------------------------------------------------------
    # Trading parameters
    MIN_DEBATE_EDGE: float = 0.04  # debate threshold
    MIN_EDGE_THRESHOLD: float = 0.03  # minimum edge for signals
    MAX_ENTRY_PRICE: float = 0.80  # maximum entry price
    MAX_TRADES_PER_WINDOW: int = 20  # trades per scheduling window
    MAX_TRADES_PER_SCAN: int = 10  # trades per scan cycle
    AUTO_TRADER_BATCH_SIZE: int = 100  # batch size for auto-trader
    MAX_TOTAL_PENDING_TRADES: int = 50  # max pending trades
    STALE_TRADE_HOURS: int = 24  # hours before trade considered stale

    # Position sizing
    KELLY_FRACTION: float = 0.30  # Kelly fraction (0.30 = 30% Kelly)
    MAX_POSITION_FRACTION: float = 0.30  # max position as % of bankroll
    MAX_TOTAL_EXPOSURE_FRACTION: float = 0.70  # max total exposure
    CORRELATION_MULTIPLIER: float = (
        1.0  # same-category exposure multiplier (1.0=no inflation)
    )
    MAX_CORRELATED_EXPOSURE_PCT: float = (
        0.80  # max correlation-adjusted exposure % of bankroll
    )
    MAX_TRADE_SIZE: float = 100.0  # max single trade size in USD
    MIN_ORDER_USDC: float = 1.0  # minimum order size (live)
    PAPER_MIN_ORDER_USDC: float = (
        1.0  # minimum order size (paper — matches live to prevent hallucination)
    )

    # Confidence and signal weights
    AUTO_APPROVE_MIN_CONFIDENCE: float = float(
        os.getenv("AUTO_APPROVE_MIN_CONFIDENCE", "0.5")
    )
    PAPER_AUTO_APPROVE_MIN_CONFIDENCE: float = float(
        os.getenv("PAPER_AUTO_APPROVE_MIN_CONFIDENCE", "0.5")
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
    KILL_WIN_RATE: float = 0.05  # win rate below which strategy is auto-killed
    KILL_SHARPE: float = -2.0  # Sharpe ratio below which strategy is auto-killed
    KILL_DRAWDOWN: float = 0.50  # drawdown fraction above which strategy is auto-killed
    WARN_WIN_RATE: float = 0.15  # win rate below which strategy gets warning flag
    WARN_SHARPE: float = -1.0  # Sharpe below which strategy gets warning
    MIN_WARMUP_TRADES: int = 30  # trades before strategy governance activates
    DEGRADATION_WR_THRESHOLD: float = 0.35  # win rate drop triggering degradation review
    DEGRADATION_SHARPE_THRESHOLD: float = -0.5  # Sharpe drop triggering degradation review
    MAX_DEGRADATIONS_BEFORE_REVIEW: int = 2  # consecutive degradations before forced review
    REHAB_CATASTROPHIC_WR_FLOOR: float = 0.05  # min WR to enter strategy rehabilitation
    REHAB_CATASTROPHIC_MIN_TRADES: int = 30  # min trades before rehab evaluation
    STRATEGY_MIN_WIN_RATE: float = 0.45  # circuit breaker kill threshold per strategy
    STRATEGY_MIN_PNL_RATIO: float = 0.05  # circuit breaker PnL kill threshold
    STRATEGY_WINRATE_LOOKBACK_TRADES: int = 20  # trade lookback for WR calculation
    STRATEGY_PNL_LOOKBACK_DAYS: int = 30  # day lookback for PnL evaluation
    RISK_MAX_DAILY_LOSS_PER_STRATEGY_USD: float = 50.0  # hard-dollar daily stop per strategy
    RISK_MAX_TOTAL_DRAWDOWN_PCT: float = 10.0  # % of total balance drawdown limit
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

    # Risk config (canonical source)
    DEFAULT_KELLY_FRACTION: float = 0.25
    MAX_KELLY_FRACTION: float = 0.50
    DEFAULT_MAX_DAILY_LOSS_USD: float = 100.0
    DEFAULT_MAX_DRAWDOWN_PCT: float = 0.20
    TERMINAL_DRAWDOWN_PCT: float = 0.50
    DAILY_DRAWDOWN_LIMIT_PCT: float = 0.10  # max daily drawdown
    WEEKLY_DRAWDOWN_LIMIT_PCT: float = 0.20  # max weekly drawdown
    DAILY_LOSS_FLOOR_PCT: float = -0.10  # daily loss floor (auto-pause)
    WEEKLY_LOSS_FLOOR_PCT: float = -0.20  # weekly loss floor (revert to paper)
    MAX_STRATEGY_DRAWDOWN_PCT: float = (
        1.00  # per-strategy max drawdown (% of allocation)
    )
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
    BOND_SCANNER_MIN_PRICE: float = 0.90
    BOND_SCANNER_MAX_PRICE: float = 0.96
    BOND_SCANNER_MIN_DAYS_TO_RESOLUTION: float = 0.5
    BOND_SCANNER_KELLY_FRACTION: float = 0.15
    BOND_SCANNER_BANKROLL_PCT: float = 0.05
    BOND_SCANNER_MIN_EDGE: float = 0.05
    BOND_SCANNER_PROXIMITY_BOOST_SCALE: float = 0.01
    BOND_SCANNER_MAX_POSITION_SIZE: float = 5.0
    BOND_SCANNER_MAX_CONCURRENT_BONDS: int = 4
    BOND_SCANNER_MIN_VOLUME: int = 5000
    BOND_SCANNER_MAX_DAYS_TO_RESOLUTION: int = 14
    BOND_SCANNER_MIN_SIZE_USD: float = 5.0

    # BTC Oracle
    BTC_ORACLE_MIN_POSITION_USD: float = 1.0
    BTC_ORACLE_MAX_POSITION_USD: float = 50.0
    BTC_ORACLE_EDGE_SCALE_THRESHOLD: float = 0.10
    BTC_ORACLE_MIN_EDGE: float = 0.08  # raised from 0.03 — WR 40.7% loss-making, need stronger conviction
    BTC_ORACLE_INTERVAL_SECONDS: int = 30
    BTC_ORACLE_MAX_MINUTES_TO_RESOLUTION: int = 5

    # CEX PM Lead-Lag
    CEX_PM_LEADLAG_MIN_MOMENTUM: float = 0.001
    CEX_PM_LEADLAG_MIN_EDGE: float = 0.03
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
    CRYPTO_ORACLE_MIN_EDGE: float = 0.05
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

    # --------------------------------------------------------------------------
    # SYSTEM - Deployment and runtime settings
    # --------------------------------------------------------------------------
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./tradingbot.db")
    PARQUET_DIR: str = os.getenv("PARQUET_DIR", "data/parquet")
    POSTGRES_POOL_SIZE: int = 20
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

        if (
            self.DATABASE_URL.startswith("mysql://")
            and "+pymysql" not in self.DATABASE_URL
        ):
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
    POLYMARKET_SIGNATURE_TYPE: int = 1
    POLYMARKET_BUILDER_API_KEY: Optional[str] = None
    POLYMARKET_BUILDER_SECRET: Optional[str] = None
    POLYMARKET_BUILDER_PASSPHRASE: Optional[str] = None
    POLYMARKET_BUILDER_ADDRESS: Optional[str] = None
    POLYMARKET_WALLET_ADDRESS: Optional[str] = None
    POLYMARKET_RELAYER_API_KEY: Optional[str] = None
    POLYMARKET_RELAYER_API_KEY_ADDRESS: Optional[str] = None
    AUTO_REDEEM_ENABLED: bool = True
    AUTO_REDEEM_DRY_RUN: bool = True
    AUTO_REDEEM_INTERVAL_SECONDS: int = 3600
    AUTO_REDEEM_TIMEOUT_SECONDS: float = 120.0
    AUTO_REDEEM_DB_SCAN_ENABLED: bool = True
    KALSHI_API_KEY_ID: Optional[str] = None
    KALSHI_PRIVATE_KEY_PATH: Optional[str] = None
    KALSHI_ENABLED: bool = False
    PMXT_ENABLED: bool = False
    ADMIN_API_KEY: Optional[str] = None

    # Port and hosting
    PORT: int = 8100  # backend API port
    CORS_ORIGINS: str = (
        "http://localhost:5173,http://localhost:5174,http://127.0.0.1:5173,http://127.0.0.1:5174,https://polyedge.aitradepulse.com,http://polyedge.aitradepulse.com"
    )

    # Trading modes
    ACTIVE_MODES: str = "paper"
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
        0.03  # 3% profit target (must cover ~1% PM fee + 0.5% slippage)
    )
    AUTO_SELL_STOP_LOSS_PCT: float = 0.03  # 3% stop-loss
    AUTO_SELL_MAX_HOLD_SECONDS: int = 300  # 5 min max hold
    AUTO_SELL_INTERVAL_SECONDS: int = 30  # Check every 30s

    # --------------------------------------------------------------------------
    # POLLING - Interval settings for jobs and tasks
    # --------------------------------------------------------------------------
    # Scan intervals
    SCAN_INTERVAL_SECONDS: int = 120
    SETTLEMENT_INTERVAL_SECONDS: int = 120

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
    CROSSOVER_CYCLE_INTERVAL_HOURS: int = 168  # weekly
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
    AGI_REHAB_ALLOCATION_PCT: float = 0.25  # graduated rehab starting allocation
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
    FORENSICS_AUTO_MUTATE: bool = True
    FORENSICS_MAX_MUTATIONS_PER_DAY: int = 3
    AGI_SELF_TUNE_INTERVAL_MINUTES: int = 30
    AGI_SELF_TUNE_IN_PAPER: bool = True

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
    LLM_OPENAI_API_KEY: Optional[str] = None
    LLM_OPENAI_BASE_URL: Optional[str] = None
    LLM_OPENAI_MODEL: str = "auto/best-chat"

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
    INITIAL_BANKROLL: float = 1000.0
    PAPER_MIN_BANKROLL: float = 50.0

    # Genome strategy defaults
    GENOME_KELLY_FRACTION: float = 0.25
    GENOME_MAX_POSITION_FRACTION: float = 0.08
    GENOME_MAX_EXPOSURE_FRACTION: float = 0.70
    GENOME_MIN_CONFIDENCE: float = 0.50
    GENOME_BANKROLL: float = 1000.0
    GENOME_MAX_TRADE_SIZE: float = 100.0
    GENOME_CONFIDENCE_BASELINE: float = 0.5
    GENOME_MARKET_LIMIT: int = 50
    GENOME_TOP_MARKETS: int = 10

    # DB backup
    DB_BACKUP_RETENTION_DAYS: int = 30
    DB_BACKUP_MAX_BACKUPS: int = 100

    # Performance tracker
    PERF_TRACKER_MAX_RETRIES: int = 2
    PERF_TRACKER_RETRY_DELAY: float = 0.1
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
    EVOLUTION_BACKEND: str = "legacy"  # "deap" or "legacy"
    AGI_POPULATION_SIZE: int = 20
    AGI_MUTATION_RATE: float = 0.10
    GENOME_POPULATION_TARGET: int = 25
    DEAP_POPULATION_SIZE: int = 100
    DEAP_CROSSOVER_PROB: float = 0.7
    DEAP_MUTATION_PROB: float = 0.2
    DEAP_TOURNAMENT_SIZE: int = 3
    DEAP_GENERATIONS: int = 50
    DEAP_PARALLEL_WORKERS: int = 4
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
    CATEGORY_CONFIDENCE_MULTIPLIER: Dict[str, float] = field(
        default_factory=lambda: {
            "finance": 0.85,
            "politics": 0.95,
            "sports": 1.10,
            "crypto": 1.10,
            "weather": 1.15,
            "entertainment": 1.15,
        }
    )

    # --------------------------------------------------------------------------
    # EV_FILTERS - Expected value and longshot bias filters
    # --------------------------------------------------------------------------
    MIN_TRADE_EV: float = 0.10  # Minimum expected value ($0.10) to accept a trade
    LONGSHOT_YES_REJECT_PRICE: float = 0.30  # Reject YES trades below this price
    LONGSHOT_NO_BOOST_PRICE: float = 0.30  # Boost NO trades below this price

    # Category-specific minimum edge requirements (by efficiency)
    CATEGORY_MIN_EDGE: Dict[str, float] = field(
        default_factory=lambda: {
            "finance": 0.05,  # Nearly efficient — high bar
            "politics": 0.03,  # Moderate
            "sports": 0.02,  # Good target
            "crypto": 0.02,  # Good target
            "entertainment": 0.01,  # Highest edge opportunity
            "weather": 0.02,  # Good target
            "uncategorized": 0.03,  # Default
        }
    )

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
    TAKER_FEE_RATE: float = 0.01
    MIN_ARB_SPREAD: float = 0.005
    SSE_EVENT_TYPE_FILTER_ENABLED: bool = True

    # --------------------------------------------------------------------------
    # NEWS - News feed settings
    # --------------------------------------------------------------------------
    NEWS_FEED_ENABLED: bool = False
    RSS_FEEDS: str = (
        "https://feeds.bbci.co.uk/news/rss.xml,https://feeds.reuters.com/reuters/businessNews,https://www.federalreserve.gov/feeds/press_all.xml,https://cointelegraph.com/rss,https://coindesk.com/arc/outboundfeeds/rss/"
    )

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
    PAPER_SLIPPAGE_BPS_CONFIG: float = 20.0
    PAPER_RANDOM_SLIPPAGE_CONFIG: bool = True
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

        if not self.DATABASE_URL:
            issues.append("DATABASE_URL is required")

        if not self.GAMMA_API_URL:
            issues.append("GAMMA_API_URL is required")

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
            if url and not url.startswith(("http://", "https://", "wss://", "ws://")):
                issues.append(f"Invalid URL format: {url}")

        if self.RATE_LIMIT_GAMMA <= 0:
            issues.append("RATE_LIMIT_GAMMA must be positive")
        if self.RATE_LIMIT_KALSHI <= 0:
            issues.append("RATE_LIMIT_KALSHI must be positive")
        if self.RATE_LIMIT_CRYPTO <= 0:
            issues.append("RATE_LIMIT_CRYPTO must be positive")

        if self.RATE_LIMIT_BACKOFF_BASE < 1.0:
            issues.append("RATE_LIMIT_BACKOFF_BASE must be >= 1.0")
        if self.RATE_LIMIT_MAX_DELAY < self.RATE_LIMIT_BACKOFF_BASE:
            issues.append("RATE_LIMIT_MAX_DELAY must be >= RATE_LIMIT_BACKOFF_BASE")

        if self.PORT < 1 or self.PORT > 65535:
            issues.append(f"PORT must be between 1 and 65535, got {self.PORT}")

        risky_floats = [
            ("KELLY_FRACTION", self.KELLY_FRACTION, 0.0, 0.5),
            ("MAX_POSITION_FRACTION", self.MAX_POSITION_FRACTION, 0.0, 1.0),
            ("MAX_TOTAL_EXPOSURE_FRACTION", self.MAX_TOTAL_EXPOSURE_FRACTION, 0.0, 1.0),
            ("SLIPPAGE_TOLERANCE", self.SLIPPAGE_TOLERANCE, 0.0, 0.1),
            ("DAILY_DRAWDOWN_LIMIT_PCT", self.DAILY_DRAWDOWN_LIMIT_PCT, 0.0, 0.5),
            ("WEEKLY_DRAWDOWN_LIMIT_PCT", self.WEEKLY_DRAWDOWN_LIMIT_PCT, 0.0, 0.5),
            ("DAILY_LOSS_FLOOR_PCT", self.DAILY_LOSS_FLOOR_PCT, -0.5, 0.0),
            ("WEEKLY_LOSS_FLOOR_PCT", self.WEEKLY_LOSS_FLOOR_PCT, -0.5, 0.0),
            ("AI_SIGNAL_WEIGHT", self.AI_SIGNAL_WEIGHT, 0.0, 0.5),
            ("HFT_POSITION_SIZE_PCT", self.HFT_POSITION_SIZE_PCT, 0.01, 1.0),
            (
                "WEATHER_MAX_BANKROLL_FRACTION",
                self.WEATHER_MAX_BANKROLL_FRACTION,
                0.0,
                1.0,
            ),
            ("HFT_ARB_MIN_PROFIT", self.HFT_ARB_MIN_PROFIT, 0.0, 1.0),
            ("HFT_WHALE_MIN_SCORE", self.HFT_WHALE_MIN_SCORE, 0.0, 1.0),
            (
                "HFT_EXECUTION_AUTO_EXECUTE_MIN_CONFIDENCE",
                self.HFT_EXECUTION_AUTO_EXECUTE_MIN_CONFIDENCE,
                0.0,
                1.0,
            ),
        ]

        for name, value, min_val, max_val in risky_floats:
            if not (min_val <= value <= max_val):
                issues.append(
                    f"{name} must be between {min_val} and {max_val}, got {value}"
                )

        risky_ints = [
            ("HFT_MAX_POSITION_USD", self.HFT_MAX_POSITION_USD, 100, 100000),
            ("MAX_TRADES_PER_WINDOW", self.MAX_TRADES_PER_WINDOW, 1, 1000),
            ("MAX_TRADES_PER_SCAN", self.MAX_TRADES_PER_SCAN, 1, 1000),
            ("AUTO_TRADER_BATCH_SIZE", self.AUTO_TRADER_BATCH_SIZE, 1, 1000),
            ("MAX_TOTAL_PENDING_TRADES", self.MAX_TOTAL_PENDING_TRADES, 1, 1000),
            ("STALE_TRADE_HOURS", self.STALE_TRADE_HOURS, 1, 720),
            ("SCANNER_PAGE_SIZE", self.SCANNER_PAGE_SIZE, 100, 1000),
            ("SCANNER_SEMAPHORE_LIMIT", self.SCANNER_SEMAPHORE_LIMIT, 10, 100),
            ("SCANNER_MAX_MARKETS", self.SCANNER_MAX_MARKETS, 1000, 100000),
            ("MIN_TIME_REMAINING", self.MIN_TIME_REMAINING, 1, 3600),
            ("MAX_TIME_REMAINING", self.MAX_TIME_REMAINING, 60, 7200),
        ]

        for name, value, min_val, max_val in risky_ints:
            if not (min_val <= value <= max_val):
                issues.append(
                    f"{name} must be between {min_val} and {max_val}, got {value}"
                )

        if self.SCAN_INTERVAL_SECONDS < 5:
            issues.append(
                f"SCAN_INTERVAL_SECONDS too aggressive: {self.SCAN_INTERVAL_SECONDS}s (min: 5s)"
            )
        if self.SETTLEMENT_INTERVAL_SECONDS < 30:
            issues.append(
                f"SETTLEMENT_INTERVAL_SECONDS too aggressive: {self.SETTLEMENT_INTERVAL_SECONDS}s (min: 30s)"
            )

        if not self.WALLET_FERNET_KEY:
            issues.append(
                "WALLET_FERNET_KEY is empty — wallet encryption disabled: private keys stored in plaintext. This is safe for dev/paper-only but NOT for live production trading."
            )

        if self.HFT_SCANNER_CIRCUIT_BREAKER_THRESHOLD < 1:
            issues.append("HFT_SCANNER_CIRCUIT_BREAKER_THRESHOLD must be >= 1")
        if self.HFT_SCANNER_CIRCUIT_BREAKER_TIMEOUT < 1:
            issues.append("HFT_SCANNER_CIRCUIT_BREAKER_TIMEOUT must be >= 1s")

        if self.REGISTRY_MIN_WIN_RATE < 0 or self.REGISTRY_MIN_WIN_RATE > 1:
            issues.append(
                f"REGISTRY_MIN_WIN_RATE must be 0-1, got {self.REGISTRY_MIN_WIN_RATE}"
            )
        if self.REGISTRY_MIN_ROI < -1:
            issues.append(
                f"REGISTRY_MIN_ROI must be >= -1, got {self.REGISTRY_MIN_ROI}"
            )

        positive_ints = [
            ("SCAN_INTERVAL_SECONDS", self.SCAN_INTERVAL_SECONDS),
            ("SETTLEMENT_INTERVAL_SECONDS", self.SETTLEMENT_INTERVAL_SECONDS),
            ("AGI_PROMOTION_INTERVAL_HOURS", self.AGI_PROMOTION_INTERVAL_HOURS),
            (
                "AGI_HEALTH_CHECK_INTERVAL_MINUTES",
                self.AGI_HEALTH_CHECK_INTERVAL_MINUTES,
            ),
            ("JOB_TIMEOUT_SECONDS", self.JOB_TIMEOUT_SECONDS),
            ("MAX_CONCURRENT_JOBS", self.MAX_CONCURRENT_JOBS),
            ("DB_EXECUTOR_MAX_WORKERS", self.DB_EXECUTOR_MAX_WORKERS),
            (
                "AGI_CALIBRATION_CHECK_INTERVAL_HOURS",
                self.AGI_CALIBRATION_CHECK_INTERVAL_HOURS,
            ),
            ("AUTO_IMPROVE_INTERVAL_DAYS", self.AUTO_IMPROVE_INTERVAL_DAYS),
            ("SELF_REVIEW_INTERVAL_DAYS", self.SELF_REVIEW_INTERVAL_DAYS),
            ("RESEARCH_PIPELINE_INTERVAL_HOURS", self.RESEARCH_PIPELINE_INTERVAL_HOURS),
            (
                "AGI_IMPROVEMENT_CYCLE_INTERVAL_HOURS",
                self.AGI_IMPROVEMENT_CYCLE_INTERVAL_HOURS,
            ),
            (
                "HISTORICAL_DATA_COLLECTOR_INTERVAL_HOURS",
                self.HISTORICAL_DATA_COLLECTOR_INTERVAL_HOURS,
            ),
            ("ARBITRAGE_SCAN_INTERVAL_SECONDS", self.ARBITRAGE_SCAN_INTERVAL_SECONDS),
            ("NEWS_FEED_INTERVAL_SECONDS", self.NEWS_FEED_INTERVAL_SECONDS),
            ("AGI_MUTATION_INTERVAL_HOURS", self.AGI_MUTATION_INTERVAL_HOURS),
            ("AGI_CROSSOVER_INTERVAL_HOURS", self.AGI_CROSSOVER_INTERVAL_HOURS),
            ("MUTATION_CYCLE_INTERVAL_HOURS", self.MUTATION_CYCLE_INTERVAL_HOURS),
            ("CROSSOVER_CYCLE_INTERVAL_HOURS", self.CROSSOVER_CYCLE_INTERVAL_HOURS),
            ("NECROMANCY_INTERVAL_DAYS", self.NECROMANCY_INTERVAL_DAYS),
            ("AGI_REHAB_COOLDOWN_DAYS", self.AGI_REHAB_COOLDOWN_DAYS),
            ("AGI_REHAB_MIN_TRADES", self.AGI_REHAB_MIN_TRADES),
            ("AGI_PROMOTER_SHADOW_MIN_TRADES", self.AGI_PROMOTER_SHADOW_MIN_TRADES),
            ("AGI_PROMOTER_SHADOW_MIN_DAYS", self.AGI_PROMOTER_SHADOW_MIN_DAYS),
            ("AGI_PROMOTER_PAPER_MIN_TRADES", self.AGI_PROMOTER_PAPER_MIN_TRADES),
            ("AGI_PROMOTER_PAPER_MIN_DAYS", self.AGI_PROMOTER_PAPER_MIN_DAYS),
            ("AGI_FRONTTEST_DAYS", self.AGI_FRONTTEST_DAYS),
            ("AGI_FRONTTEST_MIN_TRADES", self.AGI_FRONTTEST_MIN_TRADES),
            ("AGI_MAX_IMPROVEMENT_ATTEMPTS", self.AGI_MAX_IMPROVEMENT_ATTEMPTS),
            ("AGI_DEMOTION_RETRY_LIMIT", self.AGI_DEMOTION_RETRY_LIMIT),
            ("AGI_LIVE_TRIAL_DAYS", self.AGI_LIVE_TRIAL_DAYS),
            ("AGI_LIVE_TRIAL_MIN_TRADES", self.AGI_LIVE_TRIAL_MIN_TRADES),
            ("AGI_REHAB_LITE_COOLDOWN_HOURS", self.AGI_REHAB_LITE_COOLDOWN_HOURS),
            ("AGI_REHAB_LITE_RE_DISABLE_HOURS", self.AGI_REHAB_LITE_RE_DISABLE_HOURS),
            ("AGI_AUTO_DISABLE_MIN_TRADES", self.AGI_AUTO_DISABLE_MIN_TRADES),
            ("CACHE_TTL_SECONDS", self.CACHE_TTL_SECONDS),
            ("DB_BACKUP_INTERVAL_HOURS", self.DB_BACKUP_INTERVAL_HOURS),
            ("DB_BACKUP_RETENTION_DAYS", self.DB_BACKUP_RETENTION_DAYS),
            (
                "HISTORICAL_DATA_COLLECTOR_INTERVAL_HOURS",
                self.HISTORICAL_DATA_COLLECTOR_INTERVAL_HOURS,
            ),
            ("AGI_HEALTH_ORPHAN_MAX_AGE_DAYS", self.AGI_HEALTH_ORPHAN_MAX_AGE_DAYS),
            ("MAX_TOPUPS", self.MAX_TOPUPS),
            ("DEBATE_CYCLE_TIMEOUT", self.DEBATE_CYCLE_TIMEOUT),
            ("ACTIVITY_DB_TRANSACTION_TIMEOUT", self.ACTIVITY_DB_TRANSACTION_TIMEOUT),
            ("WEBSOCKET_ACTIVITY_LATENCY_SLA", self.WEBSOCKET_ACTIVITY_LATENCY_SLA),
            ("PAPER_MIN_ORDER_USDC", self.PAPER_MIN_ORDER_USDC),
            ("MIN_ORDER_USDC", self.MIN_ORDER_USDC),
            ("SCANNER_MIN_EDGE", int(self.SCANNER_MIN_EDGE * 100)),
            (
                "SCANNER_STALE_THRESHOLD_SECONDS",
                int(self.SCANNER_STALE_THRESHOLD_SECONDS * 10),
            ),
            ("SCANNER_MAX_MARKETS", self.SCANNER_MAX_MARKETS),
        ]

        for name, value in positive_ints:
            if value < 1:
                issues.append(f"{name} must be >= 1, got {value}")

        positive_floats = [
            ("RATE_LIMIT_BACKOFF_BASE", self.RATE_LIMIT_BACKOFF_BASE),
            ("RATE_LIMIT_MAX_DELAY", self.RATE_LIMIT_MAX_DELAY),
            ("DEBATE_TIMEOUT_SECONDS", self.DEBATE_TIMEOUT_SECONDS),
            ("MIROFISH_API_TIMEOUT", self.MIROFISH_API_TIMEOUT),
            ("MIN_DEBATE_EDGE", self.MIN_DEBATE_EDGE),
            ("MIN_EDGE_THRESHOLD", self.MIN_EDGE_THRESHOLD),
            ("MAX_ENTRY_PRICE", self.MAX_ENTRY_PRICE),
            ("KELLY_FRACTION", self.KELLY_FRACTION),
            ("DAILY_LOSS_LIMIT", self.DAILY_LOSS_LIMIT),
            ("MAX_TRADE_SIZE", self.MAX_TRADE_SIZE),
            ("INITIAL_BANKROLL", self.INITIAL_BANKROLL),
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

    @property
    def TRADING_MODE(self) -> str:
        override = getattr(self, "_trading_mode_override", None)
        if override:
            return override
        env_val = os.environ.get("TRADING_MODE")
        if env_val:
            return env_val
        modes = self.active_modes_set
        if "live" in modes:
            return "live"
        if "testnet" in modes:
            return "testnet"
        return "paper"

    @TRADING_MODE.setter
    def TRADING_MODE(self, value: str) -> None:
        self._trading_mode_override = value

    @TRADING_MODE.deleter
    def TRADING_MODE(self) -> None:
        if hasattr(self, "_trading_mode_override"):
            del self._trading_mode_override

    @property
    def SIMULATION_MODE(self) -> bool:
        override = getattr(self, "_simulation_mode_override", None)
        if override is not None:
            return override
        return "live" not in self.active_modes_set

    @SIMULATION_MODE.setter
    def SIMULATION_MODE(self, value: bool) -> None:
        self._simulation_mode_override = value

    @SIMULATION_MODE.deleter
    def SIMULATION_MODE(self) -> None:
        if hasattr(self, "_simulation_mode_override"):
            del self._simulation_mode_override

    WALLET_FERNET_KEY: Optional[str] = None

    # --------------------------------------------------------------------------
    # MISSING FIELDS - Added for completeness
    # --------------------------------------------------------------------------
    WALLET_ENCRYPTION_KEY: str = ""
    WALLET_ROUTER_ENABLED: bool = True
    COPY_POLICY_ENABLED: bool = True
    AGI_NIGHTLY_REVIEW_OUTPUT_DIR: str = ".omc/nightly_review"
    AGI_NIGHTLY_REVIEW_LOOKBACK_DAYS: int = 7
    GEMINI_ENABLED: bool = False
    KALSHI_API_KEY: str = ""
    KALSHI_API_SECRET: str = ""
    RISK_PROFILE: str = "default"
    ORCHESTRATOR_STRATEGY_INTERVAL_SECONDS: Optional[int] = None  # set by apply_profile()
    WALLET_PRIVATE_KEY: str = ""
    WALLET_ADDRESS: str = ""
    SAFETY_MAX_POSITION_SIZE: float = 0.1
    SAFETY_MAX_DAILY_LOSS: float = 0.05
    SAFETY_MIN_CONFIDENCE: float = 0.6


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

# Log missing optional API keys
for _key in ["ANTHROPIC_API_KEY", "EXA_API_KEY", "SERPER_API_KEY"]:
    if not getattr(settings, _key, None):
        logger.debug(f"[Config] {_key} not set — fallback provider disabled")


if __name__ == "__main__":
    issues = settings.validate()
    if issues:
        print("Configuration validation errors:")
        for issue in issues:
            print(f"  - {issue}")
        raise ValueError(f"Configuration validation failed: {issues[:3]}")

    print("PolyEdge Configuration Loaded Successfully")
    print(f"  Trading mode: {settings.TRADING_MODE}")
    print(f"  Bankroll: ${settings.INITIAL_BANKROLL:.2f}")
    print(
        f"  API endpoints configured: {len([k for k in dir(settings) if k.endswith('_URL') and not k.startswith('_')])}"
    )
    print(f"  Jobs enabled: {settings.JOB_WORKER_ENABLED}")
    print(f"  AGI autonomy: {settings.AGI_AUTO_PROMOTE}")
