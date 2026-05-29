"""Limitless Exchange market provider."""

import copy
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

    async def _hmac_get(self, client, tid, secret, path):
        """HMAC-signed GET request."""
        h = self._hmac_headers(tid, secret, "GET", path)
        r = await client.get(f"https://api.limitless.exchange{path}", headers=h)
        return r

    async def place_order(self, order: NormalizedOrder) -> NormalizedOrderResult:
        """Place order: HMAC for all API calls, SDK _sign_order for EIP-712."""
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
        from limitless_sdk import LimitlessClient as SDKClient
        from limitless_sdk.models import Order as SDKOrder

        pk = os.getenv("LIMITLESS_PRIVATE_KEY", "")
        tid = os.getenv("LIMITLESS_API_KEY", "")
        secret = os.getenv("LIMITLESS_API_SECRET", "")
        if not pk or not tid or not secret:
            return self._rejected(order, "Missing LIMITLESS env vars")
        pk = pk if pk.startswith("0x") else f"0x{pk}"
        print(f"[limitless] AUTH tid={tid[:8]}... secret={secret[:8]}... pk={pk[:10]}...", flush=True)

        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    # 1. Get profile via HMAC
                    pr = await self._hmac_get(client, tid, secret, "/profiles/me")
                    if pr.status_code != 200:
                        return self._rejected(order, f"Profile failed: {pr.status_code}")
                    profile = pr.json()
                    owner_id = profile.get("id")

                    # 2. Get market via HMAC
                    mr = await self._hmac_get(client, tid, secret, f"/markets/{order.market_id}")
                    if mr.status_code != 200:
                        return self._rejected(order, f"Market failed: {mr.status_code}")
                    market = mr.json()
                    tokens = market.get("tokens", {})
                    token_id = tokens.get("yes") if order.side.value.upper() == "BUY" else tokens.get("no")
                    if not token_id:
                        return self._rejected(order, "No token ID")

                    # 3. Build Order
                    price = float(order.price or Decimal("0.5"))
                    size = float(order.size)
                    side_int = 0 if order.side.value.upper() == "BUY" else 1
                    maker_amount = int(size * price * 1e6)
                    taker_amount = int(size * 1e6)
                    is_negrisk = market.get("marketType") == "group" or market.get("negRiskRequestId") is not None

                    eoa_addr = SDKClient(private_key=pk).account.address
                    smart_wallet = profile.get("smartWallet", eoa_addr)
                    sdk_order = SDKOrder(
                        salt=str(random.randint(10**9, 10**10)),
                        maker=smart_wallet,
                        signer=eoa_addr,
                        taker="0x0000000000000000000000000000000000000000",
                        tokenId=str(token_id),
                        makerAmount=maker_amount,
                        takerAmount=taker_amount,
                        feeRateBps=300,
                        side=side_int,
                        signature="0x",
                        signatureType=0,
                        expiration="0",
                        nonce=0,
                        price=price,
                    )

                    # 4. Sign with SDK _sign_order
                    sdk = SDKClient(private_key=pk)
                    signature = sdk._sign_order(sdk_order, is_negrisk=is_negrisk)
                    sdk_order.signature = signature

                    # 5. Submit via HMAC
                    order_dict = sdk_order.__dict__
                    payload = {
                        "order": order_dict,
                        "orderType": "GTC",
                        "marketSlug": order.market_id,
                        "ownerId": owner_id,
                    }
                    body = json.dumps(payload, default=str)
                    h = self._hmac_headers(tid, secret, "POST", "/orders", body)
                    r = await client.post("https://api.limitless.exchange/orders", headers=h, content=body)
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
                        raise Exception(f"Order rejected: {r.status_code} {r.text[:300]}")
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
        """Get available markets from Limitless Exchange via HMAC."""
        import httpx
        tid = os.getenv("LIMITLESS_API_KEY", "")
        secret = os.getenv("LIMITLESS_API_SECRET", "")
        raw = []
        for page in range(1, 50):
            path = f"/markets/active?limit=25&page={page}"
            h = self._hmac_headers(tid, secret, "GET", path)
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(f"https://api.limitless.exchange{path}", headers=h)
            if r.status_code != 200:
                break
            data = r.json().get("data", [])
            if not data:
                break
            raw.extend(data)
            if len(raw) >= limit:
                break
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
