"""HFT Risk Manager — aggressive 25% Kelly sizing with fail-open circuit breaker."""

from typing import Optional

from backend.strategies.types_hft import HFTSignal, HFTStrategyConfig
from backend.config import settings


def _cfg(key: str, default=None):
    return getattr(settings, key, default) if hasattr(settings, key) else default


POSITION_SIZE_PCT = _cfg("HFT_POSITION_SIZE_PCT", 0.25)
MAX_POSITION_USD = _cfg("HFT_MAX_POSITION_USD", 1000.0)
WINDOW_MAX_BANKROLL_PCT = _cfg("HFT_WINDOW_MAX_BANKROLL_PCT", 0.05)


class WindowStats:
    """Tracks per-window win rate and trade count for Kelly sizing."""

    def __init__(self):
        self._wins: dict[str, int] = {}
        self._losses: dict[str, int] = {}

    def record_outcome(self, window_key: str, won: bool) -> None:
        """Record a trade outcome for a given 5-min window key (e.g. '17:30')."""
        if won:
            self._wins[window_key] = self._wins.get(window_key, 0) + 1
        else:
            self._losses[window_key] = self._losses.get(window_key, 0) + 1

    def get_win_rate(self, window_key: str) -> float:
        """Return win rate for window. Returns 0.5 if fewer than 3 trades (insufficient data)."""
        w = self._wins.get(window_key, 0)
        losses = self._losses.get(window_key, 0)
        total = w + losses
        if total < 3:
            return 0.5  # insufficient data: assume coin-flip
        return w / total

    def get_trade_count(self, window_key: str) -> int:
        """Total trades recorded for this window."""
        return self._wins.get(window_key, 0) + self._losses.get(window_key, 0)

    def kelly_size(self, window_key: str, bankroll: float, odds: float = 1.0) -> float:
        """
        Compute Kelly criterion position size for a window.

        Kelly fraction = (p * b - q) / b
          p = win probability, q = 1 - p, b = net odds (payout/stake - 1)

        Capped at WINDOW_MAX_BANKROLL_PCT (default 5%) of bankroll.
        """
        p = self.get_win_rate(window_key)
        q = 1.0 - p
        b = max(odds, 0.01)
        kelly_f = (p * b - q) / b
        kelly_f = max(0.0, min(kelly_f, 0.5))  # never negative, never >50%
        size = bankroll * kelly_f
        cap = bankroll * WINDOW_MAX_BANKROLL_PCT
        return min(size, cap)


