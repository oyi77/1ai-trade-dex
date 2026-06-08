from eth_account import Account
import json
"""Limitless Exchange client — raw API for markets, SDK for orders."""

import os
import time as _time

import httpx
from loguru import logger


class LimitlessClient:
    """Limitless Exchange API client.

    Uses raw HTTP for market data (includes prices[]),
    uses official limitless-sdk for order placement (EIP-712 signing).
    5-minute cache on market fetches to avoid Cloudflare rate limits.
    """

    def __init__(self, base_url: str = None):
        self._base_url = (
            base_url or os.getenv("LIMITLESS_API_URL", "https://api.limitless.exchange")
        ).rstrip("/")
        self._api_key = os.getenv("LIMITLESS_API_KEY", "")
        self._private_key = os.getenv("LIMITLESS_PRIVATE_KEY", "")
        self._sdk = None
        self._markets_cache = None
        self._markets_cache_time = 0.0
        self._cache_ttl = 300.0  # 5 min

    def _get_sdk(self):
        """Lazy-init the Limitless SDK client for order operations."""
        if self._sdk is None:
            from limitless_sdk import LimitlessClient as SDKClient

            # Patch missing ensure_authenticated (SDK bug)
            if not hasattr(SDKClient, "ensure_authenticated"):
                SDKClient.ensure_authenticated = SDKClient.ensure_session
            key = self._private_key
            if key and not key.startswith("0x"):
                key = "0x" + key
            self._sdk = SDKClient(
                private_key=key or ("0x" + "0" * 64),
                api_key=self._api_key or None,
            )
        return self._sdk

    def _auth_headers(self) -> dict:
        """Build auth headers for raw API calls."""
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        return headers

    def _sign_request(
        token_id: str, secret: str, method: str, path: str, body: str = ""
    ) -> dict:
        """Generate HMAC-SHA256 signed headers for Limitless API."""
        import hmac
        import hashlib
        import base64
        from datetime import datetime, timezone

        timestamp = datetime.now(timezone.utc).isoformat()
        message = f"{timestamp}\n{method}\n{path}\n{body}"
        signature = base64.b64encode(
            hmac.new(
                base64.b64decode(secret),
                message.encode("utf-8"),
                hashlib.sha256,
            ).digest()
        ).decode("utf-8")
        return {
            "lmts-api-key": token_id,
            "lmts-timestamp": timestamp,
            "lmts-signature": signature,
            "Content-Type": "application/json",
        }

    async def _hmac_request(
        self, method: str, path: str, body: str = ""
    ) -> httpx.Response:
        """Make HMAC-signed request to Limitless API."""
        import httpx as httpx_mod

        tid = os.getenv("LIMITLESS_API_KEY", "")
        secret = os.getenv("LIMITLESS_API_SECRET", "")
        headers = self._sign_request(tid, secret, method, path, body)
        async with httpx_mod.AsyncClient(timeout=15) as client:
            if method == "GET":
                return await client.get(
                    f"https://api.limitless.exchange{path}", headers=headers
                )
            else:
                return await client.post(
                    f"https://api.limitless.exchange{path}",
                    headers=headers,
                    content=body,
                )

    async def _get_owner_id(self, address: str) -> int:
        """Get Limitless profile ID (ownerId) for the wallet address."""
        resp = await self._hmac_request("GET", f"/profiles/public/{address}")
        if resp.status_code == 200:
            return resp.json().get("id")
        # Profile might not exist — create via first login
        return None

    async def place_order(
        self, market_id: str, side: str, size: float, price: float, private_key: str
    ) -> dict:
        """Place order using SDK for EIP-712 signing + HMAC auth for submission."""
        import httpx as httpx_mod

        tid = os.getenv("LIMITLESS_API_KEY", "")
        secret = os.getenv("LIMITLESS_API_SECRET", "")
        if not tid or not secret:
            return {"error": "LIMITLESS_API_KEY or LIMITLESS_API_SECRET not set"}

        private_key = (
            private_key if private_key.startswith("0x") else f"0x{private_key}"
        )
        account = Account.from_key(private_key)

        try:
            # Get ownerId
            owner_id = await self._get_owner_id(account.address)
            if not owner_id:
                return {
                    "error": f"No Limitless profile for {account.address}. Create one at limitless.exchange"
                }

            # Get market data
            resp = await self._hmac_request("GET", "/markets/active?limit=200")
            if resp.status_code != 200:
                return {"error": f"Market fetch failed: {resp.status_code}"}
            markets = resp.json().get("data", [])
            market = None
            for m in markets:
                if m.get("slug") == market_id or str(m.get("id")) == str(market_id):
                    market = m
                    break
            if not market:
                return {"error": f"Market {market_id} not found in active markets"}

            # Get token IDs from positionIds
            position_ids = market.get("positionIds", [])
            if not position_ids:
                return {"error": f"No positionIds for market {market_id}"}
            token_id = position_ids[0] if side.upper() == "BUY" else position_ids[1]

            # Calculate amounts (6 decimals for USDC)
            maker_amount = int(size * price * 1e6)  # USDC
            taker_amount = int(size * 1e6)  # shares

            # Build EIP-712 order
            import random
            from eth_account.messages import encode_typed_data

            order_fields = {
                "salt": str(random.randint(1000000000, 9999999999)),
                "maker": account.address,
                "signer": account.address,
                "taker": "0x0000000000000000000000000000000000000000",
                "tokenId": str(token_id),
                "makerAmount": str(maker_amount),
                "takerAmount": str(taker_amount),
                "expiration": "0",
                "nonce": "0",
                "feeRateBps": "0",
                "side": 0,  # BUY
                "signatureType": 0,
            }

            # EIP-712 signing
            exchange_addr = market.get("venue", {}).get(
                "exchange", "0x0000000000000000000000000000000000000000"
            )
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
                "message": order_fields,
            }

            signable = encode_typed_data(full_message=typed_data)
            signed = account.sign_message(signable)
            order_fields["signature"] = signed.signature.hex()

            # Submit order via HMAC
            payload = {
                "order": order_fields,
                "orderType": "GTC",
                "marketSlug": market.get("slug", market_id),
                "ownerId": owner_id,
            }
            body = json.dumps(payload)
            resp = await self._hmac_request("POST", "/orders", body)

            if resp.status_code in (200, 201):
                result = resp.json()
                logger.info(f"[limitless] Order placed: {result}")
                return result
            else:
                return {"error": f"Order failed: {resp.status_code} {resp.text[:300]}"}
        except Exception as e:
            logger.warning(f"[limitless] place_order failed: {e}")
            import traceback

            traceback.print_exc()
            return {"error": str(e)}

    async def cancel_order(self, order_id: str, private_key: str) -> bool:
        """Cancel an open order using official SDK."""
        sdk = self._get_sdk()
        try:
            from limitless_sdk.models import CancelOrderDto

            dto = CancelOrderDto(order_id=order_id)
            await sdk.cancel_order(dto)
            return True
        except Exception as e:
            logger.warning(f"[limitless] cancel_order failed: {e}")
            return False

    async def get_fills(self, wallet_address: str, limit: int = 100) -> list:
        """Get recent fills/trades for a wallet address."""
        sdk = self._get_sdk()
        try:
            return await sdk.get_user_history()
        except Exception as e:
            logger.warning(f"[limitless] get_fills failed: {e}")
            return []

    async def health_check(self) -> bool:
        """Check if Limitless Exchange API is available."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self._base_url}/markets/active",
                    params={"limit": 1},
                    headers=self._auth_headers(),
                )
                return resp.status_code == 200
        except Exception:
            return False
