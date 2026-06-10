"""APEX edge router — prioritizes, deduplicates, and routes edge signals.

Takes raw edge signals from the scanner/calculator, filters expired and
low-quality signals, deduplicates by market, and returns the top-N
signals for execution.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from backend.core.edge.edge_types import EdgeSignal

logger = logging.getLogger(__name__)


class APEXEdgeRouter:
    """Routes edge signals to execution, prioritizing by expected value.

    Deduplicates by market (keeps highest-edge signal per ticker),
    filters expired signals, and caps per-cycle output.
    """

    def __init__(
        self,
        max_signals_per_cycle: int = 5,
        dedup_window_minutes: int = 30,
    ):
        self.max_signals = max_signals_per_cycle
        self.dedup_window_minutes = dedup_window_minutes
        self._active_signals: dict[str, EdgeSignal] = {}  # ticker -> latest signal
        self._last_cycle: datetime | None = None

    def route(self, signals: list[EdgeSignal]) -> list[EdgeSignal]:
        """Filter, deduplicate, and prioritize signals for execution.

        Args:
            signals: Raw edge signals from the scanner/calculator.

        Returns:
            Top-N signals sorted by expected value, ready for execution.
        """
        # 1. Remove expired signals
        now = datetime.now(timezone.utc)
        valid = [s for s in signals if not s.is_expired]

        if not valid:
            return []

        # 2. Deduplicate: keep highest-edge signal per market
        by_ticker: dict[str, EdgeSignal] = {}
        for s in valid:
            existing = by_ticker.get(s.market_ticker)
            if existing is None or s.edge_pp > existing.edge_pp:
                by_ticker[s.market_ticker] = s

        # 3. Sort by expected value: edge_pp * confidence
        ranked = sorted(
            by_ticker.values(),
            key=lambda s: s.expected_value,
            reverse=True,
        )

        # 4. Cap per cycle
        selected = ranked[: self.max_signals]

        # 5. Update active signals tracking
        for s in selected:
            self._active_signals[s.market_ticker] = s

        self._last_cycle = now

        logger.info(
            f"APEX router: {len(signals)} raw → {len(valid)} valid → "
            f"{len(by_ticker)} deduped → {len(selected)} selected"
        )

        return selected

    def get_active_signal(self, market_ticker: str) -> EdgeSignal | None:
        """Get the most recent active signal for a market."""
        sig = self._active_signals.get(market_ticker)
        if sig and not sig.is_expired:
            return sig
        return None

    def clear_signal(self, market_ticker: str) -> None:
        """Remove a signal after it's been executed or rejected."""
        self._active_signals.pop(market_ticker, None)

    @property
    def active_count(self) -> int:
        """Number of non-expired active signals."""
        return sum(1 for s in self._active_signals.values() if not s.is_expired)

    def get_active_tickers(self) -> list[str]:
        """Get tickers with active (non-expired) signals."""
        return [
            ticker
            for ticker, sig in self._active_signals.items()
            if not sig.is_expired
        ]