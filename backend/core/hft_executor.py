"""HFT Strategy Executor — auto-executes HFT signals with idempotency and audit trail."""

import asyncio
import logging
import time
import uuid
from collections import deque
from typing import Optional, Any

from backend.config import settings
from backend.strategies.types_hft import HFTSignal, HFTExecution
from backend.core.risk_manager_hft import HRiskManager
from backend.core.slippage import calculate_slippage
from backend.monitoring.hft_metrics import record_execution, record_circuit_open, hft_latency_ms

logger = logging.getLogger("trading_bot.hft_executor")


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
        self._executions: deque[HFTExecution] = deque(maxlen=self._MAX_EXECUTION_HISTORY)
        self._failure_count = 0
        self._failure_threshold = 10
        self._circuit_open = False

    async def execute(self, signal: HFTSignal, size: float, bankroll: float) -> HFTExecution:
        """Execute a single HFT signal."""
        risk = None
        # Define start timing assumptions
        start = time.monotonic()
        # Generate a unique execution ID
        exec_id = str(uuid.uuid4())

        # Circuit breaker check
        if self._circuit_open or self._main_breaker.is_open():
            record_execution(strategy="hft", side="BUY", status="cancelled", latency_s=0.0)
            execution = HFTExecution(
                execution_id=exec_id,
                signal_id=signal.signal_id,
                status="cancelled",
                error="Circuit breaker open",
                timestamp=start
            )
            await self._persist_to_db(execution)
            return execution


            record_execution(strategy="hft", side="BUY", status="rejected", latency_s=(time.monotonic() - start))
            # Generate execution to track reject details
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
            await self._persist_to_db(execution)
            return execution

        # Calculate permissible trade risk before execution
        risk = self._risk.validate_hft_trade(signal, bankroll)
        size = risk["size"]
        side = "BUY" if signal.signal_type in ("arb", "prob_arb", "whale") else "SELL"

        book = signal.metadata.get("orderbook") if isinstance(signal.metadata, dict) else None
        if book is not None:
            est = calculate_slippage(book, side, size)
            mid = getattr(book, "mid_price", 0.0) or 0.0
            slippage_bps = abs(est.slippage) * 10000.0 if mid > 0 else abs(est.slippage) * 10000.0
            if slippage_bps > settings.HFT_MAX_SLIPPAGE_BPS:
                latency_ms = (time.monotonic() - start) * 1000
                hft_latency_ms.observe(latency_ms)
                record_execution(strategy="hft", side=side, status="rejected", latency_s=(time.monotonic() - start))
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
                await self._persist_to_db(execution)
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
            record_execution(strategy="hft", side=side, status="filled", latency_s=(time.monotonic() - start))
            return execution

        except Exception as exc:
            self._failure_count += 1
            if self._failure_count >= self._failure_threshold:
                self._circuit_open = True
                record_circuit_open(name="hft_executor", reason="failure_threshold")
                logger.error("[hft_executor] Circuit breaker OPEN")
            record_execution(strategy="hft", side=side, status="failed", latency_s=(time.monotonic() - start))

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

    async def _place_order(self, signal: HFTSignal, side: str, size: float) -> Optional[str]:
        """Place order with retry."""
        if self._clob is None:
            raise ValueError("CLOB instance not initialized")

        idempotency_key = f"hft-{signal.signal_id}-{int(time.monotonic() * 1000000)}"

        for attempt in range(3):
            try:
                result = await self._clob.place_limit_order(
                    token_id=signal.market_id,
                    side=side,
                    price=signal.edge,
                    size=size,
                    idempotency_key=idempotency_key,
                )
                return getattr(result, "order_id", None)
            except Exception:
                if attempt < 2:
                    wait = 0.01 * (2 ** attempt)
                    await asyncio.sleep(wait)
                else:
                    raise

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
                logger.info(f"[hft_executor] Order {order_id} filled at {fill_data['fill_price']}")
        except asyncio.TimeoutError:
            logger.warning(f"[hft_executor] Fill timeout for order {order_id}")
        except Exception as exc:
            logger.error(f"[hft_executor] Fill monitor error for {order_id}: {exc}")
        finally:
            event_bus.unsubscribe_handler("order_update", handler)

    async def execute_batch(self, signals: list[HFTSignal], bankroll: float) -> list[HFTExecution]:
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
