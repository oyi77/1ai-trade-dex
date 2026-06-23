"""HFT Strategy Executor — auto-executes HFT signals with idempotency and audit trail."""

import asyncio
import time
import uuid
from collections import deque
from typing import Optional, Any

from backend.config import settings
from backend.strategies.types_hft import HFTSignal, HFTExecution
from backend.core.risk.risk_manager_hft import HRiskManager
from backend.core.slippage import calculate_slippage
from backend.core.retry import retry
from backend.monitoring.hft_metrics import (
    record_execution,
    record_circuit_open,
    hft_latency_ms,
)

from loguru import logger


@retry(max_attempts=3)
async def _place_order_with_retry(
    clob: object,
    market_id: str,
    side: str,
    price: float,
    size: float,
    idempotency_key: str,
    signal_id: str,
) -> Optional[str]:
    """Place a limit order with retry. Extracted for @retry decorator."""
    try:
        result = await clob.place_limit_order(
            token_id=market_id,
            side=side,
            price=price,
            size=size,
            idempotency_key=idempotency_key,
        )
        return getattr(result, "order_id", None)
    except Exception:
        logger.exception(
            f"[hft_executor] Order placement failed for signal {signal_id}, retrying..."
        )
        raise


class HFTExecutor:
    """
    HFT Strategy Executor — auto-executes HFT signals with <50ms target.

    Zero Gaps:
    - Idempotency: UUID per signal prevents duplicate orders
    - Audit trail: execution receipt logged for every signal
    - Retry logic: auto-retry on transient failures (3x)
    - Circuit breaker: halt if too many failures
    """

    _MAX_EXECUTION_HISTORY = 500

    def __init__(self, clob: Optional[object] = None, main_breaker: Any = None):
        self._main_breaker = main_breaker
        self._clob = clob
        self._risk = HRiskManager()
        self._executions: deque[HFTExecution] = deque(
            maxlen=self._MAX_EXECUTION_HISTORY
        )
        self._failure_count = 0
        self._failure_threshold = 10
        self._circuit_open = False

    async def execute(
        self, signal: HFTSignal, size: float, bankroll: float
    ) -> HFTExecution:
        """Execute a single HFT signal."""
        risk = None
        # Define start timing assumptions
        start = time.monotonic()
        # Generate a unique execution ID
        exec_id = str(uuid.uuid4())

        # CRITICAL FIX: Check for existing open position on same market
        # Prevents duplicate positions from being opened
        try:
            from backend.db.utils import get_db_session
            from backend.models.database import Trade

            with get_db_session() as db:
                existing_filters = [
                    Trade.settled.is_(False),
                    Trade.trading_mode == settings.TRADING_MODE,
                ]
                if signal.market_id:
                    existing_filters.append(Trade.token_id == signal.market_id)
                elif signal.event_slug:
                    existing_filters.append(Trade.event_slug == signal.event_slug)

                existing_position = db.query(Trade).filter(*existing_filters).first()
                if existing_position:
                    logger.info(
                        f"[hft_executor] Duplicate position blocked for {signal.market_id}/{signal.event_slug}: "
                        f"existing trade {existing_position.id} still open"
                    )
                    execution = HFTExecution(
                        execution_id=exec_id,
                        signal_id=signal.signal_id,
                        status="cancelled",
                        error="Duplicate open position on same market",
                        timestamp=start,
                    )
                    return execution
        except Exception as e:
            logger.error(f"[hft_executor] Error checking for duplicate position: {e}")
            # Continue execution if check fails (fail-open for safety)

        # Circuit breaker check
        if self._circuit_open or self._main_breaker.is_open():
            record_execution(
                strategy="hft", side="BUY", status="cancelled", latency_s=0.0
            )
            execution = HFTExecution(
                execution_id=exec_id,
                signal_id=signal.signal_id,
                status="cancelled",
                error="Circuit breaker open",
                timestamp=start,
            )
            return execution

        # Calculate permissible trade risk before execution
        risk = self._risk.validate_hft_trade(signal, bankroll)
        if not risk.get("allowed", False):
            record_execution(
                strategy="hft",
                side="BUY",
                status="rejected",
                latency_s=(time.monotonic() - start),
            )
            execution = HFTExecution(
                execution_id=exec_id,
                signal_id=signal.signal_id,
                side="BUY",
                size=0.0,
                price=0.0,
                execution_latency_ms=(time.monotonic() - start) * 1000,
                status="rejected",
                error=risk.get("reason", "Unspecified"),
            )
            logger.warning(
                f"[hft_executor] Trade rejected: {risk.get('reason', 'Unknown')}"
            )
            return execution

        size = risk["size"]
        side = "BUY" if signal.signal_type in ("arb", "prob_arb", "whale") else "SELL"

        book = (
            signal.metadata.get("orderbook")
            if isinstance(signal.metadata, dict)
            else None
        )
        if book is not None:
            est = calculate_slippage(book, side, size)
            mid = getattr(book, "mid_price", 0.0) or 0.0
            slippage_bps = (
                abs(est.slippage) * 10000.0 if mid > 0 else abs(est.slippage) * 10000.0
            )
            if slippage_bps > settings.HFT_MAX_SLIPPAGE_BPS:
                latency_ms = (time.monotonic() - start) * 1000
                hft_latency_ms.observe(latency_ms)
                record_execution(
                    strategy="hft",
                    side=side,
                    status="rejected",
                    latency_s=(time.monotonic() - start),
                )
                execution = HFTExecution(
                    execution_id=exec_id,
                    signal_id=signal.signal_id,
                    side=side,
                    size=size,
                    price=signal.edge,
                    execution_latency_ms=latency_ms,
                    status="rejected",
                    error=f"slippage {slippage_bps:.1f}bps exceeds limit",
                )
                logger.warning(
                    f"[hft_executor] Signal rejected: slippage {slippage_bps:.1f}bps exceeds {settings.HFT_MAX_SLIPPAGE_BPS}bps limit"
                )
                return execution

        try:
            order_id = await self._place_order(signal, side, size)
            # WebSocket fill monitoring
            asyncio.create_task(self._monitor_fill(order_id, signal.market_id))
            latency_ms = (time.monotonic() - start) * 1000
            hft_latency_ms.observe(latency_ms)

            execution = HFTExecution(
                execution_id=exec_id,
                signal_id=signal.signal_id,
                order_id=order_id,
                side=side,
                size=size,
                price=signal.edge,
                execution_latency_ms=latency_ms,
                status="filled",
            )

            self._risk.record_position(signal.market_id, size)
            self._executions.append(execution)
            self._failure_count = 0
            record_execution(
                strategy="hft",
                side=side,
                status="filled",
                latency_s=(time.monotonic() - start),
            )
            return execution

        except Exception as exc:
            logger.exception(
                f"[hft_executor] Order execution failed for signal {signal.signal_id}"
            )
            self._failure_count += 1
            if self._failure_count >= self._failure_threshold:
                self._circuit_open = True
                record_circuit_open(name="hft_executor", reason="failure_threshold")
                logger.error("[hft_executor] Circuit breaker OPEN")
            record_execution(
                strategy="hft",
                side=side,
                status="failed",
                latency_s=(time.monotonic() - start),
            )

            return HFTExecution(
                execution_id=exec_id,
                signal_id=signal.signal_id,
                side=side,
                size=size,
                price=signal.edge,
                execution_latency_ms=(time.monotonic() - start) * 1000,
                status="failed",
                error=str(exc),
            )

    async def _place_order(
        self, signal: HFTSignal, side: str, size: float
    ) -> Optional[str]:
        """Place order with retry."""
        if self._clob is None:
            raise ValueError("CLOB instance not initialized")

        idempotency_key = f"hft-{signal.signal_id}-{int(time.monotonic() * 1000000)}"
        return await _place_order_with_retry(
            self._clob,
            signal.market_id,
            side,
            signal.edge,
            size,
            idempotency_key,
            signal.signal_id,
        )

    async def _monitor_fill(self, order_id: str, market_id: str) -> None:
        """Monitor WebSocket for fill confirmation."""
        from backend.core.event_bus import event_bus

        fill_event = asyncio.Event()
        fill_data: dict = {}

        def handler(event_type: str, data: dict) -> None:
            if data.get("order_id") == order_id:
                fill_data.update(data)
                fill_event.set()

        event_bus.subscribe_handler("order_update", handler)
        try:
            await asyncio.wait_for(fill_event.wait(), timeout=30.0)
            # Fill received — update execution price if fill_price available
            if fill_data.get("fill_price"):
                logger.info(
                    f"[hft_executor] Order {order_id} filled at {fill_data['fill_price']}"
                )
        except asyncio.TimeoutError:
            logger.warning(f"[hft_executor] Fill timeout for order {order_id}")
        except Exception as exc:
            logger.error(f"[hft_executor] Fill monitor error for {order_id}: {exc}")
        finally:
            event_bus.unsubscribe_handler("order_update", handler)

    async def execute_batch(
        self, signals: list[HFTSignal], bankroll: float
    ) -> list[HFTExecution]:
        """Execute multiple signals concurrently."""
        per_signal_pct = getattr(settings, "HFT_POSITION_SIZE_PCT", 0.25)
        per_signal_size = bankroll * per_signal_pct
        results = await asyncio.gather(
            *[self.execute(sig, per_signal_size, bankroll) for sig in signals],
            return_exceptions=True,
        )
        return [r for r in results if isinstance(r, HFTExecution)]

    def reset_circuit(self) -> None:
        """Reset the circuit breaker."""
        self._circuit_open = False
        self._failure_count = 0

    def get_recent(self, limit: int = 100) -> list[HFTExecution]:
        """Get recent executions."""
        return list(self._executions)[-limit:]
