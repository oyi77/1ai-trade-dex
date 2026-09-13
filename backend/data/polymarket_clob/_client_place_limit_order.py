"""Methods carved verbatim out of ``backend/data/polymarket_clob/client.py``."""

from .client import (
    Optional,
    OrderResult,
)

from . import client as _facade

class PolymarketCLOBMixin2:
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
        if size < _facade._cfg("MIN_ORDER_USDC", 5.0):
            return _facade.OrderResult(
                success=False,
                error=f"Size ${size:.2f} below minimum ${_facade._cfg('MIN_ORDER_USDC', 5.0)}",
            )

        # Fail fast for live/testnet mode without credentials (before touching the DB)
        if not self.is_paper:
            if not self._clob_client:
                return _facade.OrderResult(
                    success=False,
                    error="ClobClient not initialised — private_key required",
                )
            if not self._clob_client.creds:
                return _facade.OrderResult(
                    success=False,
                    error="API credentials required — call create_or_derive_api_key() first",
                )

        # Deterministic key: same token+side+size within a 5-min window = same key → deduplicated.
        # Price excluded — slight price changes between rapid calls must NOT bypass dedup.
        bucket = int(_facade.time.time()) // 300
        raw = f"{token_id}:{side}:{size:.4f}:{bucket}"
        idempotency_key = _facade.hashlib.sha256(raw.encode()).hexdigest()[:32]
        if await _facade._check_and_claim_idempotency(idempotency_key):
            _facade.logger.warning(
                f"Duplicate order detected (key={idempotency_key}), skipping"
            )
            return _facade.OrderResult(
                success=False,
                error="Duplicate order: same params already placed this window",
            )
        _facade.logger.info(
            f"Order idempotency_key={idempotency_key} | {side} {size} @ {price} token={token_id[:16]}..."
        )

        if self.is_paper:
            # Paper trade: simulate fill at current mid-price
            try:
                mid = await self.get_mid_price(token_id)
            except Exception as e:
                _facade.logger.debug(
                    f"[polymarket_clob.place_limit_order] {type(e).__name__}: mid-price fetch failed, using limit price: {e}",
                    exc_info=True,
                )
                mid = price
            _facade.logger.info(
                f"[PAPER] {side} {size:.2f} USDC @ {price:.3f} "
                f"(mid={mid:.3f}) token={token_id[:16]}..."
            )
            result = _facade.OrderResult(
                success=True,
                order_id=f"paper_{int(_facade.time.time())}",
                fill_price=mid,
                fill_size=size,
                idempotency_key=idempotency_key,
            )
            _facade._release_idempotency_key(idempotency_key)
            return result

        # Live/testnet mode — use py-clob-client
        if not self._clob_client:
            _facade._release_idempotency_key(idempotency_key)
            return _facade.OrderResult(
                success=False, error="ClobClient not initialised — private_key required"
            )
        if not self._clob_client.creds:
            _facade._release_idempotency_key(idempotency_key)
            return _facade.OrderResult(
                success=False,
                error="API credentials required — call create_or_derive_api_key() first",
            )

        if _facade.clob_breaker.state == "OPEN":
            _facade.logger.warning("CLOB circuit OPEN, rejecting order placement")
            _facade._release_idempotency_key(idempotency_key)
            return _facade.OrderResult(
                success=False, error="Circuit breaker OPEN for polymarket_clob"
            )

        mode_label = "[TESTNET]" if self.mode == "testnet" else "[LIVE]"
        try:
            # Ensure token_id is in the decimal format expected by py-clob-client
            clean_token_id = _facade.ensure_token_id(token_id)

            # In CLOB V2, OrderArgsV2.size is shares.
            # In PolyEdge, size argument is USDC to spend.
            shares = size / price if side == "BUY" else size

            order_args = _facade.OrderArgs(
                token_id=clean_token_id,
                price=price,
                size=shares,
                side=side,
            )

            # ClobClient.create_order handles tick-size resolution, neg_risk, signing
            signed_order = await _facade.asyncio.to_thread(
                self._clob_client.create_order, order_args
            )

            # Post the signed order
            resp = await _facade.asyncio.to_thread(self._clob_client.post_order, signed_order)

            order_id = (
                resp.get("orderID", resp.get("id", "unknown"))
                if isinstance(resp, dict)
                else str(resp)
            )
            _facade.logger.info(
                f"{mode_label} Order placed: {order_id} | {side} {size} @ {price}"
            )
            await _facade.clob_breaker._on_success()
            return _facade.OrderResult(success=True, order_id=order_id)

        except Exception as e:
            error_msg = str(e)
            import traceback

            print(
                f"[CLOB ERROR] {type(e).__name__}: {error_msg}\n{traceback.format_exc()}",
                flush=True,
            )
            await _facade.clob_breaker._on_failure()
            return _facade.OrderResult(success=False, error=error_msg)
        finally:
            # Always release in-flight guard so same params can be retried later
            _facade._release_idempotency_key(idempotency_key)
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order. Delegates to py-clob-client."""
        if self.is_paper:
            _facade.logger.info(f"[PAPER] Cancel order {order_id}")
            return True
        if not self._clob_client or not self._clob_client.creds:
            _facade.logger.error("Cancel requires ClobClient with API credentials")
            return False
        try:
            resp = await _facade.asyncio.to_thread(
                self._clob_client.cancel_order, _facade.OrderPayload(orderID=order_id)
            )
            return resp.get("success", False) if isinstance(resp, dict) else bool(resp)
        except Exception as e:
            _facade.logger.error(
                f"[polymarket_clob.cancel_order] {type(e).__name__}: Cancel failed: {e}",
                exc_info=True,
            )
            return False
    async def get_open_orders(self) -> list[dict]:
        """Get all open orders for this account. Delegates to py-clob-client."""
        if self.is_paper or not self._clob_client or not self._clob_client.creds:
            return []
        try:
            return await _facade.asyncio.to_thread(self._clob_client.get_open_orders)
        except Exception as e:
            _facade.logger.error(
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
        except _facade.httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            _facade.logger.warning(
                f"[polymarket_clob.get_order] HTTP {e.response.status_code} for order {order_id}: {e}"
            )
            return None
        except Exception as e:
            _facade.logger.warning(
                f"[polymarket_clob.get_order] Failed to get order {order_id}: {e}"
            )
            return None
    async def cancel_all_orders(self) -> bool:
        """Cancel all open orders. Delegates to py-clob-client."""
        if self.is_paper:
            return True
        if not self._clob_client or not self._clob_client.creds:
            _facade.logger.error("Cancel all requires ClobClient with API credentials")
            return False
        try:
            _resp = await _facade.asyncio.to_thread(self._clob_client.cancel_all)
            _facade.logger.info("Cancelled all open orders")
            return True
        except Exception as e:
            _facade.logger.error(
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
                _facade.record_maker_fill_rate(token_id, False)
            except Exception:
                _facade.logger.exception("record_maker_fill_rate failed")
            if hasattr(result, "maker_filled"):
                try:
                    result.maker_filled = False
                except Exception:
                    _facade.logger.exception("set maker_filled failed")
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
                _facade.record_maker_fill_rate(token_id, False)
            except Exception:
                _facade.logger.exception("record_maker_fill_rate failed")
            return maker_result

        if getattr(maker_result, "fill_price", None) is not None:
            try:
                _facade.record_maker_fill_rate(token_id, True)
            except Exception:
                _facade.logger.exception("record_maker_fill_rate failed")
            if hasattr(maker_result, "maker_filled"):
                try:
                    maker_result.maker_filled = True
                except Exception:
                    _facade.logger.exception("set maker_filled failed")
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
                await _facade.asyncio.sleep(0.1)

        try:
            await _facade.asyncio.wait_for(_poll_for_fill(), timeout=timeout)
            try:
                _facade.record_maker_fill_rate(token_id, True)
            except Exception:
                _facade.logger.exception("record_maker_fill_rate failed")
            if hasattr(maker_result, "maker_filled"):
                try:
                    maker_result.maker_filled = True
                except Exception:
                    _facade.logger.exception("set maker_filled failed")
            return maker_result
        except _facade.asyncio.TimeoutError:
            if order_id:
                try:
                    await self.cancel_order(order_id)
                except Exception:
                    _facade.logger.exception("cancel_order during taker escalation failed")
            try:
                taker_result = await self.place_market_order(
                    token_id=token_id,
                    side=side_u,
                    size=size,
                )
            except Exception as e:
                _facade.logger.error(f"Taker escalation failed: {e}", exc_info=True)
                try:
                    _facade.record_maker_fill_rate(token_id, False)
                except Exception:
                    _facade.logger.exception("record_maker_fill_rate failed")
                return _facade.OrderResult(success=False, error=f"Taker escalation failed: {e}")
            try:
                _facade.record_maker_fill_rate(token_id, False)
            except Exception:
                _facade.logger.exception("record_maker_fill_rate failed")
            if hasattr(taker_result, "maker_filled"):
                try:
                    taker_result.maker_filled = False
                except Exception:
                    _facade.logger.exception("set maker_filled failed")
            return taker_result
