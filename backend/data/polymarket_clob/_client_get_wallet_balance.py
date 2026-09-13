"""Methods carved verbatim out of ``backend/data/polymarket_clob/client.py``."""

from .client import (
    Optional,
    TradeRecord,
)

from . import client as _facade

class PolymarketCLOBMixin3:
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

            client = _facade.get_shared_client()
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
                    _facade.logger.warning(f"Failed to fetch {name} balance: {e}")

            return {"usdc_balance": total_balance, "token_balances": {}, "error": None}
        except Exception as e:
            _facade.logger.warning(f"Polygon RPC balance fetch failed: {e}")

        try:
            # Fetch collateral balance (USDC) with correct signature_type for proxy wallets
            # This is the fallback if RPC fails
            params = _facade.BalanceAllowanceParams(
                asset_type=_facade.AssetType.COLLATERAL,
                signature_type=self.signature_type if self.signature_type else None,
            )
            resp = await _facade.asyncio.to_thread(
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
            _facade.logger.error(
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
            _facade.logger.debug(
                "[polymarket_clob.get_pusd_balance] ClobClient not initialised"
            )
            return 0.0
        if not self._clob_client.creds:
            # Try deriving creds if we have a private key
            if self.private_key:
                try:
                    await self.create_or_derive_api_key()
                except Exception as e:
                    _facade.logger.debug(
                        f"[polymarket_clob.get_pusd_balance] Failed to derive creds: {e}"
                    )
            if not self._clob_client.creds:
                _facade.logger.debug(
                    "[polymarket_clob.get_pusd_balance] No API credentials available"
                )
                return 0.0

        try:
            params = _facade.BalanceAllowanceParams(
                asset_type=_facade.AssetType.COLLATERAL,
                signature_type=self.signature_type if self.signature_type else None,
            )
            result = await _facade.asyncio.to_thread(
                self._clob_client.get_balance_allowance, params
            )
            pusd_balance = int(result.get("balance", 0)) / 1e6
            _facade.logger.debug(
                f"[polymarket_clob.get_pusd_balance] PUSD balance: {pusd_balance:.4f}"
            )
            return pusd_balance
        except Exception as e:
            _facade.logger.warning(
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

        _facade.logger.info(
            f"[polymarket_clob.get_wallet_trades] Fetching trades for {address}"
        )

        # Validate inputs
        if limit > 1000:
            _facade.logger.warning(f"Requested limit {limit} > 1000, capping at 1000")
            limit = 1000

        all_trades: list[_facade.TradeRecord] = []
        current_offset = offset
        page = 0

        async def _fetch_page(off: int) -> tuple[list[dict], bool]:
            """Fetch one page of trades. Returns (trades, has_more)."""
            try:
                resp = await self._http.get(
                    f"{_facade.DATA_HOST}/trades",
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

                _facade.logger.debug(
                    f"[polymarket_clob.get_wallet_trades] "
                    f"Page {page}: {len(trades)} trades at offset {off}"
                )

                # Check if there are more pages
                has_more = len(trades) == limit
                return trades, has_more
            except Exception as e:
                _facade.logger.error(
                    f"[polymarket_clob.get_wallet_trades._fetch_page] {type(e).__name__}: Failed to fetch page at offset {off}: {e}",
                    exc_info=True,
                )
                raise

        # Fetch paginated results
        while True:
            if max_pages is not None and page >= max_pages:
                _facade.logger.info(
                    f"[polymarket_clob.get_wallet_trades] "
                    f"Reached max_pages={max_pages}, stopping"
                )
                break

            try:
                trades_page, has_more = await _facade.clob_breaker.call(
                    lambda off=current_offset: _fetch_page(off)
                )
            except Exception as e:
                _facade.logger.error(
                    f"[polymarket_clob.get_wallet_trades] {type(e).__name__}: Circuit breaker or API error: {e}",
                    exc_info=True,
                )
                if all_trades:
                    _facade.logger.info(
                        f"Returning {len(all_trades)} trades fetched before error"
                    )
                    break
                raise

            if not trades_page:
                _facade.logger.info(
                    f"[polymarket_clob.get_wallet_trades] "
                    f"No more trades (empty page at offset {current_offset})"
                )
                break

            for trade_data in trades_page:
                try:
                    record = _facade.TradeRecord(
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
                    _facade.logger.warning(
                        f"[polymarket_clob.get_wallet_trades] {type(e).__name__}: Skipping malformed trade record: {e}",
                        exc_info=True,
                    )

            page += 1
            current_offset += limit

            if not has_more:
                _facade.logger.info(
                    f"[polymarket_clob.get_wallet_trades] "
                    f"Reached end of results (page {page})"
                )
                break

        _facade.logger.info(
            f"[polymarket_clob.get_wallet_trades] "
            f"Fetched {len(all_trades)} total trades across {page} pages"
        )

        return all_trades
