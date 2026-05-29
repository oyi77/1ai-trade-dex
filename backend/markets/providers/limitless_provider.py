"""Limitless Exchange market provider."""

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
    from backend.clients.limitless_client import LimitlessClient

    HAS_LIMITLESS = True
except ImportError:
    HAS_LIMITLESS = False

if not os.getenv("LIMITLESS_API_URL"):
    logger.info("[LimitlessProvider] LIMITLESS_API_URL not set — provider disabled")


@market_registry.plugin
class LimitlessProvider(BaseMarketProvider):
    """Limitless Exchange market provider plugin."""

    def __init__(self, paper_mode: bool = False):
        super().__init__(paper_mode=paper_mode)
        if not HAS_LIMITLESS:
            raise ImportError("LimitlessClient required")
        self._client = LimitlessClient()

    @classmethod
    def manifest(cls) -> MarketProviderManifest:
        return MarketProviderManifest(
            name="limitless",
            display_name="Limitless Exchange",
            version="1.0.0",
            venue_type="prediction_market",
            capabilities=[VenueCapability.LIMIT_ORDERS, VenueCapability.MARKET_SEARCH],
            supported_currencies=["USDC"],
            required_env_vars=["LIMITLESS_API_URL"],
            supports_paper_mode=True,
            is_live_venue=True,
            min_order_size_usd=1.0,
            tags=["prediction_market"],
        )

    @staticmethod
    def _hmac_headers(tid: str, secret: str, method: str, path: str, body: str = "") -> dict:
        import hmac, hashlib, base64
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).isoformat()
        msg = f"{ts}\n{method}\n{path}\n{body}"
        sig = base64.b64encode(hmac.new(base64.b64decode(secret), msg.encode(), hashlib.sha256).digest()).decode()
        return {"lmts-api-key": tid, "lmts-timestamp": ts, "lmts-signature": sig, "Content-Type": "application/json"}

    async def place_order(self, order: NormalizedOrder) -> NormalizedOrderResult:
        """Place order via HMAC-signed direct API calls (no SDK dependency)."""
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
        import httpx, json, random
        from eth_account import Account
        from eth_account.messages import encode_typed_data

        tid = os.getenv("LIMITLESS_API_KEY", "")
        secret = os.getenv("LIMITLESS_API_SECRET", "")
        pk = os.getenv("LIMITLESS_PRIVATE_KEY", "")
        if not tid or not secret:
            return self._rejected(order, "LIMITLESS_API_KEY or LIMITLESS_API_SECRET not set")
        if not pk:
            return self._rejected(order, "LIMITLESS_PRIVATE_KEY not set")

        pk = pk if pk.startswith("0x") else f"0x{pk}"
        account = Account.from_key(pk)

        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    # Get ownerId via /profiles/me (authenticated)
                    path = "/profiles/me"
                    h = self._hmac_headers(tid, secret, "GET", path)
                    r = await client.get(f"https://api.limitless.exchange{path}", headers=h)
                    if r.status_code != 200:
                        return self._rejected(order, f"Profile fetch failed: {r.status_code} {r.text[:100]}")
                    owner_id = r.json().get("id")
                    if not owner_id:
                        return self._rejected(order, "No ownerId in profile")

                    # Get market data by slug
                    path = f"/markets/{order.market_id}"
                    h = self._hmac_headers(tid, secret, "GET", path)
                    r = await client.get(f"https://api.limitless.exchange{path}", headers=h)
                    if r.status_code != 200:
                        return self._rejected(order, f"Market fetch failed: {r.status_code} {r.text[:100]}")
                    market = r.json()

                    tokens = market.get("tokens", {})
                    token_id = tokens.get("yes") if order.side.value.upper() == "BUY" else tokens.get("no")
                    if not token_id:
                        return self._rejected(order, f"No token ID for side {order.side.value}")

                    price = float(order.price or Decimal("0.5"))
                    size = float(order.size)
                    maker_amount = int(size * price * 1e6)
                    taker_amount = int(size * 1e6)

                    exchange_addr = market.get("venue", {}).get("exchange", "0x0000000000000000000000000000000000000000")
                    order_fields = {
                        "salt": random.randint(10**9, 10**10),
                        "maker": account.address,
                        "signer": account.address,
                        "taker": "0x0000000000000000000000000000000000000000",
                        "tokenId": str(token_id),
                        "makerAmount": maker_amount,
                        "takerAmount": taker_amount,
                        "expiration": "0",
                        "nonce": 0,
                        "feeRateBps": 0,
                        "side": 0,
                        "signatureType": 0,
                    }
                    # Deep copy for EIP-712 signing (encode_typed_data may mutate dict)
                    sign_fields = copy.deepcopy(order_fields)
                    typed_data = {
                        "types": {
                            "EIP712Domain": [
                                {"name": "name", "type": "string"},
                                {"name": "version", "type": "string"},
                                {"name": "chainId", "type": "uint256"},
                                {"name": "verifyingContract", "type": "address"},
                            ],
                            "Order": [
                                {"name": "salt", "type": "uint256"},
                                {"name": "maker", "type": "address"},
                                {"name": "signer", "type": "address"},
                                {"name": "taker", "type": "address"},
                                {"name": "tokenId", "type": "uint256"},
                                {"name": "makerAmount", "type": "uint256"},
                                {"name": "takerAmount", "type": "uint256"},
                                {"name": "expiration", "type": "uint256"},
                                {"name": "nonce", "type": "uint256"},
                                {"name": "feeRateBps", "type": "uint256"},
                                {"name": "side", "type": "uint8"},
                                {"name": "signatureType", "type": "uint8"},
                            ],
                        },
                        "primaryType": "Order",
                        "domain": {
                            "name": "Limitless CTF Exchange",
                            "version": "1",
                            "chainId": 8453,
                            "verifyingContract": exchange_addr,
                        },
                        "message": sign_fields,
                    }
                    signable = encode_typed_data(full_message=typed_data)
                    signed = account.sign_message(signable)
                    order_fields["signature"] = "0x" + signed.signature.hex()

                    payload = {
                        "order": order_fields,
                        "orderType": "GTC",
                        "marketSlug": market.get("slug", order.market_id),
                        "ownerId": owner_id,
                    }
                    body = json.dumps(payload)
                    print(f"[limitless] ORDER payload expiration={payload['order']['expiration']} type={type(payload['order']['expiration']).__name__}", flush=True)
                    path = "/orders"
                    h = self._hmac_headers(tid, secret, "POST", path, body)
                    r = await client.post(f"https://api.limitless.exchange{path}", headers=h, content=body)

                    if r.status_code in (200, 201):
                        result = r.json()
                        logger.info(f"[limitless] Order placed: {result}")
                        return NormalizedOrderResult(
                            venue_order_id=result.get("orderId", result.get("id", "unknown")),
                            client_order_id=order.client_order_id,
                            status=OrderStatus.OPEN,
                            filled_size=Decimal("0"),
                            filled_avg_price=order.price or Decimal("0.5"),
                            remaining_size=order.size,
                            fees_paid=Decimal("0"),
                        )
                    else:
                        raise Exception(f"Order rejected: {r.status_code} {r.text[:200]}")

            except Exception as exc:
                import sys, asyncio
                print(f"[limitless] ORDER attempt {attempt+1}/3: {exc}", file=sys.stderr, flush=True)
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                else:
                    return self._rejected(order, str(exc))

    async def cancel_order(self, venue_order_id: str) -> bool:
        """Cancel an open order."""
        private_key = os.getenv("LIMITLESS_PRIVATE_KEY", "")
        return await self._client.cancel_order(venue_order_id, private_key)

    async def search_markets(self, query=None, category=None, limit=50, **kwargs) -> list:
        """Search markets — delegates to get_markets since Limitless has no search API."""
        return await self.get_markets(limit=limit)

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

    async def get_markets(self, limit: int = 50, **kwargs) -> list[MarketInfo]:
        """Get available markets from Limitless Exchange."""
        raw = await self._client.get_markets(limit=limit)
        result = []
        for m in raw:
            prices = m.get("prices", [])
            if not prices or len(prices) < 2:
                continue  # Skip markets with no price data
            yes_price = Decimal(str(prices[0]))
            no_price = Decimal(str(prices[1]))
            if yes_price <= 0 or no_price <= 0:
                continue  # Skip markets with zero prices
            title = m.get("title") or m.get("proxyTitle") or m.get("question", "")
            result.append(MarketInfo(
                venue="limitless",
                market_id=str(m.get("slug", "") or m.get("id", "")),
                title=title,
                description="",
                category="crypto",
                yes_price=yes_price,
                no_price=no_price,
                volume_24h=Decimal(str(m.get("volume", 0) or 0)),
                open_interest=Decimal("0"),
                closes_at=m.get("expirationTimestamp"),
                is_active=True,
                min_order_size=Decimal("1"),
                tick_size=Decimal("0.01"),
                raw=m,
            ))
        return result

    async def get_balance(self) -> NormalizedBalance:
        """Get account balance."""
        return NormalizedBalance(
            venue="limitless", available_cash=Decimal("0"), total_equity=Decimal("0"), reserved_margin=Decimal("0"), currency="USDC"
        )

    async def get_positions(self) -> list[NormalizedPosition]:
        """Get open positions."""
        return []

    async def health_check(self) -> bool:
        """Check if Limitless Exchange is accessible."""
        return await self._client.health_check()
