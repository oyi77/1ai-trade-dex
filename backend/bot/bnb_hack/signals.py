from typing import Any, Dict

from backend.bot.bnb_hack.data_feed import BinanceFeed
from backend.config import settings
from backend.signals.technical import compute_sma


class SignalEngine:
    def __init__(self, feed: BinanceFeed):
        self._feed = feed

    async def evaluate(self) -> Dict[str, Any]:
        klines = await self._feed.get_klines(
            "BNBUSDT", settings.bnb_hack.timeframe, limit=100
        )
        if not klines or len(klines) < settings.bnb_hack.sma_slow + 5:
            return {"action": "hold", "confidence": 0.0,
                    "reason": "insufficient_data", "price": 0.0, "indicators": {}}

        closes = [float(k[4]) for k in klines]
        price = float(klines[-1][4])

        sma_fast = compute_sma(closes, settings.bnb_hack.sma_fast)
        sma_slow = compute_sma(closes, settings.bnb_hack.sma_slow)
        sma_fast_prev = compute_sma(closes[:-1], settings.bnb_hack.sma_fast)
        sma_slow_prev = compute_sma(closes[:-1], settings.bnb_hack.sma_slow)

        golden_cross = sma_fast_prev <= sma_slow_prev and sma_fast > sma_slow
        death_cross = sma_fast_prev >= sma_slow_prev and sma_fast < sma_slow

        action = "hold"
        confidence = 0.5
        reason = "neutral"

        if golden_cross:
            action = "buy"
            confidence = 0.70
            reason = "golden_cross"
        elif death_cross:
            action = "sell"
            confidence = 0.70
            reason = "death_cross"

        return {
            "action": action,
            "confidence": confidence,
            "price": price,
            "reason": reason,
            "indicators": {
                "price": round(price, 2),
                "sma_fast": round(sma_fast, 2),
                "sma_slow": round(sma_slow, 2),
                "sma_cross": "golden" if golden_cross
                             else ("death" if death_cross
                                   else ("up" if sma_fast > sma_slow else "down")),
            },
        }
