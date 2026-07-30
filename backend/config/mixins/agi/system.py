"""AGI system mixin — deployment, runtime, API keys, platform wallets, websocket, telegram."""
import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class AGISystemMixin:
    """System-level settings: DB, API keys, platform wallets, port, logging, WS, Telegram."""

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
