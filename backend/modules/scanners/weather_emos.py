"""
Weather EMOS (Ensemble Model Output Statistics) Strategy.

Uses EMOS calibration with a 30-40 day rolling window to produce calibrated
temperature probability forecasts, then compares to Polymarket market mid-prices
to find tradeable edges.

Data sources (all free, no auth required):
- Open-Meteo API: current + ensemble forecasts (https://api.open-meteo.com)
- NOAA NBM (National Blend of Models): probabilistic percentile forecasts
- Polymarket Gamma API: weather market prices (via market_scanner)

EMOS calibration:
- Collects (ensemble_mean, ensemble_std, verifying_obs) triplets over rolling window
- Fits linear correction: calibrated_mean = a + b * ensemble_mean
- Computes Pr(T > threshold) using calibrated normal distribution
- Minimum N=10 observations required before firing (SKIP otherwise)

Decision logic:
- If |calibrated_p - market_mid| > min_edge: BUY
- Always writes DecisionLog with full signal_data for ML training
"""

import asyncio
import json
import math
from dataclasses import dataclass, field
from typing import Any

import httpx

from backend.strategies.base import (
    BaseStrategy,
    StrategyContext,
    CycleResult,
    MarketEvent,
)
from backend.core.market_scanner import MarketInfo
from backend.core.decisions import record_decision
from backend.core.activity_logger import activity_logger
from backend.config import settings, _cfg
from backend.models.database import for_update


from loguru import logger  # noqa: E402

OPEN_METEO_BASE = settings.OPEN_METEO_API_URL
NBM_BASE = settings.NWS_API_URL

# Major US cities: (name, lat, lon, NWS office, grid_x, grid_y)
DEFAULT_CITIES = [
    ("New York", 40.7128, -74.0060, "OKX", 33, 37),
    ("Chicago", 41.8781, -87.6298, "LOT", 74, 73),
    ("Miami", 25.7617, -80.1918, "MFL", 110, 39),
    ("Denver", 39.7392, -104.9903, "BOU", 57, 63),
    ("Los Angeles", 34.0522, -118.2437, "LOX", 141, 39),
    ("Dallas", 32.7767, -96.7970, "FWD", 82, 101),
    ("Seattle", 47.6062, -122.3321, "SEW", 124, 69),
    ("Atlanta", 33.7490, -84.3880, "FFC", 52, 57),
]


@dataclass
class ForecastPoint:
    city: str
    lat: float
    lon: float
    forecast_high_f: float | None = None  # predicted max temp (Fahrenheit)
    forecast_low_f: float | None = None  # predicted min temp (Fahrenheit)
    ensemble_std: float = 5.0  # ensemble spread in F
    nbm_p10: float | None = None  # NBM 10th percentile MaxT
    nbm_p50: float | None = None  # NBM 50th percentile MaxT (median)
    nbm_p90: float | None = None  # NBM 90th percentile MaxT
    source: str = "open_meteo"


