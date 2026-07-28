"""Base classes for Bitget Wallet Web3 data providers.

Follows the same provider/plugin pattern as crypto_feeds/base.py.
Each provider wraps Bitget Wallet Web3 API endpoints behind a common
interface for token discovery, price data, rankings, security audits,
and liquidity info.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class BitgetWalletManifest:
    """Static metadata for a Bitget Wallet Web3 provider."""

    name: str
    display_name: str
    version: str
    base_url: str
    required_env_vars: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)


class BaseBitgetWalletProvider(ABC):
    """Abstract base class for Bitget Wallet Web3 data providers.

    Each concrete provider implements the Bitget Wallet Web3 REST API
    behind this interface. Plugins are registered via ``BitgetWalletRegistry``
    and auto-discovered at startup.
    """

    @classmethod
    @abstractmethod
    def manifest(cls) -> BitgetWalletManifest:
        """Return the provider's static metadata."""

    # ------------------------------------------------------------------
    # Token discovery
    # ------------------------------------------------------------------
    @abstractmethod
    async def get_token_list(
        self, chain: str = "", limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Return a list of tokens, optionally filtered by chain.

        Each item contains at minimum: token_address, symbol, name, chain.
        """

    @abstractmethod
    async def get_token_rankings(
        self, sort_by: str = "volume", limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Return token rankings (e.g. volume, market-cap, trending)."""

    # ------------------------------------------------------------------
    # Price / K-line data
    # ------------------------------------------------------------------
    @abstractmethod
    async def get_kline(
        self,
        token_address: str,
        chain: str,
        resolution: str = "1H",
        limit: int = 100,
    ) -> Optional[List[Dict[str, Any]]]:
        """Return OHLCV kline data for a token."""

    # ------------------------------------------------------------------
    # Security / risk
    # ------------------------------------------------------------------
    @abstractmethod
    async def get_security_audit(
        self, token_address: str, chain: str
    ) -> Optional[Dict[str, Any]]:
        """Return security audit info for a token.

        Includes: rug-pull risk score, holder concentration, liquidity lock,
        honeypot detection, etc.
        """

    @abstractmethod
    async def get_token_liquidity(
        self, token_address: str, chain: str
    ) -> Optional[Dict[str, Any]]:
        """Return liquidity info: DEX pairs, TVL, depth, pool addresses."""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def health_check(self) -> bool:
        """Verify connectivity — override in subclass with a lightweight call."""
        try:
            result = await self.get_token_list(limit=1)
            return isinstance(result, list)
        except Exception:
            return False

    async def teardown(self) -> None:
        """Cleanup hook (override if the provider holds connections)."""
        pass
