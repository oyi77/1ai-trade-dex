"""Blockchain mixin — Polygon RPC, chain config, token addresses, caching."""
from dataclasses import dataclass


@dataclass
class BlockchainMixin:
    """Blockchain settings: Polygon RPC URLs, chain config, token addresses, caching."""

    # Polygon RPC URLs (moved from web/AI section)
    POLYGON_RPC_URL: str = "https://polygon-bor-rpc.publicnode.com"
    POLYGON_PRIVATE_MEMPOOL_URL: str = "https://polygon-bor-rpc.publicnode.com"

    # Blockchain
    POLYGON_AMOY_RPC: str = "https://rpc-amoy.polygon.technology"
    POLYGON_AMOY_CHAIN_ID: int = 80002
    POLYGON_WS_URL: str = "wss://polygon-rpc.com"
    CONDITIONAL_TOKENS_ADDRESS: str = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
    QUICKNODE_RPC_URL: str = "https://rpc-mainnet.matic.quiknode.pro"

    # Token addresses
    USDC_E_ADDRESS: str = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
    USDC_NATIVE_ADDRESS: str = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
    PUSD_ADDRESS: str = "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb"

    # Database / caching
    CACHE_URL: str = "sqlite:///./cache.db"
    CACHE_TTL_SECONDS: int = 300
    REDIS_DEFAULT_URL: str = "redis://localhost:6379"
    REDIS_URL: str = "redis://localhost:6379"
    REDIS_ENABLED: bool = False
