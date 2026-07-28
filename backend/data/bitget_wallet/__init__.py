"""Bitget Wallet Web3 data providers — plugin-based token discovery & market data.

Follows the same provider/plugin pattern as ``crypto_feeds/``.
"""

from backend.data.bitget_wallet.base import (
    BaseBitgetWalletProvider,
    BitgetWalletManifest,
)
from backend.data.bitget_wallet.registry import (
    BitgetWalletRegistry,
    get_registry,
    reset_registry,
)

__all__ = [
    "BaseBitgetWalletProvider",
    "BitgetWalletManifest",
    "BitgetWalletRegistry",
    "get_registry",
    "reset_registry",
]
import backend.data.bitget_wallet.providers  # noqa: F401 — triggers @registry.plugin
