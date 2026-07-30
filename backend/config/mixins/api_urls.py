"""API URLs mixin — external API endpoints and rate limits."""

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class APIUrlsMixin:
    """External API URLs, WebSocket endpoints, and rate limit settings."""

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
    MARKET_PROVIDERS: dict = field(
        default_factory=lambda: {
            "polymarket": {
                "enabled": True,
                "priority": 1,
                "api_url": os.getenv(
                    "POLYMARKET_API_URL", "https://clob.polymarket.com"
                ),
            },
            "kalshi": {
                "enabled": False,
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
    COINMARKETCAP_API_URL: str = "https://pro-api.coinmarketcap.com"
    # Bitget Wallet Web3 API
    BITGET_WALLET_API_URL: str = "https://api-web3.bitget.com"
    COINMARKETCAP_SANDBOX_URL: str = "https://sandbox-api.coinmarketcap.com"

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
    RSS_FEED_BBC_URL: str = "https://feeds.bbci.co.uk/news/rss.xml"
    RSS_FEED_COINDESK_URL: str = "https://coindesk.com/arc/outboundfeeds/rss/"
    RSS_FEED_REUTERS_URL: str = "https://feeds.reuters.com/reuters/businessNews"
    RSS_FEED_FED_URL: str = "https://www.federalreserve.gov/feeds/press_all.xml"
    RSS_FEED_COINTELEGRAPH_URL: str = "https://cointelegraph.com/rss"

    # NOAA Weather APIs
    NOAA_METAR_URL: str = "https://aviationweather.gov/api/data/metar"

    # Azuro Protocol subgraph
    AZURO_SUBGRAPH_URL: str = (
        "https://thegraph.azuro.org/subgraphs/name/azuro-protocol/azuro-api-gnosis-v3"
    )

    # The Graph gateway for Polymarket subgraph
    THEGRAPH_GATEWAY_URL: str = "https://gateway.thegraph.com/api/"

    # Dune Analytics API
    DUNE_API_URL: str = "https://api.dune.com/api/v1"

    # Hyperliquid API
    HYPERLIQUID_API_URL: str = "https://api.hyperliquid.xyz"
    HYPERLIQUID_WS_URL: str = "wss://api.hyperliquid.xyz/ws"

    # Blockscout explorer API (Polygon)
    BLOCKSCOUT_API_URL: str = "https://polygon.blockscout.com/api/v2"

    # HuggingFace datasets-server API
    HF_DATASETS_SERVER_URL: str = "https://datasets-server.huggingface.co/rows"

    # --------------------------------------------------------------------------
    # RATE_LIMITS - Rate limit settings for API services
    # --------------------------------------------------------------------------
    RATE_LIMIT_GAMMA: int = 100  # requests per minute
    RATE_LIMIT_KALSHI: int = 30
    RATE_LIMIT_CRYPTO: int = 60
    RATE_LIMIT_BACKOFF_BASE: float = 2.0  # base multiplier for exponential backoff
    RATE_LIMIT_MAX_DELAY: float = 60.0  # maximum delay between retries
    # Circuit breaker thresholds (configurable per service)
    CB_FAILURE_THRESHOLD: int = 20  # failures before opening circuit (increased from 5 to handle auto_sell burst)
    CB_RECOVERY_TIMEOUT: float = 30.0  # seconds before attempting recovery (reduced from 60 for faster recovery)
    CB_HALF_OPEN_MAX: int = 3  # max concurrent probes in half-open state (increased from 1)
