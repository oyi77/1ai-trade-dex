"""
Calibration and bias — price bucket calibration and longshot bias adjustment.
"""
import time as time_module
from typing import Optional

from loguru import logger


def get_or_update_calibration_and_bias(
    db,
    calibration_cache,
    calibration_cache_time,
    longshot_bias_cache,
    longshot_bias_cache_time,
    cache_ttl: int = 300,
) -> tuple:
    """Return cached calibration and longshot bias, updating if stale (> TTL seconds).

    Returns (calibration_cache, longshot_bias_cache) — dicts that may be empty on error.
    """
    now_ts = time_module.time()

    # Ensure cache holders exist
    if calibration_cache is None:
        calibration_cache = {}
    if longshot_bias_cache is None:
        longshot_bias_cache = {}

    # Update calibration if needed
    if (
        calibration_cache_time is None
        or now_ts - calibration_cache_time > cache_ttl
    ):
        try:
            from backend.core.learning.calibration_tracker import (
                compute_price_bucket_calibration,
            )
            calibration_cache = compute_price_bucket_calibration(
                db, bucket_width=5, window_days=30
            )
            calibration_cache_time = now_ts
        except Exception as e:
            logger.error(f"[RiskManager] Failed to update calibration cache: {e}")

    # Update longshot bias if needed
    if (
        longshot_bias_cache_time is None
        or now_ts - longshot_bias_cache_time > cache_ttl
    ):
        try:
            from backend.core.longshot_bias import LongshotBiasDetector
            detector = LongshotBiasDetector()
            longshot_bias_cache = detector.compute_longshot_bias_from_trades(
                db, price_threshold=0.30, window_days=60
            )
            longshot_bias_cache_time = now_ts
        except Exception as e:
            logger.error(f"[RiskManager] Failed to update longshot bias cache: {e}")

    return calibration_cache, calibration_cache_time, longshot_bias_cache, longshot_bias_cache_time


def validate_trade_calibration(
    db, market_price, signal_win_rate
):
    """Calibration adjustment logic (price bucket calibration, signal_win_rate adjustment).

    Returns (signal_win_rate, calibration_stats, longshot_bias_stats).
    """
    calibration_stats = {}
    longshot_bias_stats = {}
    # This is a stub — actual implementation needs access to RiskManager's
    # _calibration_cache and _longshot_bias_cache. The RiskManager calls
    # get_or_update_calibration_and_bias and then applies the adjustment inline.
    return signal_win_rate, calibration_stats, longshot_bias_stats
