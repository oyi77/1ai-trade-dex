"""CLOB factory — create PolymarketCLOB from settings."""

from typing import Optional

from .client import PolymarketCLOB


def clob_from_settings(mode: Optional[str] = None) -> PolymarketCLOB:
    """Create PolymarketCLOB from app settings.

    Args:
        mode: Trading mode override (paper/testnet/live). If None, uses settings.TRADING_MODE.

    Returns:
        PolymarketCLOB instance configured for the specified mode.
    """
    from backend.config import settings

    effective_mode = mode or settings.TRADING_MODE

    return PolymarketCLOB(
        private_key=settings.POLYMARKET_PRIVATE_KEY,
        api_key=settings.POLYMARKET_API_KEY,
        api_secret=settings.POLYMARKET_API_SECRET,
        api_passphrase=settings.POLYMARKET_API_PASSPHRASE,
        mode=effective_mode,
        builder_api_key=settings.POLYMARKET_BUILDER_API_KEY,
        builder_secret=settings.POLYMARKET_BUILDER_SECRET,
        builder_passphrase=settings.POLYMARKET_BUILDER_PASSPHRASE,
        builder_address=settings.POLYMARKET_BUILDER_ADDRESS,
        signature_type=settings.POLYMARKET_SIGNATURE_TYPE,
    )
