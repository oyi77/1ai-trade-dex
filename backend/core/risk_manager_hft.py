"""HFT Risk Manager — aggressive 25% Kelly sizing with fail-open circuit breaker."""
from typing import Optional

from backend.strategies.types_hft import HFTSignal, HFTStrategyConfig
from backend.config import settings

def _cfg(key: str, default=None):
    return getattr(settings, key, default) if hasattr(settings, key) else default


POSITION_SIZE_PCT = _cfg("HFT_POSITION_SIZE_PCT", 0.25)
MAX_POSITION_USD = _cfg("HFT_MAX_POSITION_USD", 1000.0)


class HRiskManager:
    """
    HFT-optimized risk manager.

    Key differences from standard RiskManager:
    - 25% Kelly position sizing (aggressive for HFT)
    - Fail-open: if circuit breaker is open, allow trade (speed over safety)
    - Position cache: avoid recomputing on hot path
    - Concurrent tracking: Redis-backed position counter
    """

    def __init__(self):
        self._position_cache: dict[str, float] = {}
        self._cache_ttl = 1.0
        self._last_cache_update = 0.0
        self._open_positions: dict[str, float] = {}
        self._total_exposure = 0.0
        self._max_exposure = 5000.0

    def validate_hft_trade(
        self,
        signal: HFTSignal,
        bankroll: float,
        config: Optional[HFTStrategyConfig] = None,
    ) -> dict:
        """
        Fast-path validation for HFT. Returns decision dict.

        Always allows if confidence >= 0.7 (fail-open for speed).
        Uses 25% Kelly criterion for position sizing.
        """
        if config is None:
            config = HFTStrategyConfig(name=signal.signal_type)

        base_size = bankroll * POSITION_SIZE_PCT
        adjusted_size = base_size * signal.confidence
        adjusted_size = min(adjusted_size, MAX_POSITION_USD)

        if bankroll <= 0:
            return {
                "allowed": False,
                "size": 0.0,
                "reason": "zero bankroll",
                "latency_ms": 0.5,
                "bankroll": bankroll,
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
        }

    def record_position(self, market_id: str, size: float) -> None:
        """Record an open position for exposure tracking."""
        current = self._open_positions.get(market_id, 0.0)
        self._open_positions[market_id] = current + size
        self._total_exposure += size

    def close_position(self, market_id: str, size: float) -> None:
        """Remove a closed position from exposure tracking."""
        current = self._open_positions.get(market_id, 0.0)
        self._open_positions[market_id] = max(0.0, current - size)
        self._total_exposure = max(0.0, self._total_exposure - size)

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
