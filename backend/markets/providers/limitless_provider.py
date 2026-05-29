"""Limitless Exchange provider — HMAC auth, EIP-712 signing, tokens-based orders."""

import copy
import os
from decimal import Decimal

from backend.markets.base_provider import BaseMarketProvider, MarketProviderManifest
from backend.markets.order_types import (
    MarketInfo,
    NormalizedOrder,
    NormalizedOrderResult,
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

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    async def get_markets(self, limit: int = 50, **kwargs) -> list[MarketInfo]:
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
    # Order placement
    # ------------------------------------------------------------------

    async def place_order(self, order: NormalizedOrder) -> NormalizedOrderResult:
        """Place order: HMAC auth, manual EIP-712, tokens-based token IDs."""
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

        tid = _env("LIMITLESS_API_KEY")
        secret = _env("LIMITLESS_API_SECRET")
        pk = _env("LIMITLESS_PRIVATE_KEY")
        if not tid or not secret or not pk:
            return self._rejected(order, "Missing LIMITLESS env vars")
        pk = pk if pk.startswith("0x") else f"0x{pk}"
        acct = Account.from_key(pk)

        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    # 1. Get profile
                    path = "/profiles/me"
                    h = self._hmac_headers(tid, secret, "GET", path)
                    r = await client.get(f"https://api.limitless.exchange{path}", headers=h)
                    if r.status_code != 200:
                        return self._rejected(order, f"Profile failed: {r.status_code}")
                    profile = r.json()
                    owner_id = profile.get("id")

                    # 2. Get market
                    path = f"/markets/{order.market_id}"
                    h = self._hmac_headers(tid, secret, "GET", path)
                    r = await client.get(f"https://api.limitless.exchange{path}", headers=h)
                    if r.status_code != 200:
                        return self._rejected(order, f"Market failed: {r.status_code}")
                    market = r.json()
                    tokens = market.get("tokens", {})
                    exchange_addr = market.get("venue", {}).get("exchange", "")
                    if not exchange_addr:
                        return self._rejected(order, "No venue.exchange")
                    token_id = tokens.get("yes") if order.side.value.upper() == "BUY" else tokens.get("no")
                    if not token_id:
                        return self._rejected(order, "No token ID")

                    # 3. Build order (tick-aligned, 3 decimal price)
                    price = round(float(order.price or Decimal("0.5")), 3)
                    usd = float(order.size)
                    side_int = 0 if order.side.value.upper() == "BUY" else 1
                    SCALE = 1_000_000
                    TICK = 1000
                    raw_contracts = int(usd * SCALE / price)
                    taker_amount = (raw_contracts // TICK) * TICK
                    maker_amount = (taker_amount * int(price * SCALE)) // SCALE
                    if taker_amount < TICK:
                        return self._rejected(order, f"Too small: {taker_amount}")

                    # 4. EIP-712 sign (all values as strings for uint256)
                    msg_fields = {
                        "salt": str(random.randint(10**9, 10**10)),
                        "maker": acct.address,
                        "signer": acct.address,
                        "taker": "0x0000000000000000000000000000000000000000",
                        "tokenId": str(token_id),
                        "makerAmount": str(maker_amount),
                        "takerAmount": str(taker_amount),
                        "expiration": "0",
                        "nonce": "0",
                        "feeRateBps": "300",
                        "side": "0",
                        "signatureType": "0",
                    }
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
                        "message": msg_fields,
                    }
                    signable = encode_typed_data(full_message=typed_data)
                    signed = acct.sign_message(signable)
                    sig_hex = "0x" + signed.signature.hex()

                    # 5. Build payload (int types, no extra fields)
                    order_fields = {
                        "salt": msg_fields["salt"],
                        "maker": acct.address,
                        "signer": acct.address,
                        "taker": "0x0000000000000000000000000000000000000000",
                        "tokenId": str(token_id),
                        "makerAmount": maker_amount,
                        "takerAmount": taker_amount,
                        "expiration": "0",
                        "nonce": 0,
                        "feeRateBps": 300,
                        "side": side_int,
                        "signatureType": 0,
                        "signature": sig_hex,
                        "price": price,
                    }
                    payload = {
                        "order": order_fields,
                        "orderType": "FAK",
                        "marketSlug": order.market_id,
                        "ownerId": owner_id,
                    }
                    body = json.dumps(payload)
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
