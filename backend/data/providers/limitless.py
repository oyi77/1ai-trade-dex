"""LimitlessProvider — DISABLED 2026-05-30.

Smart wallet 0x671cE not deployed on Base — impossible to trade.
Stale bytecode was loading old version with "args should not exist" errors.
File kept for reference; re-enable when wallet is deployed.
"""

from __future__ import annotations

_DISABLED_MSG = "Limitless disabled — smart wallet 0x671cE not deployed on Base"


class LimitlessProvider:
    """DISABLED: Limitless Exchange is unavailable until smart wallet is deployed."""

    def __init__(self, *args, **kwargs) -> None:
        raise RuntimeError(_DISABLED_MSG)

    @property
    def platform_name(self) -> str:
        raise RuntimeError(_DISABLED_MSG)

    async def health_check(self) -> bool:
        raise RuntimeError(_DISABLED_MSG)

    async def get_markets(self, *args, **kwargs):
        raise RuntimeError(_DISABLED_MSG)

    async def get_orderbook(self, *args, **kwargs):
        raise RuntimeError(_DISABLED_MSG)

    async def get_positions(self, *args, **kwargs):
        raise RuntimeError(_DISABLED_MSG)

    async def get_balance(self, *args, **kwargs):
        raise RuntimeError(_DISABLED_MSG)

    async def place_order(self, *args, **kwargs):
        raise RuntimeError(_DISABLED_MSG)

    async def cancel_order(self, *args, **kwargs):
        raise RuntimeError(_DISABLED_MSG)
