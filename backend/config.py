"""Configuration settings for the BTC 5-min trading bot."""

import os
import logging
from pydantic import model_validator, field_validator, ConfigDict
from pydantic_settings import BaseSettings
from typing import Optional

logger = logging.getLogger(__name__)

# Project root directory
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT_DIR, "tradingbot.db")

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
    POSTGRES_POOL_SIZE: int = 10
    POSTGRES_MAX_OVERFLOW: int = 20
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
    SCAN_INTERVAL_SECONDS: int = 10  # Scan every 10 seconds
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
    JOB_WORKER_ENABLED: bool = False  # Phase 1: disabled by default
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
    AGI_LIVE_TRIAL_BANKROLL_PCT: float = 0.01  # 1% bankroll during live trial
    AGI_LIVE_TRIAL_DAYS: int = 7  # minimum trial period before full promotion
    AGI_LIVE_TRIAL_MIN_TRADES: int = 10
    AGI_DEMOTION_RETRY_LIMIT: int = 3  # max improvement cycles before permanent retirement
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
    POLYMARKET_WS_WHALE_URL: str = "wss://ws.polymarket.com/whale"
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
        import logging

        _logger = logging.getLogger("trading_bot.config")
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
                    _logger.warning(
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


    model_config = ConfigDict(env_file=".env", extra="ignore")


settings = Settings()
