"""Limitless Exchange provider — HMAC for market data, X-API-Key + EIP-712 for orders."""

import copy
import os
from decimal import Decimal

from backend.markets.base_provider import BaseMarketProvider, MarketProviderManifest
from backend.markets.order_types import (
    MarketInfo,
    NormalizedOrder,
    NormalizedOrderResult,
    OrderSide,
    OrderStatus,
)


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


class LimitlessProvider(BaseMarketProvider):
    """Limitless Base L2 USDC prediction market provider."""

    def __init__(self, *, paper_mode: bool = False):
        super().__init__(paper_mode=paper_mode)

    @staticmethod
    def manifest() -> MarketProviderManifest:
        return MarketProviderManifest(
            name="limitless",
            display_name="Limitless Exchange",
            capabilities=[],
            required_env_vars=["LIMITLESS_API_KEY"],
            supports_paper_mode=True,
        )

    @staticmethod
    def _hmac_headers(tid: str, secret: str, method: str, path: str, body: str = "") -> dict:
        """Generate HMAC-SHA256 signed headers for Limitless API."""
        import hmac, hashlib, base64
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).isoformat()
        msg = f"{ts}\n{method}\n{path}\n{body}"
        sig = base64.b64encode(
            hmac.new(base64.b64decode(secret), msg.encode(), hashlib.sha256).digest()
        ).decode()
        return {
            "lmts-api-key": tid,
            "lmts-timestamp": ts,
            "lmts-signature": sig,
            "Content-Type": "application/json",
        }

    def _api_headers(self) -> dict:
        """X-API-Key header for authenticated requests."""
        return {
            "X-API-Key": _env("LIMITLESS_API_KEY"),
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Market data (HMAC)
    # ------------------------------------------------------------------

    async def get_markets(self, limit: int = 50, **kwargs) -> list[MarketInfo]:
        """Get available markets from Limitless Exchange via HMAC."""
        import httpx
        tid = _env("LIMITLESS_API_KEY")
        secret = _env("LIMITLESS_API_SECRET")
        raw: list[dict] = []
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

        markets: list[MarketInfo] = []
        for m in raw[:limit]:
            slug = m.get("slug", "")
            market_id = slug or str(m.get("id", ""))
            prices = m.get("prices", [])
            if not prices or len(prices) < 2:
                continue
            yes_price = float(prices[0])
            no_price = float(prices[1])
            if yes_price <= 0 or no_price <= 0:
                continue
            markets.append(
                MarketInfo(
                    market_id=market_id,
                    question=m.get("title", ""),
                    yes_price=Decimal(str(yes_price)),
                    no_price=Decimal(str(no_price)),
                    platform="limitless",
                    event_id=str(m.get("id", "")),
                    raw=m,
                )
            )
        return markets

    # ------------------------------------------------------------------
    # Order placement (X-API-Key + EIP-712 signing)
    # ------------------------------------------------------------------

    async def place_order(self, order: NormalizedOrder) -> NormalizedOrderResult:
        """Place order following agents-starter reference implementation.

        Uses X-API-Key auth, EIP-712 signing via SDK _sign_order,
        positionIds from market data, venue.exchange as verifyingContract.
        """
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

        pk = _env("LIMITLESS_PRIVATE_KEY")
        if not pk:
            return self._rejected(order, "LIMITLESS_PRIVATE_KEY not set")
        pk = pk if pk.startswith("0x") else f"0x{pk}"

        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    headers = self._api_headers()

                    # 1. Get market details (with venue.exchange and positionIds)
                    r = await client.get(
                        f"https://api.limitless.exchange/markets/{order.market_id}",
                        headers=headers,
                    )
                    if r.status_code != 200:
                        return self._rejected(order, f"Market fetch failed: {r.status_code}")
                    market = r.json()

                    venue = market.get("venue", {})
                    exchange_addr = venue.get("exchange")
                    if not exchange_addr:
                        return self._rejected(order, "No venue.exchange in market data")

                    position_ids = market.get("positionIds", [])
                    if not position_ids or len(position_ids) < 2:
                        return self._rejected(order, "No positionIds in market data")

                    # 2. Get user profile ID
                    sdk = SDKClient(private_key=pk)
                    eoa_addr = sdk.account.address
                    r2 = await client.get(
                        f"https://api.limitless.exchange/profiles/{eoa_addr}",
                        headers=headers,
                    )
                    if r2.status_code != 200:
                        return self._rejected(order, f"Profile fetch failed: {r2.status_code}")
                    profile = r2.json()
                    owner_id = profile.get("id")
                    if not owner_id:
                        return self._rejected(order, "No profile ID")

                    # 3. Build order amounts (tick-aligned for GTC/FAK)
                    price = round(float(order.price or Decimal("0.5")), 3)
                    usd_amount = float(order.size)
                    side_int = 0 if order.side.value.upper() == "BUY" else 1
                    token_id = position_ids[0] if side_int == 0 else position_ids[1]

                    TICK_SIZE = 1000
                    SCALE = 1_000_000
                    raw_contracts = int(usd_amount * SCALE / price)
                    taker_amount = (raw_contracts // TICK_SIZE) * TICK_SIZE
                    price_scaled = int(price * SCALE)
                    maker_amount = (taker_amount * price_scaled) // SCALE

                    if taker_amount < TICK_SIZE:
                        return self._rejected(order, f"Order too small: {taker_amount} contracts < {TICK_SIZE}")

                    # 4. EIP-712 sign
                    from limitless_sdk.models import Order as SDKOrder
                    sdk_order = SDKOrder(
                        salt=str(random.randint(10**9, 10**10)),
                        maker=eoa_addr,
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
                    is_negrisk = market.get("marketType") == "group" or market.get("negRiskRequestId") is not None
                    signature = sdk._sign_order(sdk_order, is_negrisk=is_negrisk)
                    sdk_order.signature = signature

                    # 5. Submit order via X-API-Key (only API-expected fields)
                    import time
                    order_dict = {
                        "salt": sdk_order.salt,
                        "maker": sdk_order.maker,
                        "signer": sdk_order.signer,
                        "taker": sdk_order.taker,
                        "tokenId": sdk_order.tokenId,
                        "makerAmount": sdk_order.makerAmount,
                        "takerAmount": sdk_order.takerAmount,
                        "expiration": sdk_order.expiration,
                        "nonce": sdk_order.nonce,
                        "feeRateBps": sdk_order.feeRateBps,
                        "side": sdk_order.side,
                        "signatureType": sdk_order.signatureType,
                        "signature": sdk_order.signature,
                        "price": price,
                    }
                    payload = {
                        "order": order_dict,
                        "orderType": "FAK",
                        "marketSlug": order.market_id,
                        "ownerId": owner_id,
                        "clientOrderId": f"{order.market_id}-{int(time.time()*1000)}-{random.randint(10000000,99999999)}",
                    }
                    body = json.dumps(payload, default=str)
                    import sys
                    sys.stderr.write(f"[limitless] BODY: {body[:500]}\n")
                    sys.stderr.flush()
                    r3 = await client.post(
                        "https://api.limitless.exchange/orders",
                        headers=headers,
                        content=body,
                    )
                    if r3.status_code in (200, 201):
                        result = r3.json()
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
                        raise Exception(f"Order rejected: {r3.status_code} {r3.text[:300]} | payload_keys={list(payload.keys())} order_keys={list(order_dict.keys())}")
            except Exception as exc:
                import sys, asyncio
                body_preview = body[:300] if 'body' in dir() else 'NO_BODY'
                sys.stderr.write(f"[limitless] ORDER attempt {attempt+1}/3: {exc}\nBODY: {body_preview}\n")
                sys.stderr.flush()
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                else:
                    return self._rejected(order, str(exc))

    # ------------------------------------------------------------------
    # Stubs
    # ------------------------------------------------------------------

    async def cancel_order(self, order_id: str, **kwargs) -> bool:
        logger.warning(f"[limitless] cancel_order not implemented: {order_id}")
        return False

    async def get_balance(self, **kwargs) -> dict:
        return {"available": Decimal("0"), "locked": Decimal("0"), "total": Decimal("0")}

    async def get_positions(self, **kwargs) -> list:
        return []

    async def get_orderbook(self, market_id: str, **kwargs) -> dict:
        return {"bids": [], "asks": []}
