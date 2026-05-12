"""HFT Signal Generator — deduplicates, validates, and routes HFT signals."""

import asyncio
import time
from typing import Optional

from backend.strategies.types_hft import HFTSignal

from loguru import logger
class SignalGenerator:
    """
    HFT signal generator that deduplicates and validates signals.

    Zero Gaps:
    - Deduplication: same market within 1s window
    - Confidence validation: bounds [0.0, 1.0]
    - Signal queue: prevent hot path blocking
    """

    def __init__(self):
        self._seen: dict[str, float] = {}
        self._dedup_window = 1.0
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._pending: list[HFTSignal] = []

    def generate(
        self,
        market_id: str,
        ticker: str,
        signal_type: str,
        edge: float,
        confidence: float,
        metadata: Optional[dict] = None,
    ) -> Optional[HFTSignal]:
        """
        Generate HFT signal if not duplicate and confidence valid.

        Returns None if duplicate (within dedup window) or invalid.
        """
        if not self._validate_confidence(confidence):
            logger.debug(f"[signal_gen] Invalid confidence {confidence} for {market_id}")
            return None

        if not self._validate_edge(edge):
            return None

        key = f"{market_id}:{signal_type}"
        now = time.time()
        if key in self._seen and (now - self._seen[key]) < self._dedup_window:
            return None

        self._seen[key] = now
        signal = HFTSignal(
            market_id=market_id,
            ticker=ticker,
            signal_type=signal_type,
            edge=edge,
            confidence=confidence,
            latency_ms=0.0,
            timestamp=now,
            metadata=metadata or {},
        )

        return signal

    def _validate_confidence(self, confidence: float) -> bool:
        """Validate confidence is bounded [0.0, 1.0]."""
        try:
            return 0.0 <= float(confidence) <= 1.0
        except (ValueError, TypeError):
            return False

    def _validate_edge(self, edge: float) -> bool:
        """Validate edge is within reasonable bounds."""
        try:
            e = float(edge)
            return -1.0 <= e <= 1.0
        except (ValueError, TypeError):
            return False

    def enqueue(self, signal: HFTSignal) -> bool:
        """Add signal to processing queue."""
        try:
            self._queue.put_nowait(signal)
            self._pending.append(signal)
            return True
        except asyncio.QueueFull:
            logger.warning("[signal_gen] Queue full, dropping signal")
            return False

    async def drain(self, max_count: int = 100) -> list[HFTSignal]:
        """Drain up to max_count signals from queue."""
        signals = []
        for _ in range(max_count):
            try:
                sig = self._queue.get_nowait()
                signals.append(sig)
            except asyncio.QueueEmpty:
                break
        return signals

    def purge_stale(self) -> int:
        """Remove stale entries from dedup cache. Returns count removed."""
        now = time.time()
        stale_keys = [k for k, t in self._seen.items() if (now - t) > self._dedup_window * 10]
        for k in stale_keys:
            self._seen.pop(k, None)
        return len(stale_keys)

    def flush_pending(self) -> list[HFTSignal]:
        """Flush pending signals (for cycle completion)."""
        pending = self._pending
        self._pending = []
        return pending
