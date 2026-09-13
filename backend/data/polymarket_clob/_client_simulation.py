"""Methods carved verbatim out of ``backend/data/polymarket_clob/client.py``."""

from .client import (
    ApiCreds,
    Optional,
    OrderBook,
)

from . import client as _facade

class PolymarketCLOBMixin:
    @property
    def simulation(self) -> bool:
        """Backward-compat: True when not in live mode."""
        return self.mode != "live"
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

        self._account: _facade.Optional[_facade.LocalAccount] = None
        if private_key:
            self._account = _facade.Account.from_key(private_key)

        # Shared async connection pool for read-only queries
        self._http: _facade.Optional[_facade.httpx.AsyncClient] = None

        # py-clob-client instance for order operations (sync — wrapped via asyncio.to_thread)
        self._clob_client: _facade.Optional[_facade.ClobClient] = None
        if private_key:
            creds = None
            if api_key and api_secret and api_passphrase:
                creds = _facade.ApiCreds(
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

                    builder_config = _facade.BuilderConfig(
                        builder_address=builder_address or "",
                        builder_code=builder_code,
                    )
                    _facade.logger.info(
                        f"[polymarket_clob.__init__] Builder Program configured for address: {builder_address or 'default'}"
                    )
                except Exception as e:
                    _facade.logger.warning(
                        f"[polymarket_clob.__init__] Failed to configure Builder Program: {type(e).__name__}: {e}"
                    )
            # For POLY_PROXY (sig_type=1), do NOT pass builder_config —
            # it conflicts with proxy wallet and causes "maker address not allowed".
            # Only use builder_config for EOA (sig_type=0).
            effective_builder = builder_config if signature_type == 0 else None
            effective_funder = builder_address if builder_address else None
            try:
                self._clob_client = _facade.ClobClient(
                    host=self._clob_host,
                    chain_id=self._chain_id,
                    key=private_key,
                    creds=creds,
                    signature_type=signature_type,
                    builder_config=effective_builder,
                    funder=effective_funder,
                )
            except Exception as e:
                _facade.logger.warning(
                    f"[polymarket_clob.__init__] {type(e).__name__}: Failed to initialise ClobClient: {e}",
                    exc_info=True,
                )
    @property
    def is_paper(self) -> bool:
        return self.mode == "paper"
    @property
    def _clob_host(self) -> str:
        return _facade.CLOB_HOST
    @property
    def _chain_id(self) -> int:
        return _facade.CHAIN_ID
    async def __aenter__(self):
        self._http = _facade.httpx.AsyncClient(
            timeout=_facade.httpx.Timeout(15.0, connect=5.0),
            limits=_facade.httpx.Limits(max_keepalive_connections=10, max_connections=20),
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
            _facade.logger.debug(
                f"Using cached orderbook for {token_id} (age: {cached.age_seconds:.1f}s)"
            )
            return _facade.OrderBook(
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

            return _facade.OrderBook(token_id=token_id, bids=bids, asks=asks, mid_price=mid)

        return await _facade.clob_breaker.call(_fetch_book)
    async def get_mid_price(self, token_id: str) -> float:
        """Get mid-price for a token (fast, single endpoint)."""
        from backend.data.orderbook_cache import get_orderbook_cache

        cache = get_orderbook_cache()
        cached_price = await cache.get_mid_price(token_id)

        if cached_price is not None:
            _facade.logger.debug(f"Using cached mid price for {token_id}: {cached_price:.4f}")
            return cached_price

        try:
            resp = await self._http.get(
                f"{self._clob_host}/midpoint", params={"token_id": token_id}
            )
            resp.raise_for_status()
            return float(resp.json().get("mid", 0.5))
        except Exception as e:
            _facade.logger.debug(
                f"[polymarket_clob.get_mid_price] {type(e).__name__}: Midpoint endpoint failed, falling back to order book: {e}",
                exc_info=True,
            )
            book = await self.get_order_book(token_id)
            return book.mid_price
    async def get_last_trade_price(self, token_id: str) -> Optional[float]:
        """Get the last traded price for a token.

        Live response shape (docs/api_samples/clob_last-trade-price.json):
        {"price": "0.99", "side": "BUY"}
        """
        try:
            resp = await self._http.get(
                f"{self._clob_host}/last-trade-price", params={"token_id": token_id}
            )
            resp.raise_for_status()
            price = resp.json().get("price")
            return float(price) if price is not None else None
        except Exception as e:
            _facade.logger.debug(
                f"[polymarket_clob.get_last_trade_price] {type(e).__name__}: {e}"
            )
            return None
    async def get_market(self, condition_id: str) -> Optional[dict]:
        """Get market data from Gamma API."""

        async def _fetch_market():
            resp = await self._http.get(
                f"{_facade.GAMMA_HOST}/markets", params={"conditionId": condition_id}
            )
            resp.raise_for_status()
            data = resp.json()
            return data[0] if data else None

        try:
            return await _facade.polymarket_breaker.call(_fetch_market)
        except Exception as e:
            _facade.logger.warning(
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
                    f"{_facade.DATA_HOST}/{_facade.settings.DATA_API_VERSION}/leaderboard",
                    params={"timePeriod": time_period, "limit": 50, "orderBy": "PNL"},
                )
                resp.raise_for_status()
                return resp.json()

            return await _facade.polymarket_breaker.call(_fetch_leaderboard)
        except Exception as e:
            _facade.logger.debug(
                f"[polymarket_clob.get_leaderboard] Unavailable ({type(e).__name__}: {e})"
            )
            return []
    async def get_trader_trades(self, wallet: str, limit: int = 100) -> list[dict]:
        """Get recent trades for a wallet address."""
        resp = await self._http.get(
            f"{_facade.DATA_HOST}/trades",
            params={"user": wallet, "limit": limit, "takerOnly": "true"},
        )
        resp.raise_for_status()
        return resp.json()
    async def get_trader_positions(self, wallet: str) -> list[dict]:
        """Get open positions for a wallet address."""
        resp = await self._http.get(
            f"{_facade.DATA_HOST}/positions",
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
            _facade.logger.error("ClobClient not initialised — private_key required")
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
            creds = await _facade.asyncio.to_thread(self._clob_client.derive_api_key)
            if creds and creds.api_secret:
                # Store and upgrade the client to L2
                self.api_key = creds.api_key
                self.api_secret = creds.api_secret
                self.api_passphrase = creds.api_passphrase
                self._clob_client.set_api_creds(creds)
                _facade.logger.info(f"API credentials derived for {self._account.address}")
            return creds
        except Exception as e:
            _facade.logger.error(
                f"[polymarket_clob.create_or_derive_api_key] {type(e).__name__}: Failed to derive API credentials: {e}",
                exc_info=True,
            )
            return None
