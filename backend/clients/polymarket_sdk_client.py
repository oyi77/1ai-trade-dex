"""Thin wrapper around the polymarket-sdk for future use.

This module provides a configured client for the official Polymarket SDK.
It does NOT replace existing CLOB/Gamma clients — it's available for future
migration or feature use.
"""

import os
from typing import Optional

from loguru import logger


class PolymarketSDKClient:
    """Wrapper around polymarket-sdk providing a configured client.

    Usage:
        client = PolymarketSDKClient()
        client.configure()
        # Use client.sdk for SDK operations
    """

    def __init__(self):
        self.sdk = None
        self._configured = False

    def configure(
        self,
        private_key: Optional[str] = None,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        api_passphrase: Optional[str] = None,
        chain_id: int = 137,
    ) -> None:
        """Configure the Polymarket SDK client.

        Args:
            private_key: Ethereum private key (hex, no 0x prefix).
            api_key: Polymarket API key.
            api_secret: Polymarket API secret.
            api_passphrase: Polymarket API passphrase.
            chain_id: Polygon chain ID (137=mainnet, 80001=testnet).
        """
        try:
            from polymarket_sdk import PolymarketSDK

            self.sdk = PolymarketSDK(
                private_key=private_key or os.environ.get("POLYMARKET_PRIVATE_KEY", ""),
                api_key=api_key or os.environ.get("POLYMARKET_API_KEY", ""),
                api_secret=api_secret or os.environ.get("POLYMARKET_API_SECRET", ""),
                passphrase=api_passphrase or os.environ.get("POLYMARKET_API_PASSPHRASE", ""),
                chain_id=chain_id,
            )
            self._configured = True
            logger.info("PolymarketSDK client configured (chain_id={})", chain_id)
        except ImportError:
            logger.warning("polymarket-sdk not installed — SDK client unavailable")
        except Exception as e:
            logger.error("PolymarketSDK configuration failed: {}", e)

    @property
    def is_available(self) -> bool:
        return self._configured and self.sdk is not None


# Module-level singleton
_sdk_client: Optional[PolymarketSDKClient] = None


def get_sdk_client() -> PolymarketSDKClient:
    """Get or create the module-level SDK client singleton."""
    global _sdk_client
    if _sdk_client is None:
        _sdk_client = PolymarketSDKClient()
    return _sdk_client
