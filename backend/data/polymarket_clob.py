"""
Polymarket CLOB execution client.

Uses httpx.AsyncClient for read-only queries (shared connection pool).
Delegates order creation/placement/cancellation to py_clob_client_v2.ClobClient,
which handles EIP-712 signing, L2 HMAC auth, and tick-size resolution internally.

Auth: EIP-712 L1 (derive API keys) + HMAC-SHA256 L2 (per-request headers).
All order sizes in USDC. All prices in [0.01, 0.99].
"""

import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import httpx
from eth_account import Account
from eth_account.signers.local import LocalAccount

from py_clob_client_v2 import (
    ClobClient,
    ApiCreds,
    BuilderConfig,
    OrderArgs,
    BalanceAllowanceParams,
    AssetType,
    OrderPayload,
)

from backend.core.circuit_breaker import CircuitBreaker
from backend.core.circuit_breaker_pybreaker import polymarket_breaker
from backend.config import settings
from backend.data.shared_client import get_shared_client

from loguru import logger
from backend.monitoring.hft_metrics import record_maker_fill_rate


def _cfg(key: str, default=None):
    return getattr(settings, key, default) if hasattr(settings, key) else default


def ensure_token_id(token_id: str) -> str:
    """Ensure token_id is a decimal string for CLOB API.

    Polymarket CLOB exchange_order_builder expects tokenId to be
    convertible to int via int(tokenId). Gamma/Data APIs return
    token IDs as decimal strings.
    """
    if not token_id:
        return token_id
    if token_id.startswith("0x"):
        try:
            return str(int(token_id, 16))
        except ValueError:
            return token_id
    return token_id


clob_breaker = CircuitBreaker("polymarket_clob")

CLOB_HOST = settings.CLOB_API_URL
GAMMA_HOST = settings.GAMMA_API_URL
DATA_HOST = settings.DATA_API_URL
CHAIN_ID = 137  # Polygon mainnet — Builder Program and all trading run on mainnet


# Keys currently being processed (in-flight guard against concurrent duplicate calls)
_inflight_keys: set[str] = set()
_inflight_lock = asyncio.Lock()


async def _check_and_claim_idempotency(key: str) -> bool:
    """
    Return True (duplicate) if key is already in-flight or in the DB.
    Claims the key in the in-flight set atomically to prevent concurrent duplicates.
    Caller must release via _release_idempotency_key() after the order is recorded.
    """
    async with _inflight_lock:
        if key in _inflight_keys:
            return True
        _inflight_keys.add(key)

    # Check DB for cross-process/restart duplicates
    from backend.models.database import SessionLocal, Trade

    from backend.core.circuit_breaker_pybreaker import db_breaker

    def _db_query():
        db = SessionLocal()
        try:
            existing = db.query(Trade).filter(Trade.clob_idempotency_key == key).first()
            return existing
        finally:
            db.close()

    try:
        existing = db_breaker.call(_db_query)
        if existing is not None:
            async with _inflight_lock:
                _inflight_keys.discard(key)
            return True
        return False
    except Exception as e:
        logger.warning(f"DB circuit breaker open or query failed: {e}")
        return False


def _release_idempotency_key(key: str) -> None:
    """Remove key from in-flight set after order is recorded (or failed)."""
    _inflight_keys.discard(key)


@dataclass
class OrderResult:
    success: bool
    order_id: Optional[str] = None
    error: Optional[str] = None
    fill_price: Optional[float] = None
    fill_size: Optional[float] = None
    idempotency_key: Optional[str] = None
    maker_filled: bool = False


@dataclass
class OrderBook:
    token_id: str
    bids: list[dict] = field(default_factory=list)  # [{price, size}]
    asks: list[dict] = field(default_factory=list)
    mid_price: float = 0.5

    @property
    def best_ask(self) -> Optional[float]:
        return float(self.asks[0]["price"]) if self.asks else None

    @property
    def best_bid(self) -> Optional[float]:
        return float(self.bids[0]["price"]) if self.bids else None

    @property
    def spread(self) -> float:
        if self.best_ask and self.best_bid:
            return self.best_ask - self.best_bid
        return 1.0


@dataclass
class TradeRecord:
    """Trade record from Polymarket Data API."""

    id: str
    user: str
    asset_id: str
    outcome: str  # "YES" | "NO"
    shares: float
    price: float
    spent: float
    timestamp: int
    transaction_hash: Optional[str] = None
    block_number: Optional[int] = None

    @property
    def created_at(self) -> datetime:
        """Convert timestamp to datetime."""
        return datetime.fromtimestamp(self.timestamp, tz=timezone.utc)


