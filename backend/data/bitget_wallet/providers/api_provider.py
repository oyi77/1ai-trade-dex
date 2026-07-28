"""Bitget Wallet Web3 API provider — concrete implementation.

Authenticated via HMAC-SHA256: x-api-key, x-api-timestamp,
x-api-signature, x-api-passphrase.

Endpoints and base URL follow the Bitget Wallet Web3 (Bitget Onchain)
API spec. Because the exact path tree may vary by deployment, all paths
are defined as module-level constants so they can be overridden.
"""

import hashlib
import hmac
import logging
import time
from typing import Any, Dict, List, Optional

from backend.config import settings
from backend.data.shared_client import get_shared_client
from backend.data.bitget_wallet.base import (
    BaseBitgetWalletProvider,
    BitgetWalletManifest,
)
from backend.data.bitget_wallet.registry import get_registry
from backend.core.risk.circuit_breaker import CircuitBreaker

_registry = get_registry()
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Default API paths (override via env / manifest if needed)
# ------------------------------------------------------------------
DEFAULT_BASE_URL = settings.BITGET_WALLET_API_URL

# Token discovery
TOKEN_LIST_PATH = "/api/bitget/wallet/token/v1/tokens"
TOKEN_RANKING_PATH = "/api/bitget/wallet/token/v1/ranking"

# Price
KLINE_PATH = "/api/bitget/wallet/market/v1/kline"

# Security & liquidity
SECURITY_AUDIT_PATH = "/api/bitget/wallet/token/v1/security-audit"
TOKEN_LIQUIDITY_PATH = "/api/bitget/wallet/token/v1/liquidity"

_breaker = CircuitBreaker(
    "bitget_wallet_api",
    failure_threshold=settings.CB_FAILURE_THRESHOLD,
    recovery_timeout=settings.CB_RECOVERY_TIMEOUT,
)


def _sign(timestamp: str, method: str, request_path: str, body: str, secret: str) -> str:
    """HMAC-SHA256 signature per Bitget API spec."""
    message = timestamp + method.upper() + request_path + body
    mac = hmac.new(
        secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    )
    return mac.hexdigest()


def _auth_headers(
    method: str, path: str, body: str = ""
) -> Dict[str, str]:
    """Build signed headers for a Bitget Wallet Web3 API call.

    Reads credentials from settings (populated from env vars or passed in).
    """
    api_key = settings.BITGET_WALLET_API_KEY or ""
    api_secret = settings.BITGET_WALLET_API_SECRET or ""
    passphrase = settings.BITGET_WALLET_API_PASSPHRASE or ""

    timestamp = str(int(time.time() * 1000))
    signature = _sign(timestamp, method, path, body, api_secret)

    return {
        "x-api-key": api_key,
        "x-api-timestamp": timestamp,
        "x-api-signature": signature,
        "x-api-passphrase": passphrase,
        "Content-Type": "application/json",
    }


def _base_url() -> str:
    """Return configured base URL, falling back to the default."""
    return settings.BITGET_WALLET_API_URL or DEFAULT_BASE_URL


@_registry.plugin
class BitgetWalletAPIProvider(BaseBitgetWalletProvider):
    """Concrete Bitget Wallet Web3 API provider.

    Calls the Bitget Onchain / Wallet Web3 REST API.
    All write operations raise ``NotImplementedError`` — this is a
    read-only Market & Token data provider.
    """

    @classmethod
    def manifest(cls) -> BitgetWalletManifest:
        return BitgetWalletManifest(
            name="bitget_wallet_api",
            display_name="Bitget Wallet Web3 API",
            version="1.0.0",
            base_url=settings.BITGET_WALLET_API_URL or DEFAULT_BASE_URL,
            required_env_vars=[
                "BITGET_WALLET_API_KEY",
                "BITGET_WALLET_API_SECRET",
                "BITGET_WALLET_API_PASSPHRASE",
            ],
            tags=["bitget", "wallet-web3", "token-discovery", "onchain"],
        )

    # ------------------------------------------------------------------
    # Token discovery
    # ------------------------------------------------------------------
    async def get_token_list(
        self, chain: str = "", limit: int = 50
    ) -> List[Dict[str, Any]]:
        async def _fetch() -> List[Dict[str, Any]]:
            params: Dict[str, Any] = {"limit": min(limit, 200)}
            if chain:
                params["chain"] = chain
            return await self._get(TOKEN_LIST_PATH, params=params)

        return await _breaker.call(_fetch)

    async def get_token_rankings(
        self, sort_by: str = "volume", limit: int = 20
    ) -> List[Dict[str, Any]]:
        async def _fetch() -> List[Dict[str, Any]]:
            params: Dict[str, Any] = {
                "sortBy": sort_by,
                "limit": min(limit, 100),
            }
            return await self._get(TOKEN_RANKING_PATH, params=params)

        return await _breaker.call(_fetch)

    # ------------------------------------------------------------------
    # Price / K-line
    # ------------------------------------------------------------------
    async def get_kline(
        self,
        token_address: str,
        chain: str,
        resolution: str = "1H",
        limit: int = 100,
    ) -> Optional[List[Dict[str, Any]]]:
        async def _fetch() -> Optional[List[Dict[str, Any]]]:
            params = {
                "tokenAddress": token_address,
                "chain": chain,
                "resolution": resolution,
                "limit": min(limit, 500),
            }
            return await self._get(KLINE_PATH, params=params)

        return await _breaker.call(_fetch)

    # ------------------------------------------------------------------
    # Security / risk
    # ------------------------------------------------------------------
    async def get_security_audit(
        self, token_address: str, chain: str
    ) -> Optional[Dict[str, Any]]:
        async def _fetch() -> Optional[Dict[str, Any]]:
            params = {
                "tokenAddress": token_address,
                "chain": chain,
            }
            return await self._get(SECURITY_AUDIT_PATH, params=params)

        return await _breaker.call(_fetch)

    async def get_token_liquidity(
        self, token_address: str, chain: str
    ) -> Optional[Dict[str, Any]]:
        async def _fetch() -> Optional[Dict[str, Any]]:
            params = {
                "tokenAddress": token_address,
                "chain": chain,
            }
            return await self._get(TOKEN_LIQUIDITY_PATH, params=params)

        return await _breaker.call(_fetch)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    async def _get(
        self, path: str, params: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Signed GET request to the Bitget Wallet Web3 API."""
        client = get_shared_client()
        url = _base_url().rstrip("/") + path
        headers = _auth_headers("GET", path)
        resp = await client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        # Bitget API wraps payload in {"code": "00000", "data": ..., "msg": ...}
        if isinstance(data, dict) and "code" in data:
            code = data["code"]
            if code != "00000":
                logger.warning(
                    f"Bitget Wallet API error [{code}]: {data.get('msg', '')} "
                    f"on GET {path}"
                )
                return None
            return data.get("data")
        return data

    async def health_check(self) -> bool:
        """Ping API with a 1-token list query to verify credentials & connectivity."""
        try:
            result = await self.get_token_list(limit=1)
            return isinstance(result, list)
        except Exception as exc:
            logger.warning(f"Bitget Wallet health check failed: {exc}")
            return False

    async def teardown(self) -> None:
        logger.info("BitgetWalletAPIProvider teardown complete")