@dataclass
class CalibrationState:
    """Rolling EMOS calibration state for one city."""

    obs_pairs: list[tuple[float, float, float]] = field(default_factory=list)
    a: float = 0.0
    b: float = 1.0
    last_updated: str | None = None
    _persistence_path: str | None = None
    _city: str | None = None
    use_db_persistence: bool = False

    @property
    def n(self) -> int:
        return len(self.obs_pairs)

    def set_persistence_path(self, path: str):
        self._persistence_path = path

    def set_city(self, city: str):
        self._city = city

    def _save_db(self) -> bool:
        """Save calibration state to DB. Returns True on success."""
        if not self._city:
            return False
        try:
            from backend.models.database import SessionLocal, EMOSCalibrationState
            from datetime import datetime as _dt

            db = SessionLocal()
            try:
                row = db.query(EMOSCalibrationState).filter_by(city=self._city).first()
                payload = json.dumps(self.obs_pairs)
                last_updated_dt = None
                if self.last_updated:
                    try:
                        last_updated_dt = _dt.fromisoformat(self.last_updated)
                    except Exception:
                        logger.exception(
                            "weather_emos: failed to parse last_updated timestamp"
                        )
                        last_updated_dt = None
                if row is None:
                    row = EMOSCalibrationState(
                        city=self._city,
                        obs_pairs_json=payload,
                        a=self.a,
                        b=self.b,
                        last_updated=last_updated_dt,
                    )
                    db.add(row)
                else:
                    row.obs_pairs_json = payload
                    row.a = self.a
                    row.b = self.b
                    row.last_updated = last_updated_dt
                db.commit()
                return True
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"EMOS DB save failed for {self._city}: {e}")
            return False

    def _load_db(self) -> bool:
        """Load calibration state from DB. Returns True on success."""
        if not self._city:
            return False
        try:
            from backend.models.database import SessionLocal, EMOSCalibrationState

            db = SessionLocal()
            try:
                row = db.query(EMOSCalibrationState).filter_by(city=self._city).first()
                if row is None:
                    return False
                try:
                    pairs = json.loads(row.obs_pairs_json or "[]")
                except Exception:
                    logger.exception("Failed to parse obs_pairs_json from database")
                    pairs = []
                    pairs = []
                self.obs_pairs = [tuple(p) for p in pairs]
                self.a = row.a if row.a is not None else 0.0
                self.b = row.b if row.b is not None else 1.0
                self.last_updated = (
                    row.last_updated.isoformat() if row.last_updated else None
                )
                return True
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"EMOS DB load failed for {self._city}: {e}")
            return False

    def save(self):
        if self.use_db_persistence:
            if self._save_db():
                return
            # Fall through to filesystem fallback on DB failure
        if self._persistence_path is None:
            return
        import json

        data = {
            "obs_pairs": self.obs_pairs,
            "a": self.a,
            "b": self.b,
            "last_updated": self.last_updated,
        }
        with open(self._persistence_path, "w") as f:
            json.dump(data, f)

    def load(self):
        if self.use_db_persistence:
            if self._load_db():
                return
            # Fall through to filesystem fallback on DB failure / missing row
        if self._persistence_path is None:
            return
        import json
        import os

        if not os.path.exists(self._persistence_path):
            return
        with open(self._persistence_path, "r") as f:
            data = json.load(f)
        self.obs_pairs = [tuple(p) for p in data.get("obs_pairs", [])]
        self.a = data.get("a", 0.0)
        self.b = data.get("b", 1.0)
        self.last_updated = data.get("last_updated")

    def add_observation(
        self, forecast_mean: float, forecast_std: float, actual: float, window: int = 40
    ):
        self.obs_pairs.append((forecast_mean, forecast_std, actual))
        if len(self.obs_pairs) > window:
            self.obs_pairs = self.obs_pairs[-window:]
        if self.n >= 3:
            self._refit()

    def _refit(self):
        """Simple linear regression: calibrated_mean = a + b * forecast_mean."""
        n = self.n
        xs = [p[0] for p in self.obs_pairs]
        ys = [p[2] for p in self.obs_pairs]
        x_mean = sum(xs) / n
        y_mean = sum(ys) / n
        num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
        den = sum((x - x_mean) ** 2 for x in xs)
        self.b = num / den if den != 0 else 1.0
        self.a = y_mean - self.b * x_mean

    def calibrate(self, forecast_mean: float) -> float:
        return self.a + self.b * forecast_mean

    def residual_std(self) -> float:
        """RMSE of calibrated forecasts vs actuals."""
        if self.n < 3:
            return 5.0  # prior: 5F uncertainty
        calibrated = [self.calibrate(p[0]) for p in self.obs_pairs]
        errors = [(c - p[2]) ** 2 for c, p in zip(calibrated, self.obs_pairs)]
        return math.sqrt(sum(errors) / len(errors))


CATEGORY_WEATHER_WEIGHTS = {
    "sports": 1.5,
    "entertainment": 1.5,
    "pop culture": 1.5,
    "retail": 1.5,
    "politics": 0.8,
    "crypto": 0.5,
    "economy": 0.2,
    "financials": 0.2,
    "macroeconomics": 0.2,
    "general": 1.0,
}


def normal_cdf(x: float, mean: float, std: float) -> float:
    """Cumulative distribution function of normal distribution."""
    if std <= 0:
        return 1.0 if x >= mean else 0.0
    return 0.5 * (1.0 + math.erf((x - mean) / (std * math.sqrt(2))))


def pr_exceeds_threshold(
    threshold_f: float, calibrated_mean: float, calibrated_std: float
) -> float:
    """P(T > threshold) using calibrated normal distribution."""
    return 1.0 - normal_cdf(threshold_f, calibrated_mean, calibrated_std)


