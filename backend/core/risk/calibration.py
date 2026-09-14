"""
Calibration adjustment — price bucket calibration and longshot bias tracking.
"""

from typing import Optional, Tuple
import time
from loguru import logger

from backend.config import settings


def _get_or_update_calibration_and_bias(db) -> Tuple[dict, Optional[dict]]:
    """Return cached calibration and longshot bias, updating if stale (> 5 minutes)."""
    from backend.core.learning.calibration_tracker import (
        compute_price_bucket_calibration,
    )
    from backend.core.longshot_bias import LongshotBiasDetector

    now_ts = time.time()

    # Use function attributes for caching (module-level singleton pattern)
    if not hasattr(_get_or_update_calibration_and_bias, "_calibration_cache"):
        _get_or_update_calibration_and_bias._calibration_cache = None
        _get_or_update_calibration_and_bias._calibration_cache_time = None
        _get_or_update_calibration_and_bias._longshot_bias_cache = None
        _get_or_update_calibration_and_bias._longshot_bias_cache_time = None

    # Update calibration if needed
    if (
        _get_or_update_calibration_and_bias._calibration_cache is None
        or _get_or_update_calibration_and_bias._calibration_cache_time is None
        or now_ts - _get_or_update_calibration_and_bias._calibration_cache_time > 300
    ):
        try:
            # Recalculate price bucket calibration in 5c increments
            _get_or_update_calibration_and_bias._calibration_cache = (
                compute_price_bucket_calibration(db, bucket_width=5, window_days=30)
            )
            _get_or_update_calibration_and_bias._calibration_cache_time = now_ts
        except Exception as e:
            logger.error(f"[RiskManager] Failed to update calibration cache: {e}")
            if _get_or_update_calibration_and_bias._calibration_cache is None:
                _get_or_update_calibration_and_bias._calibration_cache = {}

    # Update longshot bias if needed
    if (
        _get_or_update_calibration_and_bias._longshot_bias_cache is None
        or _get_or_update_calibration_and_bias._longshot_bias_cache_time is None
        or now_ts - _get_or_update_calibration_and_bias._longshot_bias_cache_time > 300
    ):
        try:
            detector = LongshotBiasDetector()
            # Compute longshot bias ratio from actual settled trades
            _get_or_update_calibration_and_bias._longshot_bias_cache = (
                detector.compute_longshot_bias_from_trades(
                    db, price_threshold=0.30, window_days=60
                )
            )
            _get_or_update_calibration_and_bias._longshot_bias_cache_time = now_ts
        except Exception as e:
            logger.error(f"[RiskManager] Failed to update longshot bias cache: {e}")

    return (
        _get_or_update_calibration_and_bias._calibration_cache,
        _get_or_update_calibration_and_bias._longshot_bias_cache,
    )


def _validate_trade_calibration(db, market_price, signal_win_rate):
    """Calibration adjustment logic (price bucket calibration, signal_win_rate adjustment)."""
    calibration_stats = {}
    longshot_bias_stats = {}
    if db is not None and market_price is not None and signal_win_rate is not None:
        try:
            calibration_stats, longshot_bias_stats = _get_or_update_calibration_and_bias(db)
            bucket_start = int(market_price * 100) - (int(market_price * 100) % 5)
            if bucket_start in calibration_stats:
                bucket = calibration_stats[bucket_start]
                if bucket.get("confidence", 0.0) >= 0.3:
                    adjustment = bucket["error"] * bucket["confidence"]
                    adjustment = max(-0.05, min(0.05, adjustment))
                    pre_adj = signal_win_rate
                    # CALIBRATION GUARD: never adjust swr below market_price,
                    # otherwise edge_pp = (swr - price) * 100 turns negative
                    # and the edge filter rejects EVERY trade — permanent deadlock.
                    max_down = max(0.0, pre_adj - market_price - 0.005)
                    adjustment = max(adjustment, -max_down)
                    signal_win_rate = max(
                        0.01, min(0.995, pre_adj + adjustment)
                    )
                    logger.info(
                        "[risk.calibration] Realized calibration adjustment for bucket {}c: {:.2f} -> {:.2f} (error={:.2%}, conf={:.2f})",
                        bucket_start,
                        pre_adj,
                        signal_win_rate,
                        bucket["error"],
                        bucket["confidence"],
                    )
        except Exception as e:
            logger.error(
                f"[RiskManager] Failed to apply calibration adjustment: {e}"
            )
    return signal_win_rate, calibration_stats, longshot_bias_stats