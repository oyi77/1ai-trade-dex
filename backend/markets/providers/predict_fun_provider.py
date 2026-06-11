"""predict.fun market provider — powered by Azuro Protocol."""

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

if not os.getenv("AZURO_GRAPH_URL"):
    logger.info("[AzuroProvider] AZURO_GRAPH_URL not set — provider disabled")


@market_registry.plugin
class PredictFunProvider(BaseMarketProvider):
    """predict.fun market provider plugin using Azuro Protocol."""

    def __init__(self, paper_mode: bool = False):
        super().__init__(paper_mode=paper_mode)
        if not HAS_AZURO:
            raise ImportError("AzuroClient required for PredictFunProvider")
        self._client = AzuroClient()

    @classmethod
    def manifest(cls) -> MarketProviderManifest:
        return MarketProviderManifest(
            name="predict_fun",
            display_name="predict.fun",
            version="1.0.0",
            venue_type="prediction_market",
            capabilities=[VenueCapability.MARKET_ORDERS, VenueCapability.MARKET_SEARCH],
            supported_currencies=["USDC"],
            required_env_vars=["AZURO_GRAPH_URL", "AZURO_RPC_URL"],
            supports_paper_mode=True,
            is_live_venue=False,  # Azuro subgraph 301 Moved Permanently
            min_order_size_usd=1.0,
            tags=["azuro", "prediction_market"],
        )

    async def place_order(self, order: NormalizedOrder) -> NormalizedOrderResult:
        """Place an order on predict.fun."""
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
            return NormalizedOrderResult(
                venue_order_id=tx_hash,
                client_order_id=order.client_order_id,
                status=OrderStatus.FILLED,
                filled_size=order.size,
                filled_avg_price=order.price or Decimal("0.5"),
                remaining_size=Decimal("0"),
                fees_paid=Decimal("0"),
            )
        except Exception as exc:
            logger.exception("predict.fun order failed")
            return self._rejected(order, str(exc))

    async def cancel_order(self, venue_order_id: str) -> bool:
        """Azuro bets are non-cancellable."""
        raise ValueError("Azuro bets are non-cancellable")

    async def get_markets(self, limit: int = 50, **kwargs) -> list[MarketInfo]:
        """Get available markets from predict.fun."""
        raw = await self._client.get_markets(limit=limit)
        return [
            MarketInfo(
                venue="predict_fun",
                market_id=str(c.get("conditionId", "")),
                title=str(c.get("question") or c.get("title") or c),
                description="",
                category="",
                yes_price=Decimal("0.5"),
                no_price=Decimal("0.5"),
                volume_24h=Decimal("0"),
                open_interest=Decimal("0"),
                closes_at=None,
                is_active=True,
                min_order_size=Decimal("1"),
                tick_size=Decimal("0.01"),
            )
            for c in raw
            if isinstance(c, dict)
        ]

    async def get_balance(self) -> NormalizedBalance:
        """Get account balance."""
        try:
            raw = await self._client.get_balance()
            bal = Decimal(str(raw.get("balance", 0)))
            return NormalizedBalance(
                venue="predict_fun",
                available_cash=bal,
                total_equity=bal,
                reserved_margin=Decimal("0"),
                currency="USDC",
                raw=raw,
            )
        except Exception as exc:
            logger.warning(f"[PredictFunProvider] get_balance failed: {exc}")
            return NormalizedBalance(
                venue="predict_fun",
                available_cash=Decimal("0"),
                total_equity=Decimal("0"),
                reserved_margin=Decimal("0"),
                currency="USDC",
            )

    async def get_positions(self) -> list[NormalizedPosition]:
        """Get open positions."""
        return []

    async def health_check(self) -> bool:
        """Check if predict.fun is accessible."""
        return await self._client.health_check()
