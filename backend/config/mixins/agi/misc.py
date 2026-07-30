"""AGI misc mixin — bot state, trading, evolution engine, MiroFish, alerts, EV filters, news, TWAK, and remaining fields."""
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class AGIMiscMixin:
    """Miscellaneous AGI settings: bot state, trading, jobs, evolution, MiroFish, alerts, EV filters, news, TWAK, and more."""

    # Bot state and trading
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

    # DB backup (deduplicated — only first occurrence kept)
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

    # MiroFish - External signal API
    MIROFISH_ENABLED: bool = True
    MIROFISH_API_TIMEOUT: float = 10.0
    ACTIVITY_LOG_RETENTION_DAYS: int = 90
    PROPOSAL_APPROVAL_REQUIRED: bool = True
    PROPOSAL_EXECUTION_TIMEOUT: int = 5
    DEBATE_CYCLE_TIMEOUT: int = 30
    ACTIVITY_DB_TRANSACTION_TIMEOUT: int = 3
    WEBSOCKET_ACTIVITY_LATENCY_SLA: int = 500

    # Alerts — webhook notifications
    SLACK_WEBHOOK_URL: Optional[str] = None
    DISCORD_WEBHOOK_URL: Optional[str] = None

    # BTC-specific settings
    BTC_PRICE_SOURCE: str = "coinbase"

    # Token contract addresses (documented for clarity)
    USDC_E_ADDRESS_TOKENS: str = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
    USDC_NATIVE_ADDRESS_TOKENS: str = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
    PUSD_ADDRESS_TOKENS: str = "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb"

    # Category-specific confidence multipliers
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

    # EV filters — expected value and longshot bias filters
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

    # News feed settings
    NEWS_FEED_ENABLED: bool = False
    RSS_FEEDS: str = (
        "https://feeds.bbci.co.uk/news/rss.xml,https://feeds.reuters.com/reuters/businessNews,https://www.federalreserve.gov/feeds/press_all.xml,https://cointelegraph.com/rss,https://coindesk.com/arc/outboundfeeds/rss/"
    )

    # AGI health check parameters
    AGI_HEALTH_STALE_STRATEGY_HOURS: float = 2.0
    AGI_HEALTH_DATA_FRESHNESS_HOURS: float = 24.0
    AGI_HEALTH_BUDGET_NEAR_LIMIT_PCT: float = 0.8
    AGI_HEALTH_ORPHAN_MAX_AGE_DAYS: int = 7

    # Additional fields from the end of ConfigRegistry
    WALLET_FERNET_KEY: Optional[str] = None

    # TWAK (Trust Wallet Agent Kit) — shared with Track 1 agent endpoints
    TWAK_WALLET_ADDRESS: str = ""
    TWAK_WALLET_PASSWORD: str = ""
    TWAK_ACCESS_ID: str = ""
    TWAK_HMAC_SECRET: str = ""
    ALCHEMY_API_KEY: str = ""  # WARNING: Must be set for whale tracker to work
    WHALE_WALLETS: str = "0xf8831548531d56ad6a4331493243c447a827cd1f"
    COPY_TRADER_MIN_PNL: int = 10000
    COPY_TRADER_MIN_VOLUME: int = 100000

    # Missing fields — added for completeness
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
