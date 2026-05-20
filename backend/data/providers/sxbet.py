"""SXBetProvider — DataProvider implementation for sx.bet.

sx.bet is a peer-to-peer decentralized sports prediction market on Polygon.

REST API:  https://api.sx.bet
- Public reads (sports, leagues, fixtures, markets, orders) require NO auth.
- Order placement requires EIP-712 wallet signature (Polygon mainnet).

Config is read from the ``provider_credentials`` DB table via
:class:`~backend.core.provider_config_store.ProviderConfigStore`, with ENV
var fallback using the convention ``SXBET_{KEY_UPPER}``.
"""

from __future__ import annotations

from typing import Optional

import httpx
from loguru import logger

from backend.core.provider_config_store import provider_config
from backend.data.provider import DataProvider, MarketEntry, PositionEntry, BalanceInfo

_SXBET_API_DEFAULT = "https://api.sx.bet"


class SXBetProvider(DataProvider):
    """DataProvider for sx.bet P2P sports prediction market."""

    def __init__(self) -> None:
        self._base_url = provider_config.get(
            "sxbet", "api_url", _SXBET_API_DEFAULT
        ).rstrip("/")

    @property
    def platform_name(self) -> str:
        return "sxbet"

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self._base_url}/sports")
                return resp.status_code == 200
        except Exception:
            logger.debug("SXBet health check failed")
            return False

    async def get_markets(
        self, category: Optional[str] = None, limit: int = 200
    ) -> list[MarketEntry]:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                params: dict = {}
                resp = await client.get(
                    f"{self._base_url}/markets/active",
                    params=params,
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("SXBetProvider.get_markets failed: {}", exc)
            return []

        raw_markets = data if isinstance(data, list) else data.get("data", [])
        entries: list[MarketEntry] = []
        for m in raw_markets[:limit]:
            # SX.bet markets have marketHash as the unique ID
            market_hash = m.get("marketHash") or m.get("gameId") or ""
            outcome_names: list = m.get("outcomeNames", [])
            question = (
                " vs ".join(outcome_names) if outcome_names else m.get("label", "")
            )

            # SX.bet uses decimal odds in the moneyline format
            odds = m.get("homeOdds", m.get("impliedOdds", 2.0))
            try:
                implied_prob = round(1.0 / float(odds), 4) if float(odds) > 0 else 0.5
            except (TypeError, ZeroDivisionError):
                implied_prob = 0.5

            entries.append(
                MarketEntry(
                    ticker=market_hash,
                    question=question,
                    market_id=market_hash,
                    platform="sxbet",
                    current_price=implied_prob,
                    volume_24h=float(m.get("volume", 0.0)),
                    liquidity=0.0,
                    created_at=m.get("gameTime", ""),
                )
            )
        return entries

    async def get_orderbook(self, market_id: str) -> dict:
        """Fetch active maker orders for a given market hash."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{self._base_url}/orders",
                    params={"marketHashes": market_id},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("SXBetProvider.get_orderbook failed: {}", exc)
            return {"bids": [], "asks": [], "market_id": market_id}

        orders = data if isinstance(data, list) else data.get("data", [])
        bids = [o for o in orders if o.get("makerDirection") == "BUY"]
        asks = [o for o in orders if o.get("makerDirection") == "SELL"]
        return {"bids": bids, "asks": asks, "market_id": market_id, "platform": "sxbet"}

    async def get_positions(self) -> list[PositionEntry]:
        """Fetch open maker orders for own wallet (proxy for positions)."""
        wallet = provider_config.get("sxbet", "wallet_address")
        if not wallet:
            return []
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{self._base_url}/orders",
                    params={"maker": wallet},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("SXBetProvider.get_positions failed: {}", exc)
            return []

        orders = data if isinstance(data, list) else data.get("data", [])
        return [
            PositionEntry(
                market_id=o.get("marketHash", ""),
                side=o.get("makerDirection", ""),
                size=float(o.get("stakeAmount", 0.0)),
                entry_price=float(o.get("percentageOdds", 0.5)),
                current_price=float(o.get("percentageOdds", 0.5)),
                unrealized_pnl=0.0,
            )
            for o in orders
        ]

    async def get_balance(self) -> BalanceInfo:
        raise RuntimeError(
            "SX.bet provider does not support balance queries — use markets/providers/ instead"
        )

    async def place_order(
        self, market_id: str, side: str, size: float, price: float, **kwargs
    ) -> dict:
        """Place a maker order via EIP-712 signed payload.

        private_key is read from kwargs → DB (is_secret=True) → ENV fallback.
        Full EIP-712 signing is planned in plugin-system task 26e.
        """
        raise RuntimeError(
            "SX.bet provider does not support order placement — use markets/providers/ instead"
        )

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open maker order.

        SX.bet allows makers to cancel unfilled orders.
        Full implementation planned in plugin-system task 26e.
        """
        raise RuntimeError(
            "SX.bet provider does not support order cancellation — use markets/providers/ instead"
        )
