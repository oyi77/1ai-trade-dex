"""Whale wallet scoring formula from polyedge-production-transformation plan."""

from typing import List, Dict, Any


def calculate_whale_score(
    trades: List[Dict[str, Any]], days_active: float = 1.0
) -> float:
    """
    Score = win_rate*0.35 + clamped_roi*0.30 + clamped_size*0.20 + clamped_freq*0.15
    Each clamp normalizes its component to [0, 1].
    """
    if not trades:
        return 0.0

    n = len(trades)
    wins = sum(1 for t in trades if t.get("pnl", 0.0) > 0)
    win_rate = wins / n if n > 0 else 0.0

    total_size = sum(abs(t.get("size", 0.0)) for t in trades) or 1.0
    total_pnl = sum(t.get("pnl", 0.0) for t in trades)
    roi = total_pnl / total_size

    avg_size = total_size / n if n > 0 else 0.0
    freq = n / max(days_active, 1.0)

    clamped_roi = min(max(roi / 0.5, 0.0), 1.0)
    clamped_size = min(max(avg_size / 10000.0, 0.0), 1.0)
    clamped_freq = min(max(freq / 5.0, 0.0), 1.0)

    score = (
        win_rate * 0.35 + clamped_roi * 0.30 + clamped_size * 0.20 + clamped_freq * 0.15
    )
    return round(min(max(score, 0.0), 1.0), 4)
