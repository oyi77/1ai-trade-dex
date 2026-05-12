"""
Forecast sigma (uncertainty) calibration per city and source.

Tracks resolved weather markets and adaptively recalibrates forecast
uncertainty (sigma) per city/source. Calibrated sigma improves the
Gaussian probability model's accuracy over time.
"""

import json
import math
import threading
from pathlib import Path
from typing import Dict

from loguru import logger
# Default sigma values (°F) before calibration
DEFAULT_SIGMA_F = 2.5  # US cities (°F)
DEFAULT_SIGMA_C = 1.4  # Non-US cities (°C, converted to effective °F)

# Minimum resolved markets before trusting calibration
MIN_CALIBRATION_SAMPLES = 20

_CALIBRATION_FILE = Path("data/calibration.json")
_cal_cache: Dict[str, dict] = {}
_cal_lock = threading.Lock()


def _load() -> Dict[str, dict]:
    global _cal_cache
    with _cal_lock:
        if not _cal_cache and _CALIBRATION_FILE.exists():
            try:
                _cal_cache = json.loads(_CALIBRATION_FILE.read_text(encoding="utf-8"))
            except Exception as e:
                logger.debug(f"Failed to load calibration file: {e}")
                _cal_cache = {}
        return _cal_cache


def get_sigma(city_key: str, source: str = "gefs") -> float:
    """
    Return calibrated forecast sigma for a city/source pair.
    Falls back to default if not enough resolved markets.
    """
    cal = _load()
    key = f"{city_key}_{source}"
    entry = cal.get(key)
    if entry and entry.get("n", 0) >= MIN_CALIBRATION_SAMPLES:
        return float(entry["sigma"])
    # Default: US cities in °F, others effectively in °F after conversion
    from backend.data.weather import CITY_CONFIG

    unit = CITY_CONFIG.get(city_key, {}).get("unit", "F")
    return DEFAULT_SIGMA_F if unit == "F" else DEFAULT_SIGMA_C * 1.8  # rough C→F scale


def update_calibration(
    city_key: str, source: str, forecast_temp_f: float, actual_temp_f: float
) -> None:
    """
    Update calibration with a resolved market outcome.
    Uses online Welford algorithm for running mean/variance.
    """
    cal = _load()
    key = f"{city_key}_{source}"

    error = abs(forecast_temp_f - actual_temp_f)
    entry = cal.get(
        key, {"n": 0, "mean_error": 0.0, "M2": 0.0, "sigma": DEFAULT_SIGMA_F}
    )

    n = entry["n"] + 1
    delta = error - entry["mean_error"]
    mean_error = entry["mean_error"] + delta / n
    delta2 = error - mean_error
    M2 = entry["M2"] + delta * delta2

    sigma = math.sqrt(M2 / (n - 1)) if n > 1 else DEFAULT_SIGMA_F

    cal[key] = {"n": n, "mean_error": mean_error, "M2": M2, "sigma": sigma}
    with _cal_lock:
        _cal_cache.update(cal)

    _CALIBRATION_FILE.parent.mkdir(exist_ok=True)
    _CALIBRATION_FILE.write_text(json.dumps(cal, indent=2), encoding="utf-8")
    logger.info(f"Calibration updated: {key} n={n} sigma={sigma:.2f}°F")


def get_calibration_report() -> str:
    """Return human-readable calibration status."""
    cal = _load()
    if not cal:
        return "No calibration data yet."
    lines = ["Calibration Report:", "=" * 40]
    for key, entry in sorted(cal.items()):
        lines.append(
            f"  {key:30s} n={entry['n']:3d}  sigma={entry['sigma']:.2f}°F  "
            f"mean_err={entry['mean_error']:.2f}°F"
            + (
                "  ✓ ACTIVE"
                if entry["n"] >= MIN_CALIBRATION_SAMPLES
                else "  (warming up)"
            )
        )
    return "\n".join(lines)
