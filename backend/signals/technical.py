from typing import List


def compute_sma(closes: List[float], period: int) -> float:
    if not closes:
        raise ValueError("closes must not be empty")
    if period < 1:
        raise ValueError("period must be >= 1")
    if len(closes) < period:
        return sum(closes) / len(closes)
    return sum(closes[-period:]) / period


def compute_sma_series(closes: List[float], period: int) -> List[float]:
    if period < 1:
        raise ValueError("period must be >= 1")
    return [
        sum(closes[max(0, i + 1 - period):i + 1]) / min(period, i + 1)
        for i in range(len(closes))
    ]


def compute_rsi(closes: List[float], period: int = 14) -> float:
    if period < 1:
        raise ValueError("period must be >= 1")
    if len(closes) < period + 1:
        return 50.0
    gains, losses = 0.0, 0.0
    for i in range(-period, 0):
        change = closes[i] - closes[i - 1]
        if change > 0:
            gains += change
        else:
            losses -= change
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def compute_rsi_series(closes: List[float], period: int = 14) -> List[float]:
    if period < 1:
        raise ValueError("period must be >= 1")
    out = [50.0] * min(period, len(closes))
    for i in range(period, len(closes)):
        gains, losses = 0.0, 0.0
        for j in range(i - period, i):
            delta = closes[j + 1] - closes[j]
            if delta > 0:
                gains += delta
            else:
                losses -= delta
        avg_gain = gains / period
        avg_loss = losses / period
        out.append(100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss))
    return out