def _calculate_weather_kelly_size(
    edge: float,
    probability: float,
    market_price: float,
    direction: str,
    bankroll: float,
) -> float:
    if market_price <= 0 or market_price >= 1:
        return 10.0

    b = (1.0 - market_price) / market_price
    p = probability
    q = 1.0 - p
    kelly_full = (p * b - q) / b if b != 0 else 0

    kelly_fraction = _cfg("WEATHER_KELLY_FRACTION", 0.15)
    kelly_fractional = max(0.0, kelly_full * kelly_fraction)

    size = kelly_fractional * bankroll

    max_fraction = _cfg("WEATHER_MAX_BANKROLL_FRACTION", 0.05)
    size = min(size, bankroll * max_fraction)

    return max(10.0, size)


async def fetch_open_meteo_forecast(lat: float, lon: float) -> dict[str, Any]:
    """Fetch daily temperature forecast from Open-Meteo API (free, no auth)."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_max,temperature_2m_min",
        "temperature_unit": "fahrenheit",
        "timezone": "auto",
        "forecast_days": 3,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{OPEN_METEO_BASE}/forecast", params=params)
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        logger.warning(f"Open-Meteo fetch failed for ({lat},{lon}): {e}")
    return {}


def extract_threshold_from_question(question: str) -> tuple[float | None, str | None]:
    """
    Extract temperature threshold and direction from market question.
    e.g. "Will NYC max temp exceed 85°F on June 15?" -> (85.0, "above")
    Returns (threshold_f, direction) or (None, None) if cannot parse.
    """
    import re

    q = question.lower()
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:°f|°f|f|degrees?)", q)
    if not match:
        return None, None
    threshold = float(match.group(1))
    is_above = any(w in q for w in ["exceed", "above", "over", "high", "warm", "hot"])
    is_below = any(w in q for w in ["below", "under", "low", "cold", "cool"])
    direction = "above" if is_above else ("below" if is_below else "above")
    return threshold, direction


def load_calibration_states(db, strategy_name: str) -> dict[str, CalibrationState]:
    """Load EMOS calibration states from BotState JSON blob."""
    if db is None:
        return {}
    try:
        from backend.models.database import BotState

        state = db.query(BotState).first()
        if state and state.misc_data:
            data = (
                json.loads(state.misc_data)
                if isinstance(state.misc_data, str)
                else state.misc_data
            )
            cal_data = data.get(f"emos_calibration_{strategy_name}", {})
            result = {}
            for city, cal_dict in cal_data.items():
                cs = CalibrationState(
                    obs_pairs=[tuple(p) for p in cal_dict.get("obs_pairs", [])],
                    a=cal_dict.get("a", 0.0),
                    b=cal_dict.get("b", 1.0),
                    last_updated=cal_dict.get("last_updated"),
                )
                result[city] = cs
            return result
    except Exception as e:
        logger.warning(f"Could not load calibration states (using empty state): {e}")
    return {}


def save_calibration_states(
    db, strategy_name: str, states: dict[str, CalibrationState]
):
    """Persist EMOS calibration states to BotState JSON blob."""
    try:
        from backend.models.database import BotState

        state = for_update(db, db.query(BotState)).first()
        if not state:
            return
        existing = {}
        if state.misc_data:
            try:
                existing = (
                    json.loads(state.misc_data)
                    if isinstance(state.misc_data, str)
                    else dict(state.misc_data)
                )
            except Exception:
                logger.exception("Failed to parse misc_data JSON for calibration state")
                existing = {}
        cal_key = f"emos_calibration_{strategy_name}"
        existing[cal_key] = {
            city: {
                "obs_pairs": cs.obs_pairs,
                "a": cs.a,
                "b": cs.b,
                "last_updated": cs.last_updated,
                "n": cs.n,
            }
            for city, cs in states.items()
        }
        state.misc_data = json.dumps(existing)
        try:
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                logger.exception(
                    "Failed to rollback DB after calibration commit failure"
                )
            raise
    except Exception as e:
        logger.warning(f"Could not save calibration states: {e}")


class WeatherEMOSStrategy(BaseStrategy):
    name = "weather_emos"
    description = (
        "Weather trading with EMOS calibration. Uses Open-Meteo ensemble forecasts "
        "calibrated against observations to compute Pr(T > threshold). "
        "Fires when calibrated edge > min_edge. Requires N>=10 obs to activate."
    )
    category = "weather"
    default_params = {
        "min_edge": 0.05,
        "max_position_usd": 100,
        "calibration_window_days": 40,
        "min_calibration_observations": 10,
        "keywords": [
            "temperature",
            "degrees",
            "high temperature",
            "low temperature",
            "weather",
        ],
        "interval_seconds": 300,
    }

    # ── Event-driven (WS-first) extensions ──
    subscribed_events: set[str] = {
        "last_trade_price",
        "price_change",
        "market_resolved",
    }

    async def on_market_event(self, event: MarketEvent) -> dict | None:
        """
        Handle real-time WS events for weather markets.

        - market_resolved → auto-settle open positions
        - price_change / last_trade_price → re-evaluate calibrated edge vs new market price
        """
        token_id = event.token_id
        event_type = event.event_type
        data = event.data

        if event_type == "market_resolved":
            return await self._handle_market_resolved(token_id, data)

        if event_type in ("price_change", "last_trade_price"):
            return await self._handle_price_update(token_id, data)

        return None

    async def _handle_market_resolved(self, token_id: str, data: dict) -> dict | None:
        """Auto-settle positions when a weather market resolves."""
        outcome = data.get("outcome") or data.get("resolution")
        if not outcome:
            logger.debug(
                f"[{self.name}] market_resolved event missing outcome for {token_id[:20]}..."
            )
            return None

        logger.info(
            f"[{self.name}] Market resolved: token={token_id[:20]}... outcome={outcome}"
        )

        return {
            "decision": "SETTLE",
            "token_id": token_id,
            "outcome": outcome,
            "strategy_name": self.name,
            "reasoning": f"weather_emos: auto-settle on market_resolved outcome={outcome}",
        }

    async def _handle_price_update(self, token_id: str, data: dict) -> dict | None:
        """
        Re-evaluate calibrated edge when market price changes.

        Compares our EMOS-calibrated probability against the new market mid-price.
        Fires a BUY signal if edge exceeds min_edge threshold.
        """
        new_price = data.get("price") or data.get("last_trade_price")
        if new_price is None:
            return None

        try:
            new_price = float(new_price)
        except (ValueError, TypeError):
            return None

        if not (0.0 < new_price < 1.0):
            return None

        question = data.get("question", "")
        if not question:
            return None

        threshold_f, direction = extract_threshold_from_question(question)
        if threshold_f is None:
            return None

        city_name = None
        for city, fp_city in DEFAULT_CITIES:
            if city.lower().replace(" ", "") in question.lower().replace(" ", ""):
                city_name = city
                break

        if city_name is None:
            return None

        cal_states = load_calibration_states(None, self.name)
        cal = cal_states.get(city_name)
        if cal is None or cal.n < self.default_params["min_calibration_observations"]:
            return None

        forecast_high = data.get("forecast_high_f")
        if forecast_high is None:
            return None

        forecast_mean = float(forecast_high)
        calibrated_mean = cal.calibrate(forecast_mean)
        calibrated_std = max(1.0, cal.residual_std())

        if direction == "above":
            calibrated_p = pr_exceeds_threshold(
                threshold_f, calibrated_mean, calibrated_std
            )
        else:
            calibrated_p = 1.0 - pr_exceeds_threshold(
                threshold_f, calibrated_mean, calibrated_std
            )

        edge = calibrated_p - new_price
        min_edge = self.default_params["min_edge"]

        if abs(edge) <= min_edge:
            return None

        trade_side = "NO" if edge < 0 else "YES"
        confidence = min(1.0, abs(edge) / min_edge)

        logger.info(
            f"[{self.name}] WS edge signal: city={city_name} edge={edge:+.3f} "
            f"calibrated_p={calibrated_p:.3f} market={new_price:.3f}"
        )

        return {
            "decision": "BUY",
            "token_id": token_id,
            "direction": trade_side.lower(),
            "confidence": confidence,
            "edge": edge,
            "model_probability": calibrated_p,
            "market_probability": new_price,
            "strategy_name": self.name,
            "market_type": "weather",
            "reasoning": f"weather_emos WS: calibrated_p={calibrated_p:.3f} market={new_price:.3f} edge={edge:+.3f}",
        }

    async def market_filter(self, markets: list[MarketInfo]) -> list[MarketInfo]:
        """Filter to weather/temperature markets."""
        keywords = [
            "temperature",
            "degrees",
            "fahrenheit",
            "weather",
            "high temp",
            "low temp",
        ]
        return [
            m
            for m in markets
            if any(kw in m.question.lower() or kw in m.slug.lower() for kw in keywords)
        ]

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        result = CycleResult(
            decisions_recorded=0,
            trades_attempted=0,
            trades_placed=0,
        )
        params = ctx.params
        min_edge = params.get("min_edge", self.default_params["min_edge"])
        min_obs = params.get(
            "min_calibration_observations",
            self.default_params["min_calibration_observations"],
        )
        max_pos = params.get(
            "max_position_usd", self.default_params["max_position_usd"]
        )
        keywords = params.get("keywords", self.default_params["keywords"])

        # Load calibration states
        cal_states = load_calibration_states(ctx.db, self.name)

        # Fetch active weather markets
        try:
            from backend.core.market_scanner import fetch_markets_by_keywords

            all_markets = await fetch_markets_by_keywords(keywords, limit=1000)
            weather_markets = await self.market_filter(all_markets)
            result.markets_scanned = len(weather_markets)
        except Exception as e:
            result.errors.append(f"Market fetch failed: {e}")
            return result

        if not weather_markets:
            logger.warning(
                "No active weather markets found. Auto-pausing weather_emos strategy."
            )
            # Auto-pause by setting enabled=False in StrategyConfig
            if ctx.db:
                try:
                    from backend.models.database import StrategyConfig

                    cfg = (
                        ctx.db.query(StrategyConfig)
                        .filter(StrategyConfig.strategy_name == self.name)
                        .first()
                    )
                    if cfg:
                        cfg.enabled = False
                        ctx.db.commit()
                        logger.info(f"Successfully auto-paused {self.name} in DB.")
                except Exception as db_ex:
                    logger.error(f"Failed to auto-pause {self.name} in DB: {db_ex}")

            record_decision(
                ctx.db,
                self.name,
                "all_weather_markets",
                "SKIP",
                signal_data={
                    "reason": "no_active_weather_markets",
                    "sources": ["weather_emos"],
                },
                reason="No active weather markets found",
            )
            result.decisions_recorded = 1
            return result

        # Fetch forecasts for all configured cities
        city_forecasts: dict[str, ForecastPoint] = {}
        fetch_tasks = []
        for name_city, lat, lon, *_ in DEFAULT_CITIES:
            fetch_tasks.append(fetch_open_meteo_forecast(lat, lon))

        forecast_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        for (name_city, lat, lon, *_), forecast_data in zip(
            DEFAULT_CITIES, forecast_results
        ):
            if isinstance(forecast_data, Exception) or not forecast_data:
                continue
            try:
                daily = forecast_data.get("daily", {})
                max_temps = daily.get("temperature_2m_max", [])
                min_temps = daily.get("temperature_2m_min", [])
                if max_temps:
                    city_forecasts[name_city] = ForecastPoint(
                        city=name_city,
                        lat=lat,
                        lon=lon,
                        forecast_high_f=float(max_temps[0]) if max_temps else None,
                        forecast_low_f=float(min_temps[0]) if min_temps else None,
                        ensemble_std=5.0,  # Open-Meteo free doesn't include ensemble spread; use prior
                    )
            except Exception as e:
                logger.debug(f"Forecast parse error for {name_city}: {e}")

        # Match markets to cities and compute calibrated probabilities
        for market in weather_markets:
            city_name = None
            forecast = None
            for city, fp in city_forecasts.items():
                if city.lower().replace(" ", "") in market.question.lower().replace(
                    " ", ""
                ):
                    city_name = city
                    forecast = fp
                    break

            if forecast is None:
                record_decision(
                    ctx.db,
                    self.name,
                    market.ticker,
                    "SKIP",
                    signal_data={
                        "reason": "no_city_match",
                        "question": market.question,
                        "sources": ["weather_emos"],
                    },
                    reason="Could not match market to a configured city",
                )
                result.decisions_recorded += 1
                continue

            threshold_f, direction = extract_threshold_from_question(market.question)
            if threshold_f is None:
                record_decision(
                    ctx.db,
                    self.name,
                    market.ticker,
                    "SKIP",
                    signal_data={
                        "reason": "no_threshold_parsed",
                        "question": market.question,
                        "sources": ["weather_emos"],
                    },
                    reason="Could not parse temperature threshold from question",
                )
                result.decisions_recorded += 1
                continue

            # Get or create calibration state
            cal = cal_states.get(city_name)
            if cal is None:
                cal = CalibrationState()
                cal.set_city(city_name)
                cal_states[city_name] = cal
                logger.warning(
                    f"CalibrationState for city '{city_name}' missing, created new."
                )

            # Check minimum observations
            if cal.n < min_obs:
                record_decision(
                    ctx.db,
                    self.name,
                    market.ticker,
                    "SKIP",
                    confidence=0.0,
                    signal_data={
                        "reason": "insufficient_calibration_data",
                        "city": city_name,
                        "n_observations": cal.n,
                        "min_required": min_obs,
                        "sources": ["weather_emos"],
                    },
                    reason=f"Only {cal.n}/{min_obs} calibration observations for {city_name}",
                )
                result.decisions_recorded += 1
                continue

            # Apply EMOS calibration
            forecast_mean = (
                forecast.forecast_high_f
                if "high" in market.question.lower()
                else forecast.forecast_low_f
            )
            if forecast_mean is None:
                continue

            calibrated_mean = cal.calibrate(forecast_mean)
            calibrated_std = max(1.0, cal.residual_std())

            # Compute P(T > threshold)
            if direction == "above":
                calibrated_p = pr_exceeds_threshold(
                    threshold_f, calibrated_mean, calibrated_std
                )
            else:
                calibrated_p = 1.0 - pr_exceeds_threshold(
                    threshold_f, calibrated_mean, calibrated_std
                )

            # Compute weather mood shift (z-score anomaly)
            mood_anomaly = (
                (calibrated_mean - forecast_mean) / calibrated_std
                if calibrated_std > 0
                else 0.0
            )

            # Determine category weight for emotional sentiment
            cat = getattr(market, "category", "general") or "general"
            cat_lower = cat.lower()

            category_weight = 1.0
            for k, w in CATEGORY_WEATHER_WEIGHTS.items():
                if k in cat_lower:
                    category_weight = w
                    break

            # Calculate emotional sentiment adjustment (up to 5% baseline shift scaled by category weight)
            sentiment_shift = mood_anomaly * 0.05 * category_weight

            # Adjust calibrated probability with the category-weighted sentiment
            calibrated_p = max(0.01, min(0.99, calibrated_p + sentiment_shift))

            market_mid = market.yes_price
            edge = calibrated_p - market_mid

            signal_data = {
                "city": city_name,
                "threshold_f": threshold_f,
                "direction": direction,
                "forecast_mean_f": forecast_mean,
                "calibrated_mean_f": calibrated_mean,
                "calibrated_std_f": calibrated_std,
                "calibrated_p": calibrated_p,
                "market_mid": market_mid,
                "edge": edge,
                "n_calibration_obs": cal.n,
                "emos_a": cal.a,
                "emos_b": cal.b,
                "sources": ["weather_emos", "open_meteo", "nws"],
            }

            decision = "BUY" if abs(edge) > min_edge else "SKIP"
            # If edge is negative (calibrated_p < market_mid), we'd buy NO
            if decision == "BUY" and edge < 0:
                signal_data["trade_side"] = "NO"
            elif decision == "BUY":
                signal_data["trade_side"] = "YES"

            confidence_score = min(1.0, abs(edge) / min_edge)

            record_decision(
                ctx.db,
                self.name,
                market.ticker,
                decision,
                confidence=confidence_score,
                signal_data=signal_data,
                reason=f"EMOS: calibrated_p={calibrated_p:.3f} market={market_mid:.3f} edge={edge:+.3f}",
            )
            result.decisions_recorded += 1

            activity_logger.log_entry(
                strategy_name=self.name,
                decision_type="entry" if decision == "BUY" else "hold",
                data={
                    "market_ticker": market.ticker,
                    "city": city,
                    "threshold_f": threshold_f,
                    "calibrated_p": calibrated_p,
                    "market_mid": market_mid,
                    "edge": edge,
                    "calibration_n": cal.n,
                    "question": market.question,
                },
                confidence=confidence_score,
                mode=ctx.mode,
                db=ctx.db,
            )

            if decision == "BUY":
                result.trades_attempted += 1
                trade_side = signal_data.get("trade_side", "YES")
                entry_price = market_mid if trade_side == "YES" else (1.0 - market_mid)

                # Extract token_id from market metadata
                clob_token_id = None
                clob_token_ids = market.metadata.get("clobTokenIds") or []
                if isinstance(clob_token_ids, str):
                    import json as _json

                    try:
                        clob_token_ids = _json.loads(clob_token_ids)
                    except Exception as e:
                        logger.debug(f"Failed to parse clobTokenIds JSON: {e}")
                        clob_token_ids = []
                if clob_token_ids and len(clob_token_ids) >= 2:
                    clob_token_id = str(
                        clob_token_ids[0] if trade_side == "YES" else clob_token_ids[1]
                    )
                elif clob_token_ids:
                    clob_token_id = str(clob_token_ids[0])

                bankroll = 100.0
                try:
                    from backend.models.database import BotState, for_update

                    state = for_update(ctx.db, ctx.db.query(BotState)).first()
                    if state:
                        if ctx.mode == "paper":
                            bankroll = float(
                                state.paper_bankroll
                                if state.paper_bankroll is not None
                                else ctx.settings.INITIAL_BANKROLL
                            )
                        elif ctx.mode == "testnet":
                            bankroll = float(
                                state.testnet_bankroll
                                if state.testnet_bankroll is not None
                                else ctx.settings.INITIAL_BANKROLL
                            )
                        else:
                            bankroll = float(
                                state.bankroll
                                if state.bankroll is not None
                                else ctx.settings.INITIAL_BANKROLL
                            )
                except Exception:
                    logger.exception("Failed to retrieve bot bankroll for weather EMOS")
                    pass

                kelly_size = _calculate_weather_kelly_size(
                    edge=abs(edge),
                    probability=calibrated_p,
                    market_price=market_mid,
                    direction=trade_side.lower(),
                    bankroll=bankroll,
                )
                trade_size = min(
                    kelly_size, max_pos, ctx.settings.WEATHER_MAX_TRADE_SIZE
                )
                trade_size = max(trade_size, 10.0)

                result.decisions.append(
                    {
                        "decision": "BUY",
                        "market_ticker": market.ticker,
                        "token_id": clob_token_id,
                        "direction": trade_side.lower(),
                        "confidence": min(1.0, abs(edge) / min_edge),
                        "edge": edge,
                        "size": trade_size,
                        "entry_price": entry_price,
                        "suggested_size": trade_size,
                        "model_probability": calibrated_p,
                        "market_probability": market_mid,
                        "platform": settings.DEFAULT_VENUE,
                        "strategy_name": self.name,
                        "market_type": "weather",
                        "reasoning": f"EMOS: calibrated_p={calibrated_p:.3f} market={market_mid:.3f} edge={edge:+.3f}",
                        "slug": market.slug,
                    }
                )

                if ctx.clob:
                    try:
                        order_result = await ctx.clob.place_limit_order(
                            token_id=clob_token_id or market.ticker,
                            side="BUY",
                            price=entry_price,
                            size=trade_size,
                        )
                        if order_result.success:
                            result.trades_placed += 1
                            # Record Trade in DB for both paper and live modes
                            try:
                                from backend.models.database import Trade

                                new_trade = Trade(
                                    market_ticker=market.ticker,
                                    direction=trade_side.lower(),
                                    entry_price=entry_price,
                                    size=trade_size,
                                    market_type="weather",
                                    trading_mode=ctx.mode,
                                    strategy="weather_emos",
                                    status="open",
                                )
                                ctx.db.add(new_trade)
                                ctx.db.commit()
                            except Exception as db_err:
                                try:
                                    ctx.db.rollback()
                                except Exception:
                                    logger.warning(
                                        "DB rollback failed after trade record error",
                                        exc_info=True,
                                    )
                                result.errors.append(
                                    f"Trade record failed {market.ticker}: {db_err}"
                                )
                    except Exception as e:
                        result.errors.append(f"Order failed {market.ticker}: {e}")

        # Save updated calibration states
        save_calibration_states(ctx.db, self.name, cal_states)
        return result
