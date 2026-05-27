"""
DEPRECATED: Use backend.core.calibration instead.
This module will be removed in a future release.

Forecast sigma (uncertainty) calibration per city and source.

Tracks resolved weather markets and adaptively recalibrates forecast
uncertainty (sigma) per city/source. Calibrated sigma improves the
Gaussian probability model's accuracy over time.
"""



import json
import math
import threading
from pathlib import Path
from typing import Dict, Optional

from loguru import logger

from backend.models.database import Trade

BUCKETS = [
    (0, 10),
    (10, 20),
    (20, 30),
    (30, 40),
    (40, 50),
    (50, 60),
    (60, 70),
    (70, 80),
    (80, 90),
    (90, 100),
]


def _price_to_bucket(price: float) -> tuple[float, float]:
    """Return the bucket (low, high) for a price in [0, 1] range."""
    pct = price * 100
    for lo, hi in BUCKETS:
        if lo <= pct < hi:
            return (lo, hi)
    return (90, 100)  # fallback for 0.95+


def get_bucket_win_rate(
    price: float, strategy: str, lookback: int = 200
) -> Optional[float]:
    """Return realized win rate for the price bucket of the given strategy.

    Args:
        price: Entry price in [0, 1] range (e.g. 0.47 for 47c)
        strategy: Strategy name (e.g. "btc_oracle")
        lookback: Max trades to consider (default 200)

    Returns:
        Realized win rate (0.0-1.0) if >= 10 samples, else None.
    """
    from backend.db.utils import get_db_session

    lo, hi = _price_to_bucket(price)
    lo_frac = lo / 100.0
    hi_frac = hi / 100.0

    with get_db_session() as db:
        trades = (
            db.query(Trade)
            .filter(Trade.strategy == strategy)
            .filter(Trade.settled.is_(True))
            .filter(Trade.entry_price >= lo_frac)
            .filter(Trade.entry_price < hi_frac)
            .filter(Trade.settlement_value.isnot(None))
            .order_by(Trade.timestamp.desc())
            .limit(lookback)
            .all()
        )

    if len(trades) < 10:
        return None

    wins = sum(1 for t in trades if t.__dict__.get("settlement_value", 0) == 1.0)
    return wins / len(trades)


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


def kelly_fraction(
    win_prob: float,
    price: float,
    kelly_multiplier: float = 1.0,
    cap: float = 0.25,
) -> float:
    """
    Compute Kelly position sizing fraction for a prediction-market bet.

    For a YES share bought at ``price`` that pays $1 on win:
        profit-on-win per $1 staked  b = (1 - price) / price
        kelly f* = p - (1 - p) / b   =   (p - price) / (1 - price)

    Args:
        win_prob: Estimated probability the share resolves YES (0.0–1.0).
        price: Current market price of the share (0.0–1.0, exclusive).
        kelly_multiplier: Scaling factor (e.g. 0.5 for half-Kelly).
        cap: Hard upper bound on returned fraction (defaults to 25% of bankroll).

    Returns:
        Fraction of bankroll to stake. 0.0 when the bet has no positive edge or
        when inputs are out of bounds.
    """
    try:
        p = float(win_prob)
        q = float(price)
    except (TypeError, ValueError):
        return 0.0

    # Degenerate / out-of-range inputs → no bet.
    if not (0.0 < p < 1.0) or not (0.0 < q < 1.0):
        return 0.0

    edge = p - q
    if edge <= 0.0:
        return 0.0

    # Kelly fraction for binary payoff at price q.
    f_star = edge / (1.0 - q)

    # Apply user multiplier (half-Kelly, quarter-Kelly, etc.) and clamp.
    f_scaled = f_star * max(0.0, float(kelly_multiplier))
    if f_scaled <= 0.0:
        return 0.0
    if cap is not None and f_scaled > cap:
        return float(cap)
    return float(f_scaled)


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
