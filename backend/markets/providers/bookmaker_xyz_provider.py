"""bookmaker.xyz market provider — powered by Azuro Protocol."""

import os
from decimal import Decimal
from backend.markets.base_provider import (
    BaseMarketProvider,
    MarketProviderManifest,
    NormalizedOrder,
    NormalizedOrderResult,
    NormalizedBalance,
    NormalizedPosition,
    VenueCapability,
)
from backend.markets.order_types import MarketInfo, OrderStatus
from backend.markets.provider_registry import market_registry
from loguru import logger

try:
    from backend.clients.azuro_client import AzuroClient

    HAS_AZURO = True
except ImportError:
    HAS_AZURO = False


@market_registry.plugin
class BookmakerXYZProvider(BaseMarketProvider):
    """bookmaker.xyz market provider plugin using Azuro Protocol."""

    def __init__(self, paper_mode: bool = False):
        super().__init__(paper_mode=paper_mode)
        if not HAS_AZURO:
            raise ImportError("AzuroClient required for BookmakerXYZProvider")
        self._client = AzuroClient()

    @classmethod
    def manifest(cls) -> MarketProviderManifest:
        return MarketProviderManifest(
            name="bookmaker_xyz",
            display_name="bookmaker.xyz",
            version="1.0.0",
            venue_type="sports_prediction",
            capabilities=[VenueCapability.MARKET_ORDERS, VenueCapability.MARKET_SEARCH],
            supported_currencies=["USDC"],
            required_env_vars=["AZURO_GRAPH_URL", "AZURO_RPC_URL"],
            supports_paper_mode=True,
            is_live_venue=True,
            min_order_size_usd=1.0,
            tags=["azuro", "sports"],
        )

    async def place_order(self, order: NormalizedOrder) -> NormalizedOrderResult:
        """Place an order on bookmaker.xyz."""
        if self._paper_mode:
            return NormalizedOrderResult(
                venue_order_id=f"paper_{order.market_id}",
                client_order_id=order.client_order_id,
                status=OrderStatus.FILLED,
                filled_size=order.size,
                filled_avg_price=order.price or Decimal("0.5"),
                remaining_size=Decimal("0"),
                fees_paid=Decimal("0"),
            )
        private_key = os.getenv("AZURO_PRIVATE_KEY", "")
        if not private_key:
            return self._rejected(order, "AZURO_PRIVATE_KEY not set")
        try:
            tx_hash = await self._client.sign_and_send_bet(
                private_key=private_key,
                condition_id=order.market_id,
                outcome_index=0,
                amount_wei=int(order.size * 10**18),
            )
            # Azuro protocol: fees are gas costs on-chain, not exposed via API
            # Estimate gas fee based on typical Polygon gas price (~0.01 USDC per tx)
            gas_fee_wei = (
                await self._client.estimate_gas_fee()
                if hasattr(self._client, "estimate_gas_fee")
                else 10_000_000_000_000_000
            )  # ~0.01 USDC default
            fees_paid = Decimal(str(gas_fee_wei)) / Decimal("1000000000000000000")

            return NormalizedOrderResult(
                venue_order_id=tx_hash,
                client_order_id=order.client_order_id,
                status=OrderStatus.FILLED,
                filled_size=order.size,
                filled_avg_price=order.price or Decimal("0.5"),
                remaining_size=Decimal("0"),
                fees_paid=fees_paid,
            )
        except Exception as exc:
            logger.exception("bookmaker.xyz order failed")
            return self._rejected(order, str(exc))

    async def cancel_order(self, venue_order_id: str) -> bool:
        """Azuro bets are non-cancellable."""
        raise ValueError("Azuro bets are non-cancellable")

    async def get_markets(self, limit: int = 50, **kwargs) -> list[MarketInfo]:
        """Get available markets from bookmaker.xyz."""
        raw = await self._client.get_markets(limit=limit)
        return [
            MarketInfo(
                market_id=str(c.get("conditionId", "")),
                question=str(c),
                yes_price=0.5,
                no_price=0.5,
            )
            for c in raw
        ]

    async def get_balance(self) -> NormalizedBalance:
        """Get account balance."""
        return NormalizedBalance(
            available=Decimal("0"), total=Decimal("0"), currency="USDC"
        )

    async def get_positions(self) -> list[NormalizedPosition]:
        """Get open positions."""
        return []

    async def health_check(self) -> bool:
        """Check if bookmaker.xyz is accessible."""
        return await self._client.health_check()
