from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from backend.core.agi_types import MarketRegime, RegimeTransition


@dataclass
class RegimeResult:
    regime: MarketRegime
    confidence: float
    indicators: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


HYSTERESIS_THRESHOLD = 0.05


class RegimeDetector:
    def __init__(self, hysteresis: float = HYSTERESIS_THRESHOLD):
        self._current_regime: MarketRegime = MarketRegime.UNKNOWN
        self._current_confidence: float = 0.0
        self._history: list[RegimeTransition] = []
        self._hysteresis = hysteresis

    def detect_regime(self, market_data: dict[str, Any]) -> RegimeResult:
        prices = market_data.get("prices", [])
        _volumes = market_data.get("volumes", [])
        sma_50 = market_data.get("sma_50")
        sma_200 = market_data.get("sma_200")
        atr = market_data.get("atr", 0.0)
        atr_percentile = market_data.get("atr_percentile", 0.5)
        drawdown = market_data.get("drawdown", 0.0)
        volume_trend = market_data.get("volume_trend", 0.0)

        if len(prices) < 30:
            return RegimeResult(
                regime=MarketRegime.UNKNOWN,
                confidence=0.0,
                indicators={"reason": "insufficient_data", "data_points": len(prices)},
            )

        # Degraded mode: with <200 points, use available data with lower confidence
        degraded = len(prices) < 200
        if degraded and sma_50 is None:
            # Compute SMA-50 from available prices if not provided
            if len(prices) >= 50:
                sma_50 = sum(prices[-50:]) / 50.0
            else:
                sma_50 = sum(prices) / len(prices)
            sma_200 = sma_50  # Can't compute SMA-200, treat as equal

        indicators = {
            "sma_50": sma_50,
            "sma_200": sma_200,
            "atr": atr,
            "atr_percentile": atr_percentile,
            "drawdown": drawdown,
            "volume_trend": volume_trend,
        }

        if drawdown > 0.15 and atr_percentile > 0.9:
            regime, confidence = MarketRegime.CRISIS, min(0.5 + drawdown + atr_percentile / 2, 1.0)
        elif sma_50 is not None and sma_200 is not None:
            sma_diff = (sma_50 - sma_200) / sma_200 if sma_200 != 0 else 0
            if sma_diff > 0.02 and atr_percentile < 0.5 and volume_trend > 0:
                regime, confidence = MarketRegime.BULL, min(0.6 + abs(sma_diff) * 5, 0.95)
            elif sma_diff < -0.02 and atr_percentile > 0.5 and volume_trend < 0:
                regime, confidence = MarketRegime.BEAR, min(0.6 + abs(sma_diff) * 5, 0.95)
            elif abs(sma_diff) <= 0.02 and atr_percentile > 0.7:
                regime, confidence = MarketRegime.SIDEWAYS_VOLATILE, min(0.5 + atr_percentile / 2, 0.9)
            elif abs(sma_diff) <= 0.02 and atr_percentile <= 0.5:
                regime, confidence = MarketRegime.SIDEWAYS, min(0.5 + (1 - atr_percentile) / 2, 0.85)
            else:
                if sma_diff > 0:
                    regime, confidence = MarketRegime.BULL, 0.4
                else:
                    regime, confidence = MarketRegime.BEAR, 0.4
        else:
            regime, confidence = MarketRegime.UNKNOWN, 0.0

        if self._current_regime != MarketRegime.UNKNOWN and regime != self._current_regime:
            if abs(confidence - self._current_confidence) < self._hysteresis:
                regime = self._current_regime
                confidence = self._current_confidence

        if regime != self._current_regime and self._current_regime != MarketRegime.UNKNOWN:
            transition = RegimeTransition(
                from_regime=self._current_regime,
                to_regime=regime,
                confidence=confidence,
                timestamp=datetime.now(timezone.utc),
            )
            self._history.append(transition)
            self._emit_regime_change(transition)

        self._current_regime = regime
        self._current_confidence = confidence

        return RegimeResult(
            regime=regime,
            confidence=confidence,
            indicators=indicators,
        )

    def get_current_regime(self) -> MarketRegime:
        return self._current_regime

    def get_regime_history(self, hours: int = 24) -> list[RegimeTransition]:
        if hours <= 0:
            return []
        cutoff = datetime.now(timezone.utc).timestamp() - (hours * 3600)
        return [t for t in self._history if t.timestamp.timestamp() >= cutoff]

    def _emit_regime_change(self, transition: RegimeTransition) -> None:
        try:
            from backend.core import event_bus
            event_bus.publish_event("regime_changed", {
                "from_regime": transition.from_regime.value,
                "to_regime": transition.to_regime.value,
                "confidence": transition.confidence,
                "timestamp": transition.timestamp.isoformat(),
            })
        except Exception:
            pass