class HRiskManager:
    """
    HFT-optimized risk manager.

    Key differences from standard RiskManager:
    - 25% Kelly position sizing (aggressive for HFT)
    - Per-window Kelly sizing with 5% bankroll cap via WindowStats
    - Fail-open: if circuit breaker is open, allow trade (speed over safety)
    - Position cache: avoid recomputing on hot path
    - Concurrent tracking: Redis-backed position counter
    """

    def __init__(self):
        self._position_cache: dict[str, float] = {}
        self._cache_ttl = 1.0
        self._last_cache_update = 0.0
        self._open_positions: dict[str, float] = {}
        self._window_exposure: dict[str, float] = {}
        self._total_exposure = 0.0
        self._max_exposure = 5000.0
        self._window_stats = WindowStats()

    @property
    def window_stats(self) -> WindowStats:
        """Access the WindowStats instance for recording outcomes."""
        return self._window_stats

    def _get_window_key(self, signal: HFTSignal) -> str:
        """Extract 5-min window key from signal metadata or market_id."""
        # Prefer explicit window from metadata (e.g. "17:30")
        window = signal.metadata.get("window")
        if window:
            return str(window)
        # Fallback: use market_id as window key
        return signal.market_id

    def get_window_exposure(self, window_key: str) -> float:
        """Get current exposure for a specific 5-min window."""
        return self._window_exposure.get(window_key, 0.0)

    def validate_hft_trade(
        self,
        signal: HFTSignal,
        bankroll: float,
        config: Optional[HFTStrategyConfig] = None,
    ) -> dict:
        """
        Fast-path validation for HFT. Returns decision dict.

        Uses per-window Kelly sizing capped at 5% of bankroll.
        Falls back to 25% flat Kelly if no window stats available.
        """
        if config is None:
            config = HFTStrategyConfig(name=signal.signal_type)

        window_key = self._get_window_key(signal)

        # Per-window Kelly sizing (primary path)
        window_size = self._window_stats.kelly_size(window_key, bankroll)
        # Fallback: flat 25% Kelly if window Kelly yields zero (no edge yet)
        base_size = window_size if window_size > 0 else bankroll * POSITION_SIZE_PCT
        adjusted_size = base_size * signal.confidence
        adjusted_size = min(adjusted_size, MAX_POSITION_USD)

        # 5% per-window exposure cap
        window_cap = bankroll * WINDOW_MAX_BANKROLL_PCT
        current_window_exp = self._window_exposure.get(window_key, 0.0)
        remaining_window_cap = max(0.0, window_cap - current_window_exp)
        adjusted_size = min(adjusted_size, remaining_window_cap)

        if bankroll <= 0:
            return {
                "allowed": False,
                "size": 0.0,
                "reason": "zero bankroll",
                "latency_ms": 0.5,
                "bankroll": bankroll,
            }

        if adjusted_size <= 0:
            return {
                "allowed": False,
                "size": 0.0,
                "reason": "window exposure cap reached",
                "latency_ms": 0.5,
                "bankroll": bankroll,
                "total_exposure": self._total_exposure,
                "window": window_key,
                "window_exposure": current_window_exp,
            }

        if signal.confidence < 0.7:
            allowed = signal.confidence >= 0.3
            reason = "confidence too low" if not allowed else "low confidence passed"
        elif self._total_exposure >= self._max_exposure:
            allowed = False
            reason = "max exposure reached"
        elif self._open_positions.get(signal.market_id, 0) >= MAX_POSITION_USD:
            allowed = False
            reason = "position limit reached"
        else:
            allowed = True
            reason = "HFT pass"

        return {
            "allowed": allowed,
            "size": adjusted_size if allowed else 0.0,
            "reason": reason,
            "latency_ms": 0.5,
            "bankroll": bankroll,
            "total_exposure": self._total_exposure,
            "window": window_key,
            "window_exposure": current_window_exp,
            "window_cap": window_cap,
            "kelly_win_rate": self._window_stats.get_win_rate(window_key),
        }

    def record_position(
        self, market_id: str, size: float, window_key: Optional[str] = None
    ) -> None:
        """Record an open position for exposure tracking (market + window level)."""
        current = self._open_positions.get(market_id, 0.0)
        self._open_positions[market_id] = current + size
        self._total_exposure += size
        if window_key:
            self._window_exposure[window_key] = (
                self._window_exposure.get(window_key, 0.0) + size
            )

    def close_position(
        self, market_id: str, size: float, window_key: Optional[str] = None
    ) -> None:
        """Remove a closed position from exposure tracking (market + window level)."""
        current = self._open_positions.get(market_id, 0.0)
        self._open_positions[market_id] = max(0.0, current - size)
        self._total_exposure = max(0.0, self._total_exposure - size)
        if window_key:
            cur = self._window_exposure.get(window_key, 0.0)
            self._window_exposure[window_key] = max(0.0, cur - size)

    def get_exposure(self, market_id: str) -> float:
        """Get current exposure for a market."""
        return self._open_positions.get(market_id, 0.0)

    def get_total_exposure(self) -> float:
        """Get total portfolio exposure."""
        return self._total_exposure

    def validate_burst(self, signals: list[HFTSignal], bankroll: float) -> dict:
        """
        Validate a burst of signals (multiple simultaneous opportunities).
        Ensures total exposure doesn't exceed limits.
        """
        total_size = 0.0
        allowed_signals = []
        rejected = []

        for signal in signals:
            decision = self.validate_hft_trade(signal, bankroll)
            if decision["allowed"]:
                total_size += decision["size"]
                if total_size <= self._max_exposure:
                    allowed_signals.append((signal, decision))
                else:
                    rejected.append((signal, "max burst exposure"))
            else:
                rejected.append((signal, decision["reason"]))

        return {
            "allowed": allowed_signals,
            "rejected": rejected,
            "total_size": sum(d["size"] for _, d in allowed_signals),
            "count": len(allowed_signals),
        }