class PolymarketCLOB:
    """
    Async Polymarket CLOB client with shared httpx connection pool.

    Usage (paper mode — no keys needed):
        async with PolymarketCLOB() as clob:
            book = await clob.get_order_book(token_id)
            mid = book.mid_price

    Usage (live mode):
        async with PolymarketCLOB(private_key=pk, api_key=k, api_secret=s, api_passphrase=p) as clob:
            result = await clob.place_limit_order(token_id, side="BUY", price=0.65, size=50.0)
    """

    def __init__(
        self,
        private_key: Optional[str] = None,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        api_passphrase: Optional[str] = None,
        mode: str = "paper",
        simulation: Optional[
            bool
        ] = None,  # backward-compat: simulation=True -> mode="paper"
        builder_api_key: Optional[str] = None,
        builder_secret: Optional[str] = None,
        builder_passphrase: Optional[str] = None,
        builder_address: Optional[str] = None,
        signature_type: int = 0,
    ):
        # Backward-compat: if simulation kwarg passed, map to mode
        if simulation is not None:
            self.mode = "paper" if simulation else "live"
        else:
            self.mode = mode
        self.private_key = private_key
        self.api_key = api_key
        self.api_secret = api_secret
        self.api_passphrase = api_passphrase
        self.builder_api_key = builder_api_key
        self.builder_secret = builder_secret
        self.builder_passphrase = builder_passphrase
        self.builder_address = builder_address
        self.signature_type = signature_type

        self._account: Optional[LocalAccount] = None
        if private_key:
            self._account = Account.from_key(private_key)

        # Shared async connection pool for read-only queries
        self._http: Optional[httpx.AsyncClient] = None

        # py-clob-client instance for order operations (sync — wrapped via asyncio.to_thread)
        self._clob_client: Optional[ClobClient] = None
        if private_key:
            creds = None
            if api_key and api_secret and api_passphrase:
                creds = ApiCreds(
                    api_key=api_key,
                    api_secret=api_secret,
                    api_passphrase=api_passphrase,
                )

            builder_config = None
            if builder_api_key and builder_secret and builder_passphrase:
                try:
                    builder_code = (builder_api_key or "").replace("-", "").lower()
                    if builder_code and len(builder_code) < 64:
                        builder_code = builder_code.ljust(64, "0")
                    elif not builder_code:
                        builder_code = "0" * 64

                    builder_config = BuilderConfig(
                        builder_address=builder_address or "",
                        builder_code=builder_code,
                    )
                    logger.info(
                        "[polymarket_clob.__init__] Builder Program configured for address: %s",
                        builder_address or "default",
                    )
                except Exception as e:
                    logger.warning(
                        "[polymarket_clob.__init__] Failed to configure Builder Program: %s: %s",
                        type(e).__name__,
                        e,
                    )
            try:
                self._clob_client = ClobClient(
                    host=self._clob_host,
                    chain_id=self._chain_id,
                    key=private_key,
                    creds=creds,
                    signature_type=signature_type,
                    builder_config=builder_config,
                    funder=builder_address if builder_address else None,
                )
            except Exception as e:
                logger.warning(
                    f"[polymarket_clob.__init__] {type(e).__name__}: Failed to initialise ClobClient: {e}",
                    exc_info=True,
                )

    @property
    def simulation(self) -> bool:
        """Backward-compat: True when not in live mode."""
        return self.mode != "live"

    @property
    def is_paper(self) -> bool:
        return self.mode == "paper"

    @property
    def _clob_host(self) -> str:
        return CLOB_HOST

    @property
    def _chain_id(self) -> int:
        return CHAIN_ID

    async def __aenter__(self):
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0),
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
        )
        return self

    async def __aexit__(self, *_):
        if self._http:
            await self._http.aclose()
            self._http = None

    def _l2_headers(self, method: str, request_path: str, body: str = "") -> dict:
        """Generate Polymarket L2 HMAC auth headers.

        Raises ValueError if API credentials are not set.
        """
        import hashlib
        import hmac
        import time

        if not self.api_key:
            raise ValueError("api_key required for L2 auth headers")
        if not self.api_secret:
            raise ValueError("api_secret required for L2 auth headers")
        if not self.api_passphrase:
            raise ValueError("api_passphrase required for L2 auth headers")

        timestamp = str(int(time.time()))
        message = timestamp + method.upper() + request_path + (body or "")
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()

        headers = {
            "POLY_TIMESTAMP": timestamp,
            "POLY_SIGNATURE": signature,
            "POLY_API_KEY": self.api_key,
            "POLY_PASSPHRASE": self.api_passphrase,
        }
        if self._account:
            headers["POLY_ADDRESS"] = self._account.address
        return headers

    # =========================================================================
    # Public read-only endpoints (no auth)
    # =========================================================================

    async def get_order_book(self, token_id: str) -> OrderBook:
        """Fetch live order book for a token."""
        from backend.data.orderbook_cache import get_orderbook_cache

        cache = get_orderbook_cache()
        cached = await cache.get(token_id)

        if cached:
            logger.debug(
                f"Using cached orderbook for {token_id} (age: {cached.age_seconds:.1f}s)"
            )
            return OrderBook(
                token_id=token_id,
                bids=cached.bids,
                asks=cached.asks,
                mid_price=cached.mid_price,
            )

        async def _fetch_book():
            resp = await self._http.get(
                f"{self._clob_host}/book", params={"token_id": token_id}
            )
            resp.raise_for_status()
            data = resp.json()

            bids = sorted(
                data.get("bids", []), key=lambda x: float(x["price"]), reverse=True
            )
            asks = sorted(data.get("asks", []), key=lambda x: float(x["price"]))

            mid = 0.5
            if bids and asks:
                mid = (float(bids[0]["price"]) + float(asks[0]["price"])) / 2
            elif bids:
                mid = float(bids[0]["price"])
            elif asks:
                mid = float(asks[0]["price"])

            return OrderBook(token_id=token_id, bids=bids, asks=asks, mid_price=mid)

        return await clob_breaker.call(_fetch_book)

    async def get_mid_price(self, token_id: str) -> float:
        """Get mid-price for a token (fast, single endpoint)."""
        from backend.data.orderbook_cache import get_orderbook_cache

        cache = get_orderbook_cache()
        cached_price = await cache.get_mid_price(token_id)

        if cached_price is not None:
            logger.debug(f"Using cached mid price for {token_id}: {cached_price:.4f}")
            return cached_price

        try:
            resp = await self._http.get(
                f"{self._clob_host}/midpoint", params={"token_id": token_id}
            )
            resp.raise_for_status()
            return float(resp.json().get("mid", 0.5))
        except Exception as e:
            logger.debug(
                f"[polymarket_clob.get_mid_price] {type(e).__name__}: Midpoint endpoint failed, falling back to order book: {e}",
                exc_info=True,
            )
            book = await self.get_order_book(token_id)
            return book.mid_price

    async def get_market(self, condition_id: str) -> Optional[dict]:
        """Get market data from Gamma API."""

        async def _fetch_market():
            resp = await self._http.get(
                f"{GAMMA_HOST}/markets", params={"conditionId": condition_id}
            )
            resp.raise_for_status()
            data = resp.json()
            return data[0] if data else None

        try:
            return await polymarket_breaker.call(_fetch_market)
        except Exception as e:
            logger.warning(
                f"[polymarket_clob.get_market] {type(e).__name__}: Failed to fetch market {condition_id}: {e}",
                exc_info=True,
            )
            return None

    async def get_leaderboard(self, window: str = "30d") -> list[dict]:
        """Get Polymarket trader leaderboard via v1 Data API."""
        try:
            time_period = {"1d": "DAY", "7d": "WEEK", "30d": "MONTH", "all": "ALL"}.get(
                window, "MONTH"
            )

            async def _fetch_leaderboard():
                resp = await self._http.get(
                    f"{DATA_HOST}/{settings.DATA_API_VERSION}/leaderboard",
                    params={"timePeriod": time_period, "limit": 50, "orderBy": "PNL"},
                )
                resp.raise_for_status()
                return resp.json()

            return await polymarket_breaker.call(_fetch_leaderboard)
        except Exception as e:
            logger.debug(
                f"[polymarket_clob.get_leaderboard] Unavailable ({type(e).__name__}: {e})"
            )
            return []

    async def get_trader_trades(self, wallet: str, limit: int = 100) -> list[dict]:
        """Get recent trades for a wallet address."""
        resp = await self._http.get(
            f"{DATA_HOST}/trades",
            params={"user": wallet, "limit": limit, "takerOnly": "true"},
        )
        resp.raise_for_status()
        return resp.json()

    async def get_trader_positions(self, wallet: str) -> list[dict]:
        """Get open positions for a wallet address."""
        resp = await self._http.get(
            f"{DATA_HOST}/positions",
            params={"user": wallet, "sizeThreshold": "1.0"},
        )
        resp.raise_for_status()
        return resp.json()

    # =========================================================================
    # API credential derivation (via py-clob-client)
    # =========================================================================

    async def create_or_derive_api_key(self) -> Optional[ApiCreds]:
        """
        Derive or create API credentials from the private key.

        Uses ClobClient.derive_api_key() which:
        1. Tries to create a new API key (L1 auth via private key)
        2. Falls back to deriving an existing key if already created

        Returns ApiCreds(api_key, api_secret, api_passphrase) or None on failure.
        """
        if not self._clob_client:
            logger.error("ClobClient not initialised — private_key required")
            return None

        if (
            self._clob_client.creds
            and self._clob_client.creds.api_key
            and self._clob_client.creds.api_secret
        ):
            self.api_key = self._clob_client.creds.api_key
            self.api_secret = self._clob_client.creds.api_secret
            self.api_passphrase = self._clob_client.creds.api_passphrase
            return self._clob_client.creds

        try:
            creds = await asyncio.to_thread(self._clob_client.derive_api_key)
            if creds and creds.api_secret:
                # Store and upgrade the client to L2
                self.api_key = creds.api_key
                self.api_secret = creds.api_secret
                self.api_passphrase = creds.api_passphrase
                self._clob_client.set_api_creds(creds)
                logger.info(f"API credentials derived for {self._account.address}")
            return creds
        except Exception as e:
            logger.error(
                f"[polymarket_clob.create_or_derive_api_key] {type(e).__name__}: Failed to derive API credentials: {e}",
                exc_info=True,
            )
            return None

    # =========================================================================
    # Authenticated order management (delegated to py-clob-client)
    # =========================================================================

    async def place_limit_order(
        self,
        token_id: str,
        side: str,  # "BUY" or "SELL"
        price: float,
        size: float,
        order_type: str = "GTC",
    ) -> OrderResult:
        """
        Place a limit order on the CLOB.

        In paper mode: returns a fake success with mid-price fill.
        In live/testnet mode: delegates to py-clob-client for signing and submission.

        price: [0.01, 0.99] — the limit price in USDC per share
        size: USDC amount to spend
        """
        if size < _cfg("MIN_ORDER_USDC", 5.0):
            return OrderResult(
                success=False,
                error=f"Size ${size:.2f} below minimum ${_cfg('MIN_ORDER_USDC', 5.0)}",
            )

        # Fail fast for live/testnet mode without credentials (before touching the DB)
        if not self.is_paper:
            if not self._clob_client:
                return OrderResult(
                    success=False,
                    error="ClobClient not initialised — private_key required",
                )
            if not self._clob_client.creds:
                return OrderResult(
                    success=False,
                    error="API credentials required — call create_or_derive_api_key() first",
                )

        # Deterministic key: same token+side+size within a 5-min window = same key → deduplicated.
        # Price excluded — slight price changes between rapid calls must NOT bypass dedup.
        bucket = int(time.time()) // 300
        raw = f"{token_id}:{side}:{size:.4f}:{bucket}"
        idempotency_key = hashlib.sha256(raw.encode()).hexdigest()[:32]
        if await _check_and_claim_idempotency(idempotency_key):
            logger.warning(
                f"Duplicate order detected (key={idempotency_key}), skipping"
            )
            return OrderResult(
                success=False,
                error="Duplicate order: same params already placed this window",
            )
        logger.info(
            f"Order idempotency_key={idempotency_key} | {side} {size} @ {price} token={token_id[:16]}..."
        )

        if self.is_paper:
            # Paper trade: simulate fill at current mid-price
            try:
                mid = await self.get_mid_price(token_id)
            except Exception as e:
                logger.debug(
                    f"[polymarket_clob.place_limit_order] {type(e).__name__}: mid-price fetch failed, using limit price: {e}",
                    exc_info=True,
                )
                mid = price
            logger.info(
                f"[PAPER] {side} {size:.2f} USDC @ {price:.3f} "
                f"(mid={mid:.3f}) token={token_id[:16]}..."
            )
            result = OrderResult(
                success=True,
                order_id=f"paper_{int(time.time())}",
                fill_price=mid,
                fill_size=size,
                idempotency_key=idempotency_key,
            )
            _release_idempotency_key(idempotency_key)
            return result

        # Live/testnet mode — use py-clob-client
        if not self._clob_client:
            _release_idempotency_key(idempotency_key)
            return OrderResult(
                success=False, error="ClobClient not initialised — private_key required"
            )
        if not self._clob_client.creds:
            _release_idempotency_key(idempotency_key)
            return OrderResult(
                success=False,
                error="API credentials required — call create_or_derive_api_key() first",
            )

        if clob_breaker.state == "OPEN":
            logger.warning("CLOB circuit OPEN, rejecting order placement")
            _release_idempotency_key(idempotency_key)
            return OrderResult(
                success=False, error="Circuit breaker OPEN for polymarket_clob"
            )

        mode_label = "[TESTNET]" if self.mode == "testnet" else "[LIVE]"
        try:
            # Ensure token_id is in the decimal format expected by py-clob-client
            clean_token_id = ensure_token_id(token_id)

            # In CLOB V2, OrderArgsV2.size is shares.
            # In PolyEdge, size argument is USDC to spend.
            shares = size / price if side == "BUY" else size

            order_args = OrderArgs(
                token_id=clean_token_id,
                price=price,
                size=shares,
                side=side,
            )

            # ClobClient.create_order handles tick-size resolution, neg_risk, signing
            signed_order = await asyncio.to_thread(
                self._clob_client.create_order, order_args
            )

            # Post the signed order
            resp = await asyncio.to_thread(self._clob_client.post_order, signed_order)

            order_id = (
                resp.get("orderID", resp.get("id", "unknown"))
                if isinstance(resp, dict)
                else str(resp)
            )
            logger.info(
                f"{mode_label} Order placed: {order_id} | {side} {size} @ {price}"
            )
            await clob_breaker._on_success()
            return OrderResult(success=True, order_id=order_id)

        except Exception as e:
            error_msg = str(e)
            import traceback

            print(
                f"[CLOB ERROR] {type(e).__name__}: {error_msg}\n{traceback.format_exc()}",
                flush=True,
            )
            await clob_breaker._on_failure()
            return OrderResult(success=False, error=error_msg)
        finally:
            # Always release in-flight guard so same params can be retried later
            _release_idempotency_key(idempotency_key)

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order. Delegates to py-clob-client."""
        if self.is_paper:
            logger.info(f"[PAPER] Cancel order {order_id}")
            return True
        if not self._clob_client or not self._clob_client.creds:
            logger.error("Cancel requires ClobClient with API credentials")
            return False
        try:
            resp = await asyncio.to_thread(
                self._clob_client.cancel_order, OrderPayload(orderID=order_id)
            )
            return resp.get("success", False) if isinstance(resp, dict) else bool(resp)
        except Exception as e:
            logger.error(
                f"[polymarket_clob.cancel_order] {type(e).__name__}: Cancel failed: {e}",
                exc_info=True,
            )
            return False

    async def get_open_orders(self) -> list[dict]:
        """Get all open orders for this account. Delegates to py-clob-client."""
        if self.is_paper or not self._clob_client or not self._clob_client.creds:
            return []
        try:
            return await asyncio.to_thread(self._clob_client.get_open_orders)
        except Exception as e:
            logger.error(
                f"[polymarket_clob.get_open_orders] {type(e).__name__}: Failed to get open orders: {e}",
                exc_info=True,
            )
            return []

    async def get_order(self, order_id: str) -> Optional[dict]:
        """Fetch a single order by CLOB order ID.

        Args:
            order_id: The CLOB order ID to look up.

        Returns:
            Order dict from CLOB API, or None if not found / error.
        """
        if not order_id:
            return None
        try:
            resp = await self._http.get(f"{self._clob_host}/order/{order_id}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            logger.warning(
                f"[polymarket_clob.get_order] HTTP {e.response.status_code} for order {order_id}: {e}"
            )
            return None
        except Exception as e:
            logger.warning(
                f"[polymarket_clob.get_order] Failed to get order {order_id}: {e}"
            )
            return None

    async def cancel_all_orders(self) -> bool:
        """Cancel all open orders. Delegates to py-clob-client."""
        if self.is_paper:
            return True
        if not self._clob_client or not self._clob_client.creds:
            logger.error("Cancel all requires ClobClient with API credentials")
            return False
        try:
            _resp = await asyncio.to_thread(self._clob_client.cancel_all)
            logger.info("Cancelled all open orders")
            return True
        except Exception as e:
            logger.error(
                f"[polymarket_clob.cancel_all_orders] {type(e).__name__}: Failed to cancel all orders: {e}",
                exc_info=True,
            )
            return False

    async def place_maker_first_order(
        self,
        token_id: str,
        side: str,
        size: float,
        edge_pp: float,
        timeout: float = 15.0,
    ) -> OrderResult:
        side_u = (side or "BUY").upper()

        try:
            book = await self.get_order_book(token_id)
        except Exception:
            book = None

        if edge_pp > 20:
            if book and side_u == "BUY" and book.best_ask:
                taker_price = float(book.best_ask)
            elif book and side_u == "SELL" and book.best_bid:
                taker_price = float(book.best_bid)
            else:
                try:
                    taker_price = await self.get_mid_price(token_id)
                except Exception:
                    taker_price = 0.5
            taker_price = max(0.01, min(0.99, taker_price))
            result = await self.place_limit_order(
                token_id=token_id,
                side=side_u,
                price=taker_price,
                size=size,
            )
            try:
                record_maker_fill_rate(token_id, False)
            except Exception:
                logger.exception("record_maker_fill_rate failed")
            if hasattr(result, "maker_filled"):
                try:
                    result.maker_filled = False
                except Exception:
                    logger.exception("set maker_filled failed")
            return result

        if book and side_u == "BUY" and book.best_bid:
            maker_price = float(book.best_bid) + 0.001
        elif book and side_u == "SELL" and book.best_ask:
            maker_price = float(book.best_ask) - 0.001
        else:
            try:
                mid = await self.get_mid_price(token_id)
            except Exception:
                mid = 0.5
            maker_price = mid + 0.001 if side_u == "BUY" else mid - 0.001
        maker_price = max(0.01, min(0.99, round(maker_price, 4)))

        maker_result = await self.place_limit_order(
            token_id=token_id,
            side=side_u,
            price=maker_price,
            size=size,
        )

        if not getattr(maker_result, "success", False):
            try:
                record_maker_fill_rate(token_id, False)
            except Exception:
                logger.exception("record_maker_fill_rate failed")
            return maker_result

        if getattr(maker_result, "fill_price", None) is not None:
            try:
                record_maker_fill_rate(token_id, True)
            except Exception:
                logger.exception("record_maker_fill_rate failed")
            if hasattr(maker_result, "maker_filled"):
                try:
                    maker_result.maker_filled = True
                except Exception:
                    logger.exception("set maker_filled failed")
            return maker_result

        order_id = getattr(maker_result, "order_id", None)

        async def _poll_for_fill() -> bool:
            while True:
                try:
                    open_orders = await self.get_open_orders()
                except Exception:
                    open_orders = []
                still_open = any(
                    (isinstance(o, dict) and o.get("id") == order_id)
                    for o in (open_orders or [])
                )
                if not still_open:
                    return True
                await asyncio.sleep(0.1)

        try:
            await asyncio.wait_for(_poll_for_fill(), timeout=timeout)
            try:
                record_maker_fill_rate(token_id, True)
            except Exception:
                logger.exception("record_maker_fill_rate failed")
            if hasattr(maker_result, "maker_filled"):
                try:
                    maker_result.maker_filled = True
                except Exception:
                    logger.exception("set maker_filled failed")
            return maker_result
        except asyncio.TimeoutError:
            if order_id:
                try:
                    await self.cancel_order(order_id)
                except Exception:
                    logger.exception("cancel_order during taker escalation failed")
            try:
                taker_result = await self.place_market_order(
                    token_id=token_id,
                    side=side_u,
                    size=size,
                )
            except Exception as e:
                logger.error(f"Taker escalation failed: {e}", exc_info=True)
                try:
                    record_maker_fill_rate(token_id, False)
                except Exception:
                    logger.exception("record_maker_fill_rate failed")
                return OrderResult(success=False, error=f"Taker escalation failed: {e}")
            try:
                record_maker_fill_rate(token_id, False)
            except Exception:
                logger.exception("record_maker_fill_rate failed")
            if hasattr(taker_result, "maker_filled"):
                try:
                    taker_result.maker_filled = False
                except Exception:
                    logger.exception("set maker_filled failed")
            return taker_result

    async def get_wallet_balance(self) -> dict:
        """
        Fetch wallet balance from Polymarket.

        Returns:
            dict: {
                "usdc_balance": float,
                "token_balances": dict,  # token_id -> balance
                "error": str | None
            }
        """
        if self.is_paper or not self._clob_client or not self._clob_client.creds:
            return {
                "usdc_balance": 0.0,
                "token_balances": {},
                "error": "Not in live/testnet mode or not authenticated",
            }

        try:
            # First attempt RPC for USDC.e since it handles proxy wallets natively
            # without requiring py-clob-client authentication that is often flawed for builders

            wallet_address = (
                self.builder_address if self.builder_address else self._account.address
            )
            from backend.config import settings

            tokens = {
                "USDC.e": settings.USDC_E_ADDRESS,
                "USDC Native": settings.USDC_NATIVE_ADDRESS,
                "pUSD": settings.PUSD_ADDRESS,
            }

            rpc_url = settings.POLYGON_RPC_URL
            total_balance = 0.0

            client = get_shared_client()
            for name, addr in tokens.items():
                data = (
                    "0x70a08231000000000000000000000000"
                    + wallet_address.lower()[2:]
                )
                try:
                    res = await client.post(
                        rpc_url,
                        json={
                            "jsonrpc": "2.0",
                            "method": "eth_call",
                            "params": [{"to": addr, "data": data}, "latest"],
                            "id": 1,
                        },
                        headers={"User-Agent": "polyedge-finance"},
                    )
                    res_data = res.json()
                    if res.status_code == 200 and "result" in res_data:
                        hex_val = res_data["result"]
                        if hex_val == "0x" or not hex_val:
                            hex_val = "0x0"
                        total_balance += int(hex_val, 16) / 1e6
                except Exception as e:
                    logger.warning(f"Failed to fetch {name} balance: {e}")

            return {"usdc_balance": total_balance, "token_balances": {}, "error": None}
        except Exception as e:
            logger.warning(f"Polygon RPC balance fetch failed: {e}")

        try:
            # Fetch collateral balance (USDC) with correct signature_type for proxy wallets
            # This is the fallback if RPC fails
            params = BalanceAllowanceParams(
                asset_type=AssetType.COLLATERAL,
                signature_type=self.signature_type if self.signature_type else None,
            )
            resp = await asyncio.to_thread(
                self._clob_client.get_balance_allowance, params
            )

            if resp and isinstance(resp, dict):
                usdc_balance = (
                    float(resp.get("balance", 0)) / 1e6
                )  # Convert from 6 decimals
                return {
                    "usdc_balance": usdc_balance,
                    "token_balances": resp.get("tokenBalances", {}),
                    "error": None,
                }
            else:
                return {
                    "usdc_balance": 0.0,
                    "token_balances": {},
                    "error": "Invalid response from balance endpoint",
                }
        except Exception as e:
            logger.error(
                f"[polymarket_clob.get_wallet_balance] {type(e).__name__}: Failed to fetch wallet balance: {e}",
                exc_info=True,
            )
            return {"usdc_balance": 0.0, "token_balances": {}, "error": str(e)}

    async def get_pusd_balance(self) -> float:
        """
        Fetch CLOB-internal PUSD balance via py_clob_client.

        PUSD is Polymarket's internal collateral token (not an ERC20 on-chain).
        This uses the CLOB API's get_balance_allowance endpoint with
        AssetType.COLLATERAL to check the available trading balance.

        Returns:
            float: PUSD balance in human-readable units (divided by 1e6).
                   Returns 0.0 on error or if not authenticated.
        """
        if not self._clob_client:
            logger.debug(
                "[polymarket_clob.get_pusd_balance] ClobClient not initialised"
            )
            return 0.0
        if not self._clob_client.creds:
            # Try deriving creds if we have a private key
            if self.private_key:
                try:
                    await self.create_or_derive_api_key()
                except Exception as e:
                    logger.debug(
                        f"[polymarket_clob.get_pusd_balance] Failed to derive creds: {e}"
                    )
            if not self._clob_client.creds:
                logger.debug(
                    "[polymarket_clob.get_pusd_balance] No API credentials available"
                )
                return 0.0

        try:
            params = BalanceAllowanceParams(
                asset_type=AssetType.COLLATERAL,
                signature_type=self.signature_type if self.signature_type else None,
            )
            result = await asyncio.to_thread(
                self._clob_client.get_balance_allowance, params
            )
            pusd_balance = int(result.get("balance", 0)) / 1e6
            logger.debug(
                f"[polymarket_clob.get_pusd_balance] PUSD balance: {pusd_balance:.4f}"
            )
            return pusd_balance
        except Exception as e:
            logger.warning(
                f"[polymarket_clob.get_pusd_balance] {type(e).__name__}: Failed to fetch PUSD balance: {e}",
                exc_info=True,
            )
            return 0.0

    async def get_wallet_trades(
        self,
        wallet_address: Optional[str] = None,
        limit: int = 1000,
        offset: int = 0,
        max_pages: Optional[int] = None,
    ) -> list[TradeRecord]:
        """
        Fetch historical trades for a wallet from Polymarket Data API.

        Args:
            wallet_address: Wallet to fetch trades for. If None, uses self.builder_address
            limit: Records per page (max 1000, default 1000)
            offset: Starting offset (for pagination)
            max_pages: Max pages to fetch. If None, fetches all pages

        Returns:
            List of TradeRecord objects (blockchain-authoritative history)

        Raises:
            ValueError: If no wallet address available
            HTTPStatusError: If API returns error

        Usage:
            async with clob_factory() as clob:
                trades = await clob.get_wallet_trades(limit=500)
                # Returns all trades for connected wallet

                trades = await clob.get_wallet_trades(
                    wallet_address="0xabc...",
                    max_pages=5
                )
                # Returns first 5 pages only
        """
        # Determine which address to query
        address = wallet_address
        if not address:
            if self.builder_address:
                address = self.builder_address
            elif self._account:
                address = self._account.address
            else:
                raise ValueError(
                    "No wallet address available. "
                    "Either pass wallet_address arg, set POLYMARKET_BUILDER_ADDRESS, "
                    "or initialize with private_key"
                )

        logger.info(
            f"[polymarket_clob.get_wallet_trades] Fetching trades for {address}"
        )

        # Validate inputs
        if limit > 1000:
            logger.warning(f"Requested limit {limit} > 1000, capping at 1000")
            limit = 1000

        all_trades: list[TradeRecord] = []
        current_offset = offset
        page = 0

        async def _fetch_page(off: int) -> tuple[list[dict], bool]:
            """Fetch one page of trades. Returns (trades, has_more)."""
            try:
                resp = await self._http.get(
                    f"{DATA_HOST}/trades",
                    params={
                        "user": address,
                        "limit": limit,
                        "offset": off,
                    },
                    timeout=30.0,
                )
                resp.raise_for_status()
                data = resp.json()

                # Data API returns {"trades": [...]} or just [...]
                trades = data.get("trades", data) if isinstance(data, dict) else data
                if not isinstance(trades, list):
                    raise ValueError(f"Unexpected response format: {type(trades)}")

                logger.debug(
                    f"[polymarket_clob.get_wallet_trades] "
                    f"Page {page}: {len(trades)} trades at offset {off}"
                )

                # Check if there are more pages
                has_more = len(trades) == limit
                return trades, has_more
            except Exception as e:
                logger.error(
                    f"[polymarket_clob.get_wallet_trades._fetch_page] {type(e).__name__}: Failed to fetch page at offset {off}: {e}",
                    exc_info=True,
                )
                raise

        # Fetch paginated results
        while True:
            if max_pages is not None and page >= max_pages:
                logger.info(
                    f"[polymarket_clob.get_wallet_trades] "
                    f"Reached max_pages={max_pages}, stopping"
                )
                break

            try:
                trades_page, has_more = await clob_breaker.call(
                    lambda off=current_offset: _fetch_page(off)
                )
            except Exception as e:
                logger.error(
                    f"[polymarket_clob.get_wallet_trades] {type(e).__name__}: Circuit breaker or API error: {e}",
                    exc_info=True,
                )
                if all_trades:
                    logger.info(
                        f"Returning {len(all_trades)} trades fetched before error"
                    )
                    break
                raise

            if not trades_page:
                logger.info(
                    f"[polymarket_clob.get_wallet_trades] "
                    f"No more trades (empty page at offset {current_offset})"
                )
                break

            for trade_data in trades_page:
                try:
                    record = TradeRecord(
                        id=trade_data.get("id") or trade_data.get("conditionId", ""),
                        user=trade_data.get("user")
                        or trade_data.get("proxyWallet", ""),
                        asset_id=trade_data.get("asset_id")
                        or trade_data.get("asset", ""),
                        outcome=trade_data.get("outcome") or trade_data.get("side", ""),
                        shares=float(
                            trade_data.get("shares", 0) or trade_data.get("size", 0)
                        ),
                        price=float(trade_data.get("price", 0)),
                        spent=float(trade_data.get("spent", 0) or 0),
                        timestamp=int(trade_data.get("timestamp", 0)),
                        transaction_hash=trade_data.get("transaction_hash"),
                        block_number=trade_data.get("block_number"),
                    )
                    all_trades.append(record)
                except (KeyError, ValueError) as e:
                    logger.warning(
                        f"[polymarket_clob.get_wallet_trades] {type(e).__name__}: Skipping malformed trade record: {e}",
                        exc_info=True,
                    )

            page += 1
            current_offset += limit

            if not has_more:
                logger.info(
                    f"[polymarket_clob.get_wallet_trades] "
                    f"Reached end of results (page {page})"
                )
                break

        logger.info(
            f"[polymarket_clob.get_wallet_trades] "
            f"Fetched {len(all_trades)} total trades across {page} pages"
        )

        return all_trades


# =========================================================================
# Convenience: get clob client from settings
# =========================================================================


def clob_from_settings(mode: Optional[str] = None) -> PolymarketCLOB:
    """Create PolymarketCLOB from app settings.

    Args:
        mode: Trading mode override (paper/testnet/live). If None, uses settings.TRADING_MODE.

    Returns:
        PolymarketCLOB instance configured for the specified mode.
    """
    from backend.config import settings

    effective_mode = mode or settings.TRADING_MODE

    return PolymarketCLOB(
        private_key=settings.POLYMARKET_PRIVATE_KEY,
        api_key=settings.POLYMARKET_API_KEY,
        api_secret=settings.POLYMARKET_API_SECRET,
        api_passphrase=settings.POLYMARKET_API_PASSPHRASE,
        mode=effective_mode,
        builder_api_key=settings.POLYMARKET_BUILDER_API_KEY,
        builder_secret=settings.POLYMARKET_BUILDER_SECRET,
        builder_passphrase=settings.POLYMARKET_BUILDER_PASSPHRASE,
        builder_address=settings.POLYMARKET_BUILDER_ADDRESS,
        signature_type=settings.POLYMARKET_SIGNATURE_TYPE,
    )
