"""Limitless Exchange provider — HMAC auth, EIP-712 signing, tokens-based."""

import asyncio
import os
import sys

from backend.markets.base_provider import BaseMarketProvider, MarketProviderManifest
from backend.markets.order_types import (
    MarketInfo,
    NormalizedBalance,
    NormalizedOrder,
    NormalizedOrderResult,
    OrderStatus,
)
from decimal import Decimal


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


class LimitlessProvider(BaseMarketProvider):

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
    def _sign_request(tid: str, secret: str, method: str, path: str, body: str = "") -> dict:
        import hmac
        import hashlib
        import base64
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

    async def get_markets(self, limit: int = 50, **kwargs):
        import httpx
        tid = _env("LIMITLESS_API_KEY")
        secret = _env("LIMITLESS_API_SECRET")
        raw = []
        for page in range(1, 50):
            path = f"/markets/active?limit=25&page={page}"
            h = self._sign_request(tid, secret, "GET", path)
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(f"https://api.limitless.exchange{path}", headers=h)
            if r.status_code != 200:
                break
            data = r.json().get("data", [])
            if not data:
                break
            raw.extend(data)
            if len(raw) >= limit:
                break
        out = []
        for m in raw[:limit]:
            slug = m.get("slug", "")
            prices = m.get("prices", [])
            if not prices or len(prices) < 2:
                continue
            yp, np_ = float(prices[0]), float(prices[1])
            if yp <= 0 or np_ <= 0:
                continue
            out.append(MarketInfo(
                market_id=slug, question=m.get("title", ""),
                yes_price=Decimal(str(yp)), no_price=Decimal(str(np_)),
                platform="limitless", event_id=str(m.get("id", "")), raw=m,
            ))
        return out

    async def place_order(self, order: NormalizedOrder) -> NormalizedOrderResult:
        if self._paper_mode:
            return NormalizedOrderResult(
                venue_order_id=f"paper_{order.market_id}",
                client_order_id=order.client_order_id,
                status=OrderStatus.FILLED, filled_size=order.size,
                filled_avg_price=order.price or Decimal("0.5"),
                remaining_size=Decimal("0"), fees_paid=Decimal("0"),
            )
        import httpx
        import json
        import random
        from eth_account import Account
        from eth_account.messages import encode_typed_data

        tid = _env("LIMITLESS_API_KEY")
        secret = _env("LIMITLESS_API_SECRET")
        pk = _env("LIMITLESS_PRIVATE_KEY")
        if not all([tid, secret, pk]):
            return self._rejected(order, "Missing LIMITLESS env vars")
        pk = pk if pk.startswith("0x") else f"0x{pk}"
        acct = Account.from_key(pk)

        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=15) as c:
                    # Profile
                    h = self._sign_request(tid, secret, "GET", "/profiles/me")
                    r = await c.get("https://api.limitless.exchange/profiles/me", headers=h)
                    if r.status_code != 200:
                        return self._rejected(order, f"Profile failed: {r.status_code}")
                    owner_id = r.json()["id"]

                    # Market
                    h = self._sign_request(tid, secret, "GET", f"/markets/{order.market_id}")
                    r = await c.get(f"https://api.limitless.exchange/markets/{order.market_id}", headers=h)
                    if r.status_code != 200:
                        return self._rejected(order, f"Market failed: {r.status_code}")
                    market = r.json()
                    exchange_addr = market.get("venue", {}).get("exchange", "")
                    if not exchange_addr:
                        return self._rejected(order, "No venue.exchange")
                    tokens = market.get("tokens", {})
                    token_id = tokens.get("yes") if order.side.value.upper() == "BUY" else tokens.get("no")
                    if not token_id:
                        return self._rejected(order, "No token ID")

                    # Build order
                    price = round(float(order.price or Decimal("0.5")), 3)
                    usd = float(order.size)
                    side_int = 0 if order.side.value.upper() == "BUY" else 1
                    SCALE, TICK = 1_000_000, 1000
                    taker = (int(usd * SCALE / price) // TICK) * TICK
                    maker = (taker * int(price * SCALE)) // SCALE
                    if taker < TICK:
                        return self._rejected(order, f"Too small: {taker}")

                    # EIP-712
                    msg_fields = {
                        "salt": str(random.randint(10**9, 10**10)),
                        "maker": acct.address, "signer": acct.address,
                        "taker": "0x0000000000000000000000000000000000000000",
                        "tokenId": str(token_id),
                        "makerAmount": str(maker), "takerAmount": str(taker),
                        "expiration": "0", "nonce": "0", "feeRateBps": "300",
                        "side": "0", "signatureType": "0",
                    }
                    td = {
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
                            "name": "Limitless CTF Exchange", "version": "1",
                            "chainId": 8453, "verifyingContract": exchange_addr,
                        },
                        "message": msg_fields,
                    }
                    sig = "0x" + acct.sign_message(encode_typed_data(full_message=td)).signature.hex()

                    # Submit
                    order_fields = {
                        "salt": msg_fields["salt"],
                        "maker": acct.address, "signer": acct.address,
                        "taker": "0x0000000000000000000000000000000000000000",
                        "tokenId": str(token_id),
                        "makerAmount": maker, "takerAmount": taker,
                        "expiration": "0", "nonce": 0, "feeRateBps": 300,
                        "side": side_int, "signatureType": 0,
                        "signature": sig, "price": price,
                    }
                    payload = {
                        "order": order_fields,
                        "orderType": "FAK",
                        "marketSlug": order.market_id,
                        "ownerId": owner_id,
                    }
                    body = json.dumps(payload)
                    print(f"[limitless] PAYLOAD_KEYS={sorted(payload.keys())} ORDER_KEYS={sorted(order_fields.keys())}", flush=True)
                    print(f"[limitless] BODY_START={body[:200]}", flush=True)
                    h = self._sign_request(tid, secret, "POST", "/orders", body)
                    r = await c.post("https://api.limitless.exchange/orders", headers=h, content=body)
                    if r.status_code in (200, 201):
                        result = r.json()
                        return NormalizedOrderResult(
                            venue_order_id=result.get("orderId", result.get("id", "unknown")),
                            client_order_id=order.client_order_id,
                            status=OrderStatus.OPEN, filled_size=Decimal("0"),
                            filled_avg_price=order.price or Decimal("0.5"),
                            remaining_size=order.size, fees_paid=Decimal("0"),
                        )
                    else:
                        raise Exception(f"Order rejected: {r.status_code} {r.text[:300]} | BODY_KEYS={sorted(order_fields.keys())}")
            except Exception as exc:
                import asyncio
                print(f"[limitless] ORDER attempt {attempt+1}/3: {exc}", file=sys.stderr, flush=True)
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                else:
                    return self._rejected(order, str(exc))

    async def cancel_order(self, order_id: str, **kwargs) -> bool:
        return False

    async def get_balance(self, **kwargs):
        """Get Limitless balance by querying on-chain USDC on Base L2."""
        try:
            import httpx
            from backend.config import settings

            api_key = getattr(settings, "LIMITLESS_API_KEY", "") or ""
            api_secret = getattr(settings, "LIMITLESS_API_SECRET", "") or ""
            if not api_key or not api_secret:
                return NormalizedBalance(venue="limitless", available_cash=Decimal("0"),
                                         total_equity=Decimal("0"), reserved_margin=Decimal("0"))

            import hmac
            import hashlib
            import base64
            from datetime import datetime, timezone

            timestamp = datetime.now(timezone.utc).isoformat()
            message = f"{timestamp}\nGET\n/profiles/me\n"
            signature = base64.b64encode(
                hmac.new(base64.b64decode(api_secret), message.encode(), hashlib.sha256).digest()
            ).decode()

            async with httpx.AsyncClient(timeout=10) as client:
                resp = await asyncio.wait_for(client.get(
                    "https://api.limitless.exchange/profiles/me",
                    headers={
                        "lmts-api-key": api_key,
                        "lmts-timestamp": timestamp,
                        "lmts-signature": signature,
                        "Content-Type": "application/json",
                    },
                ), timeout=10)
                if resp.status_code != 200:
                    return NormalizedBalance(venue="limitless", available_cash=Decimal("0"),
                                             total_equity=Decimal("0"), reserved_margin=Decimal("0"))

                profile = resp.json()
                wallet = profile.get("smartWallet") or profile.get("account", "")
                if not wallet:
                    return NormalizedBalance(venue="limitless", available_cash=Decimal("0"),
                                             total_equity=Decimal("0"), reserved_margin=Decimal("0"))

                usdc_contract = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
                call_data = f"0x70a08231000000000000000000000000{wallet[2:].lower()}"

                rpc_resp = await asyncio.wait_for(client.post("https://mainnet.base.org", json={
                    "jsonrpc": "2.0", "method": "eth_call",
                    "params": [{"to": usdc_contract, "data": call_data}, "latest"], "id": 1,
                }), timeout=12)
                result = rpc_resp.json().get("result", "0x0")
                balance_raw = int(result, 16)
                balance_usdc = Decimal(str(balance_raw / 1e6))

                return NormalizedBalance(
                    venue="limitless",
                    available_cash=balance_usdc,
                    total_equity=balance_usdc,
                    reserved_margin=Decimal("0"),
                    currency="USDC",
                )
        except Exception as exc:
            logger.warning(f"[LimitlessProvider] get_balance failed: {exc}")
            return NormalizedBalance(venue="limitless", available_cash=Decimal("0"),
                                     total_equity=Decimal("0"), reserved_margin=Decimal("0"))

    async def get_positions(self, **kwargs):
        return []

    async def get_orderbook(self, market_id: str, **kwargs):
        return {"bids": [], "asks": []}
