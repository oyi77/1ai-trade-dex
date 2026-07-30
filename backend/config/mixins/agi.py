"""AGI/System/Bot mixin — system settings, AGI, polling, web, AI, blockchain, database, bot, and all remaining config."""

import os
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class AGIMixin:
    """System, AGI, polling, web, AI, blockchain, database, bot, and remaining settings."""

    # --------------------------------------------------------------------------
    # SYSTEM - Deployment and runtime settings
    # --------------------------------------------------------------------------
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./tradingbot.db")
    PARQUET_DIR: str = os.getenv("PARQUET_DIR", "data/parquet")
    POSTGRES_POOL_SIZE: int = 20
    POSTGRES_MAX_OVERFLOW: int = 20
    POSTGRES_POOL_TIMEOUT: int = 30
    POSTGRES_POOL_RECYCLE: int = 300  # recycle connections every 5min to prevent idle-in-transaction leaks
    POSTGRES_SSL_MODE: str = "prefer"

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
    # ── Bitget Wallet Web3 API ──────────────────────────────
    BITGET_WALLET_API_KEY: str = ""
    BITGET_WALLET_API_SECRET: str = ""
    BITGET_WALLET_API_PASSPHRASE: str = ""
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

    # Platform wallet credentials
    WALLET_PUBLIC_ADDRESS: Optional[str] = None
    HYPERLIQUID_PRIVATE_KEY: Optional[str] = None
    HYPERLIQUID_WALLET_ADDRESS: Optional[str] = None
    ASTER_PRIVATE_KEY: Optional[str] = None
    ASTER_WALLET_ADDRESS: Optional[str] = None
    LIGHTER_PRIVATE_KEY: Optional[str] = None
    LIGHTER_ACCOUNT_INDEX: str = "0"
    LIGHTER_API_KEY_INDEX: str = "2"
    OSTIUM_PRIVATE_KEY: Optional[str] = None
    OSTIUM_RPC_URL: str = "https://rpc.arbitrum.one"
    MYRIAD_API_URL: str = "https://api.myriad.markets"
    MYRIAD_WALLET_ADDRESS: Optional[str] = None
    MYRIAD_PRIVATE_KEY: Optional[str] = None
    MYRIAD_ENABLED: bool = False
    SXBET_WALLET_ADDRESS: Optional[str] = None
    SXBET_ENABLED: bool = False
    AZURO_GRAPH_URL: str = "https://thegraph.azuro.org/subgraphs/name/azuro-protocol/azuro-api-gnosis-v3"
    AZURO_RPC_URL: str = "https://rpc.gnosischain.com"
    AZURO_CHAIN_ID: int = 100
    AZURO_CACHE_TTL_SECONDS: int = 60
    AZURO_WALLET_ADDRESS: Optional[str] = None
    AZURO_LP_ADDRESS: Optional[str] = None
    AZURO_LP_ABI_PATH: Optional[str] = None
    GOLDSKY_API_URL: Optional[str] = None

    # Platform balance sync
    PLATFORM_BALANCE_SYNC_INTERVAL_SECONDS: int = 120
    PLATFORM_BALANCE_SYNC_ENABLED: bool = True
    BALANCE_POLL_INTERVAL_SECONDS: int = 30  # polling interval for venues without WebSocket

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
    API_REQUEST_TIMEOUT: float = 15.0
    DATABASE_QUERY_TIMEOUT: float = 10.0
    EXTERNAL_API_TIMEOUT: float = 15.0
    WS_HANDLER_TIMEOUT_MS: int = 100

    # Telegram
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_ADMIN_CHAT_IDS: str = ""
    TELEGRAM_HIGH_CONFIDENCE_ALERTS: bool = True

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
    AGI_AUTO_PROMOTE: bool = True
    AGI_AUTO_ENABLE: bool = True
    AGI_STRATEGY_HEALTH_ENABLED: bool = True
    AGI_HEALTH_CHECK_ENABLED: bool = True
    AGI_REHABILITATION_ENABLED: bool = True
    AGI_BANKROLL_ALLOCATION_ENABLED: bool = True
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
    AGI_AUTO_DISABLE_MIN_TRADES: int = 5
    AGI_AUTO_DISABLE_MIN_TRADES_LIFETIME: int = 20

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
    # NEWS - News feed settings
    # --------------------------------------------------------------------------
    NEWS_FEED_ENABLED: bool = False
    RSS_FEEDS: str = (
        "https://feeds.bbci.co.uk/news/rss.xml,https://feeds.reuters.com/reuters/businessNews,https://www.federalreserve.gov/feeds/press_all.xml,https://cointelegraph.com/rss,https://coindesk.com/arc/outboundfeeds/rss/"
    )

    # --------------------------------------------------------------------------
    # AGI_HEALTH - AGI health check parameters
    # --------------------------------------------------------------------------
    AGI_HEALTH_STALE_STRATEGY_HOURS: float = 2.0
    AGI_HEALTH_DATA_FRESHNESS_HOURS: float = 24.0
    AGI_HEALTH_BUDGET_NEAR_LIMIT_PCT: float = 0.8
    AGI_HEALTH_ORPHAN_MAX_AGE_DAYS: int = 7

    # Additional fields from the end of ConfigRegistry
    WALLET_FERNET_KEY: Optional[str] = None

    # --------------------------------------------------------------------------
    # TWAK (Trust Wallet Agent Kit) — shared with Track 1 agent endpoints
    # --------------------------------------------------------------------------
    TWAK_WALLET_ADDRESS: str = ""
    TWAK_WALLET_PASSWORD: str = ""
    TWAK_ACCESS_ID: str = ""
    TWAK_HMAC_SECRET: str = ""
    ALCHEMY_API_KEY: str = ""  # WARNING: Must be set for whale tracker to work
    WHALE_WALLETS: str = "0xf8831548531d56ad6a4331493243c447a827cd1f"
    COPY_TRADER_MIN_PNL: int = 10000
    COPY_TRADER_MIN_VOLUME: int = 100000

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
    ORCHESTRATOR_STRATEGY_INTERVAL_SECONDS: Optional[int] = (
        None  # set by apply_profile()
    )
    WALLET_PRIVATE_KEY: str = ""
    WALLET_ADDRESS: str = ""
    SAFETY_MAX_POSITION_SIZE: float = 0.1
    SAFETY_MAX_DAILY_LOSS: float = 0.05
    SAFETY_MIN_CONFIDENCE: float = 0.6
