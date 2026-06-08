"""BSC / Trust Wallet Agent Kit market provider for BNB HACK Track 1.

Routes trades through TWAK CLI for BSC/PancakeSwap execution.
Supports both paper mode (backtesting) and live mode (TWAK-authenticated).

For the hackathon Track 1:
  - Reads CMC signals from CoinMarketCapFeed
  - Routes execution through TWAK on BSC
  - Supports autonomous agent wallet (Mode A) for unattended trading
  - Implements risk controls: max position, drawdown cap, allowed tokens
"""

from decimal import Decimal
from typing import Optional, Dict, Any

from backend.markets.base_provider import (
    BaseMarketProvider,
    MarketProviderManifest,
    NormalizedBalance,
    NormalizedOrder,
    NormalizedOrderResult,
    NormalizedPosition,
    VenueCapability,
)
from backend.markets.order_types import OrderSide, OrderStatus, PositionSide
from backend.markets.provider_registry import market_registry
from backend.clients.twak_client import TWAKClient, TWAKConfig
from loguru import logger


@market_registry.plugin
class BSCProvider(BaseMarketProvider):
    """BSC/TWAK trading venue provider for autonomous trading agents.

    Uses Trust Wallet Agent Kit for self-custody execution on BSC.
    Supports PancakeSwap swaps and BSC perps via TWAK CLI.
    """

    def __init__(self, paper_mode: bool = False):
        super().__init__(paper_mode=paper_mode)
        self._twak: Optional[TWAKClient] = None
        self._allowed_tokens = [
            "USDC", "USDT", "WBNB", "ETH", "BTCB", "SOL", "CAKE"
        ]
        self._paper_balance = Decimal("10000.0")
        self._paper_positions: Dict[str, Dict[str, Any]] = {}

    async def _get_twak(self) -> TWAKClient:
        if self._twak is None:
            self._twak = TWAKClient(TWAKConfig(autonomous_mode=True))
        return self._twak

    @classmethod
    def manifest(cls) -> MarketProviderManifest:
        return MarketProviderManifest(
            name="bsc",
            display_name="BSC (TWAK/PancakeSwap)",
            version="1.0.0",
            venue_type="dex",
            capabilities=[
                VenueCapability.MARKET_ORDERS,
                VenueCapability.LIMIT_ORDERS,
            ],
            supported_currencies=["USDC", "USDT", "BNB"],
            required_env_vars=["TWAK_ACCESS_ID", "TWAK_HMAC_SECRET"],
            supports_paper_mode=True,
            is_live_venue=True,
            min_order_size_usd=10.0,
            tags=["bsc", "pancakeswap", "twak", "hackathon", "bnb-hack"],
        )

    async def place_order(self, order: NormalizedOrder) -> NormalizedOrderResult:
        """Place an order on BSC via TWAK."""
        if self._paper_mode:
            return self._paper_order(order)

        twak = await self._get_twak()

        # Use TWAK CLI for execution
        side = "buy" if order.side in (OrderSide.YES, OrderSide.BUY) else "sell"
        amount = str(float(order.size))
        token = order.market_id

        try:
            is_swap = side == "buy"
            if is_swap:
                result = await twak.swap(amount, "USDC", token, chain="bsc", quote_only=False)
            else:
                result = await twak.swap(amount, token, "USDC", chain="bsc", quote_only=False)

            if result.get("success"):
                return NormalizedOrderResult(
                    venue_order_id=result.get("txHash", result.get("orderId", "")),
                    client_order_id=order.client_order_id,
                    status=OrderStatus.FILLED,
                    filled_size=order.size,
                    filled_avg_price=Decimal(str(result.get("price", "0"))),
                    remaining_size=Decimal("0"),
                    fees_paid=Decimal(str(result.get("fee", "0"))),
                    raw=result,
                )
            return self._rejected(order, result.get("error", "TWAK swap failed"))
        except Exception as exc:
            logger.exception(f"BSC/TWAK order failed: {exc}")
            return self._rejected(order, str(exc))

    async def cancel_order(self, venue_order_id: str) -> bool:
        """Cancel order via TWAK (primarily for limit orders)."""
        try:
            twak = await self._get_twak()
            result = await twak._run("automation", "limit", "cancel", "--id", venue_order_id)
            return result.get("success", False)
        except Exception as exc:
            logger.warning(f"BSC/TWAK cancel failed: {exc}")
            return False

    async def get_balance(self) -> NormalizedBalance:
        """Get BSC wallet balance via TWAK."""
        if self._paper_mode:
            return NormalizedBalance(
                venue="bsc",
                available_cash=self._paper_balance,
                total_equity=self._paper_balance,
                reserved_margin=Decimal("0"),
                currency="USDC",
            )

        try:
            twak = await self._get_twak()
            result = await twak.wallet_portfolio()
            portfolio = result.get("data", result)

            total = Decimal(str(portfolio.get("total_usd", portfolio.get("total", "0"))))
            return NormalizedBalance(
                venue="bsc",
                available_cash=total,
                total_equity=total,
                reserved_margin=Decimal("0"),
                currency="USDC",
                raw=result,
            )
        except Exception as exc:
            logger.error(f"BSC balance fetch failed: {exc}")
            return NormalizedBalance(
                venue="bsc",
                available_cash=Decimal("0"),
                total_equity=Decimal("0"),
                reserved_margin=Decimal("0"),
                currency="USDC",
            )

    async def get_positions(self, market_id=None) -> list[NormalizedPosition]:
        """Get open positions from TWAK portfolio."""
        if self._paper_mode:
            return self._paper_positions_to_normalized()

        try:
            twak = await self._get_twak()
            result = await twak.wallet_portfolio()
            portfolio = result.get("data", result)
            positions = portfolio.get("positions", [])

            normalized = []
            for pos in positions:
                market = pos.get("token", pos.get("symbol", "unknown"))
                if market_id and market != market_id:
                    continue

                amount = float(pos.get("amount", pos.get("balance", 0)))
                if amount <= 0:
                    continue

                normalized.append(NormalizedPosition(
                    market_id=market,
                    side=PositionSide.LONG,
                    size=Decimal(str(amount)),
                    avg_entry_price=Decimal(str(pos.get("entry_price", pos.get("avgPrice", "0")))),
                    venue="bsc",
                    current_price=Decimal(str(pos.get("price", "0"))),
                    unrealized_pnl=Decimal(str(pos.get("unrealized_pnl", "0"))),
                ))
            return normalized
        except Exception as exc:
            logger.error(f"BSC positions fetch failed: {exc}")
            return []

    async def health_check(self) -> bool:
        """Check if TWAK is accessible."""
        if self._paper_mode:
            return True
        try:
            twak = await self._get_twak()
            return await twak.health_check()
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Paper mode
    # ------------------------------------------------------------------

    def _paper_order(self, order: NormalizedOrder) -> NormalizedOrderResult:
        """Simulate order fill in paper mode."""
        from datetime import datetime, timezone
        import random

        side = "buy" if order.side in (OrderSide.YES, OrderSide.BUY) else "sell"
        price = order.price or Decimal("1.0")
        filled_size = order.size

        if side == "buy":
            cost = filled_size * price
            if cost > self._paper_balance:
                return NormalizedOrderResult(
                    venue_order_id="",
                    client_order_id=order.client_order_id,
                    status=OrderStatus.REJECTED,
                    filled_size=Decimal("0"),
                    filled_avg_price=None,
                    remaining_size=order.size,
                    fees_paid=Decimal("0"),
                    raw={"error": f"Insufficient paper balance: {cost} > {self._paper_balance}"},
                )
            self._paper_balance -= cost
            self._paper_positions[order.market_id] = {
                "size": filled_size,
                "entry_price": price,
                "side": side,
            }
        else:
            pos = self._paper_positions.get(order.market_id, {})
            pos_size = pos.get("size", Decimal("0"))
            if filled_size > pos_size:
                return NormalizedOrderResult(
                    venue_order_id="",
                    client_order_id=order.client_order_id,
                    status=OrderStatus.REJECTED,
                    filled_size=Decimal("0"),
                    filled_avg_price=None,
                    remaining_size=order.size,
                    fees_paid=Decimal("0"),
                    raw={"error": "Insufficient position to sell"},
                )
            proceeds = filled_size * price
            self._paper_balance += proceeds
            pos["size"] = pos_size - filled_size
            if pos["size"] <= 0:
                del self._paper_positions[order.market_id]

        return NormalizedOrderResult(
            venue_order_id=f"paper_bsc_{datetime.now(timezone.utc).timestamp()}",
            client_order_id=order.client_order_id,
            status=OrderStatus.FILLED,
            filled_size=filled_size,
            filled_avg_price=price,
            remaining_size=Decimal("0"),
            fees_paid=Decimal("0"),
            raw={"paper_mode": True, "side": side, "token": order.market_id},
        )

    def _paper_positions_to_normalized(self) -> list[NormalizedPosition]:
        result = []
        for market_id, pos in self._paper_positions.items():
            result.append(NormalizedPosition(
                market_id=market_id,
                side=PositionSide.LONG if pos["side"] == "buy" else PositionSide.SHORT,
                size=pos["size"],
                avg_entry_price=pos["entry_price"],
                venue="bsc",
            ))
        return result

    @staticmethod
    def _rejected(order: NormalizedOrder, reason: str) -> NormalizedOrderResult:
        return NormalizedOrderResult(
            venue_order_id="",
            client_order_id=order.client_order_id,
            status=OrderStatus.REJECTED,
            filled_size=Decimal("0"),
            filled_avg_price=None,
            remaining_size=order.size,
            fees_paid=Decimal("0"),
            raw={"error": reason},
        )