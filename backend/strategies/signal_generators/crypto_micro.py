"""CryptoMicroSignalGenerator — Binance kline-based signals.

Generates signals from crypto microstructure data (RSI, momentum,
VWAP deviation, SMA crossover) fetched from Binance klines.
"""

from __future__ import annotations

from typing import Any


from backend.strategies.signal_generators.base import Signal, SignalGenerator


def _compute_rsi(closes: list[float], period: int = 14) -> float | None:
    """Compute RSI from a list of closing prices."""
    if len(closes) < period + 1:
        return None
    gains = []
    losses = []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(0.0, delta))
        losses.append(max(0.0, -delta))

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _compute_vwap_deviation(closes: list[float], volumes: list[float]) -> float | None:
    """Compute deviation of current price from VWAP."""
    if not closes or not volumes or len(closes) != len(volumes):
        return None
    total_vol = sum(volumes)
    if total_vol == 0:
        return None
    vwap = sum(c * v for c, v in zip(closes, volumes)) / total_vol
    if vwap == 0:
        return None
    return (closes[-1] - vwap) / vwap


def _compute_sma_crossover(
    closes: list[float], short: int = 5, long: int = 20
) -> float | None:
    """Compute SMA crossover ratio (short - long) / long."""
    if len(closes) < long:
        return None
    sma_short = sum(closes[-short:]) / short
    sma_long = sum(closes[-long:]) / long
    if sma_long == 0:
        return None
    return (sma_short - sma_long) / sma_long


class CryptoMicroSignalGenerator(SignalGenerator):
    """Generates signals from Binance kline microstructure data.

    Expects each market dict to contain:
        - 'ticker': str
        - 'klines': list of {'close': float, 'volume': float, 'timestamp': float}
    """

    @property
    def name(self) -> str:
        return "crypto_micro"

    @property
    def description(self) -> str:
        return (
            "Crypto microstructure signals from Binance klines. "
            "Computes RSI, momentum, VWAP deviation, SMA crossover."
        )

    async def generate(
        self,
        markets: list[dict[str, Any]],
        params: dict[str, Any] | None = None,
    ) -> list[Signal]:
        params = params or {}
        signals: list[Signal] = []

        for market in markets:
            ticker = market.get("ticker", "")
            klines = market.get("klines")
            if not klines or len(klines) < 20:
                continue

            closes = [k["close"] for k in klines]
            volumes = [k.get("volume", 0.0) for k in klines]

            rsi = _compute_rsi(closes)
            if rsi is None:
                continue

            # 5-min momentum: price change rate
            momentum_5m = (
                (closes[-1] - closes[-6]) / closes[-6]
                if len(closes) >= 6 and closes[-6] != 0
                else 0.0
            )

            vwap_dev = _compute_vwap_deviation(closes, volumes) or 0.0
            sma_cross = _compute_sma_crossover(closes) or 0.0

            # Composite signal strength
            rsi_norm = (rsi - 50.0) / 50.0
            mom_signal = max(-1.0, min(1.0, momentum_5m * 10.0))
            vwap_signal = max(-1.0, min(1.0, vwap_dev * 100.0))
            sma_signal = max(-1.0, min(1.0, sma_cross * 100.0))

            composite = (
                rsi_norm * 0.25
                + mom_signal * 0.30
                + vwap_signal * 0.25
                + sma_signal * 0.20
            )

            if abs(composite) < 0.1:  # below signal threshold
                continue

            signals.append(
                Signal(
                    signal_type="crypto_micro",
                    strength=composite,
                    confidence=min(1.0, abs(composite)),
                    market_ticker=ticker,
                    data={
                        "rsi": rsi,
                        "momentum_5m": momentum_5m,
                        "vwap_deviation": vwap_dev,
                        "sma_crossover": sma_cross,
                        "composite": composite,
                    },
                    reasoning=(
                        f"Crypto micro: RSI={rsi:.1f}, mom={momentum_5m:.4f}, "
                        f"VWAP={vwap_dev:.4f}, SMA={sma_cross:.4f}"
                    ),
                )
            )

        return signals
