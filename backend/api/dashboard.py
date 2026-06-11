"""Dashboard API endpoints."""

import asyncio
import time
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.api.system import BotStats, get_stats
from backend.api.trading import (
    CalibrationSummary,
    SignalResponse,
    TradeResponse,
    _compute_calibration_summary,
    _signal_to_response,
)
from backend.api.markets import _weather_signal_to_response
from backend.config import settings
from backend.core.signals import scan_for_signals
from backend.data.btc_markets import fetch_active_btc_markets
from backend.data.crypto import compute_btc_microstructure, fetch_crypto_price
from backend.models.database import BotState, Trade, TradeContext, get_db

from loguru import logger

# ── Market question cache (market_ticker → question) ──────────────────────
_market_question_cache: dict[str, str] = {}
_market_question_cache_built = False


def _build_market_question_cache(db: Session) -> None:
    global _market_question_cache_built
    if _market_question_cache_built:
        return

    try:
        from backend.models.database import MarketWatch

        rows = db.query(MarketWatch).all()
        for row in rows:
            if row.ticker and row.ticker not in _market_question_cache:
                _market_question_cache[row.ticker] = row.ticker
    except Exception:
        logger.exception("Failed to build market question cache from MarketWatch")

    _market_question_cache_built = True


async def _resolve_market_questions(tickers: list[str], db: Session) -> dict[str, str]:
    _build_market_question_cache(db)

    result: dict[str, str] = {}
    unresolved: list[str] = []

    for ticker in tickers:
        if ticker in _market_question_cache:
            result[ticker] = _market_question_cache[ticker]
        else:
            unresolved.append(ticker)

    if not unresolved:
        return result

    # First pass: decode slug-based tickers locally (e.g. "bun-dor-ein-2026-05-08-dor")
    still_unresolved: list[str] = []
    for ticker in unresolved:
        if ticker and not ticker.isdigit() and "-" in ticker:
            decoded = ticker.replace("-", " ").title()
            _market_question_cache[ticker] = decoded
            result[ticker] = decoded
        else:
            still_unresolved.append(ticker)

    if not still_unresolved:
        return result

    try:
        import httpx

        async def fetch_question(
            client: httpx.AsyncClient, ticker: str
        ) -> tuple[str, str]:
            try:
                resp = await asyncio.wait_for(
                    client.get(f"https://gamma-api.polymarket.com/markets/{ticker}"),
                    timeout=1.5,
                )
                if resp.status_code == 200:
                    question = (resp.json() or {}).get("question", "")
                    if question:
                        return ticker, question
            except Exception:
                logger.debug(f"dashboard market question lookup skipped for {ticker}")
            return ticker, ticker

        numeric_ids = [t for t in still_unresolved if t.isdigit()]
        non_numeric = [t for t in still_unresolved if not t.isdigit()]
        for ticker in non_numeric:
            result[ticker] = ticker

        if numeric_ids:
            async with httpx.AsyncClient(timeout=2.0) as client:
                question_results = await asyncio.wait_for(
                    asyncio.gather(
                        *(
                            fetch_question(client, ticker)
                            for ticker in numeric_ids[:10]
                        ),
                        return_exceptions=True,
                    ),
                    timeout=2.5,
                )
            for item in question_results:
                if isinstance(item, Exception):
                    continue
                ticker, question = item
                _market_question_cache[ticker] = question
                result[ticker] = question
    except Exception:
        logger.warning(
            "dashboard market question lookup timed out; using ticker fallbacks"
        )
        for ticker in still_unresolved:
            result.setdefault(ticker, ticker)

    return result


router = APIRouter(tags=["dashboard"])


class BtcPriceResponse(BaseModel):
    price: float
    change_24h: float
    change_7d: float
    market_cap: float
    volume_24h: float
    last_updated: datetime


class BtcWindowResponse(BaseModel):
    slug: str
    market_id: str
    up_price: float
    down_price: float
    window_start: datetime
    window_end: datetime
    volume: float
    is_active: bool
    is_upcoming: bool
    time_until_end: float
    spread: float


class MicrostructureResponse(BaseModel):
    rsi: float = 50.0
    momentum_1m: float = 0.0
    momentum_5m: float = 0.0
    momentum_15m: float = 0.0
    vwap_deviation: float = 0.0
    sma_crossover: float = 0.0
    volatility: float = 0.0
    price: float = 0.0
    source: str = "unknown"


class WeatherForecastResponse(BaseModel):
    city_key: str
    city_name: str
    target_date: str
    mean_high: float
    std_high: float
    mean_low: float
    std_low: float
    num_members: int
    ensemble_agreement: float


class WeatherMarketResponse(BaseModel):
    slug: str
    market_id: str
    platform: str = "polymarket"
    title: str
    city_key: str
    city_name: str
    target_date: str
    threshold_f: float
    metric: str
    direction: str
    yes_price: float
    no_price: float
    volume: float


class WeatherSignalResponse(BaseModel):
    market_id: str
    city_key: str
    city_name: str
    target_date: str
    threshold_f: float
    metric: str
    direction: str
    model_probability: float
    market_probability: float
    edge: float
    confidence: float
    suggested_size: float
    reasoning: str
    ensemble_mean: float
    ensemble_std: float
    ensemble_members: int
    actionable: bool = False


class DashboardData(BaseModel):
    stats: BotStats
    btc_price: Optional[BtcPriceResponse]
    microstructure: Optional[MicrostructureResponse] = None
    windows: List[BtcWindowResponse]
    active_signals: List[SignalResponse]
    recent_trades: List[TradeResponse]
    top_winning_trades: List[TradeResponse] = []
    equity_curve: List[dict]
    calibration: Optional[CalibrationSummary] = None
    weather_signals: List[WeatherSignalResponse] = []
    weather_forecasts: List[WeatherForecastResponse] = []
    trading_mode: str = "paper"
    active_modes: List[str] = []


_dashboard_cache_lock = asyncio.Lock()
_dashboard_cache_value: DashboardData | None = None
_dashboard_cache_expires_at = 0.0


def _dashboard_cache_ttl_seconds() -> float:
    return max(0.0, float(getattr(settings, "DASHBOARD_CACHE_TTL_SECONDS", 2.0)))


async def _get_cached_dashboard_data(db: Session) -> DashboardData:
    """Coalesce expensive dashboard builds across near-simultaneous pollers."""
    global _dashboard_cache_value, _dashboard_cache_expires_at

    ttl_seconds = _dashboard_cache_ttl_seconds()
    if ttl_seconds <= 0:
        return await _build_dashboard_data(db)

    now = time.monotonic()
    if _dashboard_cache_value is not None and now < _dashboard_cache_expires_at:
        return _dashboard_cache_value

    async with _dashboard_cache_lock:
        now = time.monotonic()
        if _dashboard_cache_value is not None and now < _dashboard_cache_expires_at:
            return _dashboard_cache_value

        dashboard_data = await _build_dashboard_data(db)
        _dashboard_cache_value = dashboard_data
        _dashboard_cache_expires_at = time.monotonic() + ttl_seconds
        return dashboard_data


def _serialize_trade_response(
    trade: Trade,
    contexts: dict[int, TradeContext],
    market_questions: dict[str, str] | None = None,
) -> TradeResponse:
    context = contexts.get(trade.id)
    return TradeResponse(
        id=trade.id,
        market_ticker=trade.market_ticker,
        market_question=(market_questions or {}).get(trade.market_ticker)
        or trade.event_slug,
        platform=trade.platform,
        event_slug=trade.event_slug,
        direction=trade.direction,
        entry_price=trade.entry_price,
        size=trade.size,
        timestamp=trade.timestamp,
        settled=trade.settled,
        result=trade.result,
        pnl=trade.pnl,
        strategy=(context.strategy if context else None)
        or getattr(trade, "strategy", None),
        signal_source=(context.signal_source if context else None)
        or getattr(trade, "signal_source", None),
        confidence=(context.confidence if context else None)
        or getattr(trade, "confidence", None),
        trading_mode=trade.trading_mode,
    )


def _load_trade_contexts(db: Session, trades: list[Trade]) -> dict[int, TradeContext]:
    trade_ids = [trade.id for trade in trades]
    if not trade_ids:
        return {}
    return {
        context.trade_id: context
        for context in db.query(TradeContext)
        .filter(TradeContext.trade_id.in_(trade_ids))
        .all()
    }


def _build_account_equity_curve(db: Session, curve_mode: str = "live") -> list[dict]:
    """Build dashboard equity points without letting historical backfills redefine live equity."""
    equity_curve: list[dict] = []
    initial_bankroll = (
        100.0 if curve_mode == "testnet" else float(settings.INITIAL_BANKROLL)
    )
    mode_state = db.query(BotState).filter_by(mode=curve_mode).first()

    if curve_mode == "live":
        historical_trades = (
            db.query(Trade)
            .filter(
                Trade.settled.is_(True),
                Trade.trading_mode == "live",
                Trade.pnl.isnot(None),
                or_(
                    Trade.settlement_source.is_(None),
                    Trade.settlement_source != "backfill_conservative_loss",
                ),
            )
            .order_by(Trade.timestamp)
            .limit(500)
            .all()
        )
        realized_points: list[tuple[datetime, float]] = []
        cumulative_realized = 0.0
        for trade in historical_trades:
            cumulative_realized += float(trade.pnl or 0.0)
            realized_points.append((trade.timestamp, cumulative_realized))

        current_pnl = (
            float(mode_state.total_pnl or 0.0) if mode_state else cumulative_realized
        )
        current_bankroll = (
            float(mode_state.bankroll or initial_bankroll)
            if mode_state
            else initial_bankroll + current_pnl
        )

        if realized_points:
            final_realized = realized_points[-1][1]
            adjustment = current_pnl - final_realized
            for timestamp, realized_pnl in realized_points:
                point_pnl = realized_pnl + adjustment
                equity_curve.append(
                    {
                        "timestamp": timestamp.isoformat(),
                        "pnl": point_pnl,
                        "bankroll": current_bankroll - (current_pnl - point_pnl),
                    }
                )

        equity_curve.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "pnl": current_pnl,
                "bankroll": current_bankroll,
            }
        )
        return equity_curve

    cumulative_pnl = 0.0
    equity_trades = (
        db.query(Trade)
        .filter(Trade.settled.is_(True), Trade.trading_mode == curve_mode)
        .order_by(Trade.timestamp)
        .all()
    )
    for trade in equity_trades:
        cumulative_pnl += float(trade.pnl or 0.0)
        equity_curve.append(
            {
                "timestamp": trade.timestamp.isoformat(),
                "pnl": cumulative_pnl,
                "bankroll": initial_bankroll + cumulative_pnl,
            }
        )

    if mode_state:
        if curve_mode == "paper":
            current_bankroll = (
                mode_state.paper_bankroll
                if mode_state.paper_bankroll is not None
                else mode_state.bankroll
            )
            current_pnl = (
                mode_state.paper_pnl
                if mode_state.paper_pnl is not None
                else mode_state.total_pnl
            )
        else:
            current_bankroll = (
                mode_state.testnet_bankroll
                if mode_state.testnet_bankroll is not None
                else mode_state.bankroll
            )
            current_pnl = (
                mode_state.testnet_pnl
                if mode_state.testnet_pnl is not None
                else mode_state.total_pnl
            )
        equity_curve.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "pnl": float(current_pnl or 0.0),
                "bankroll": float(current_bankroll or initial_bankroll),
            }
        )

    return equity_curve


@router.get("/dashboard", response_model=DashboardData)
async def get_dashboard(db: Session = Depends(get_db)):
    """Get all dashboard data in one call - returns stats for all 3 modes."""
    return await _get_cached_dashboard_data(db)


async def _build_dashboard_data(db: Session) -> DashboardData:
    """Build dashboard data from live sources and database snapshots."""
    try:
        stats = await asyncio.wait_for(get_stats(db=db, mode=None), timeout=6.0)
    except (asyncio.TimeoutError, Exception) as e:
        logger.warning(f"[dashboard] get_stats timed out after 12s: {e}")
        stats = await asyncio.wait_for(
            get_stats(db=db, mode=settings.TRADING_MODE), timeout=4.0
        )

    # Fetch BTC price from microstructure first, fallback to CoinGecko
    btc_price_data = None
    micro_data = None
    try:
        micro = await asyncio.wait_for(compute_btc_microstructure(), timeout=5.0)
        if micro:
            micro_data = MicrostructureResponse(
                rsi=micro.rsi,
                momentum_1m=micro.momentum_1m,
                momentum_5m=micro.momentum_5m,
                momentum_15m=micro.momentum_15m,
                vwap_deviation=micro.vwap_deviation,
                sma_crossover=micro.sma_crossover,
                volatility=micro.volatility,
                price=micro.price,
                source=micro.source,
            )
            btc_price_data = BtcPriceResponse(
                price=micro.price,
                change_24h=(micro.momentum_15m or 0.0) * 96,  # rough extrapolation
                change_7d=0,
                market_cap=0,
                volume_24h=0,
                last_updated=datetime.now(timezone.utc),
            )
    except Exception as e:
        logger.warning(
            f"[api.dashboard.get_dashboard] {type(e).__name__}: Failed to fetch BTC microstructure data, falling back to CoinGecko: {e}",
            exc_info=True,
        )
    if not btc_price_data:
        try:
            btc = await fetch_crypto_price("BTC")
            if btc:
                btc_price_data = BtcPriceResponse(
                    price=btc.current_price,
                    change_24h=btc.change_24h,
                    change_7d=btc.change_7d,
                    market_cap=btc.market_cap,
                    volume_24h=btc.volume_24h,
                    last_updated=btc.last_updated,
                )
        except Exception as e:
            logger.warning(
                f"[api.dashboard.get_dashboard] {type(e).__name__}: Failed to fetch BTC price from CoinGecko: {e}",
                exc_info=True,
            )

    # Fetch windows
    windows = []
    try:
        markets = await asyncio.wait_for(fetch_active_btc_markets(), timeout=4.0)
        windows = [
            BtcWindowResponse(
                slug=m.slug,
                market_id=m.market_id,
                up_price=m.up_price,
                down_price=m.down_price,
                window_start=m.window_start,
                window_end=m.window_end,
                volume=m.volume,
                is_active=m.is_active,
                is_upcoming=m.is_upcoming,
                time_until_end=m.time_until_end,
                spread=m.spread,
            )
            for m in markets
        ]
    except Exception as e:
        logger.warning(
            f"[api.dashboard.get_dashboard] {type(e).__name__}: Failed to fetch active BTC markets: {e}",
            exc_info=True,
        )

    # Signals — return ALL signals, mark which are actionable
    signals = []
    try:
        raw_signals = await asyncio.wait_for(scan_for_signals(), timeout=2.0)
        signals = [
            _signal_to_response(s, actionable=s.passes_threshold) for s in raw_signals
        ]
    except Exception as e:
        logger.warning(
            f"[api.dashboard.get_dashboard] {type(e).__name__}: Failed to scan for trading signals: {e}",
            exc_info=True,
        )

    # Recent trades (with TradeContext enrichment + market questions)
    trades = db.query(Trade).order_by(Trade.timestamp.desc()).limit(50).all()
    contexts = _load_trade_contexts(db, trades)
    trade_tickers = list({t.market_ticker for t in trades if t.market_ticker})
    market_questions = await _resolve_market_questions(trade_tickers, db)
    recent_trades = [
        _serialize_trade_response(t, contexts, market_questions) for t in trades
    ]

    top_winning_trade_rows = (
        db.query(Trade)
        .filter(
            Trade.settled.is_(True),
            Trade.pnl.isnot(None),
            Trade.pnl > 0,
        )
        .order_by(Trade.pnl.desc(), Trade.timestamp.desc())
        .limit(5)
        .all()
    )
    top_winning_contexts = _load_trade_contexts(db, top_winning_trade_rows)
    top_winning_trades = [
        _serialize_trade_response(t, top_winning_contexts, market_questions)
        for t in top_winning_trade_rows
    ]

    # Equity curve: match the default dashboard/account view.
    curve_mode = "live"
    equity_curve = _build_account_equity_curve(db, curve_mode=curve_mode)

    # Calibration summary
    calibration = _compute_calibration_summary(db)

    # Weather data (if enabled)
    weather_signals_data = []
    weather_forecasts_data = []
    if settings.WEATHER_ENABLED:
        try:
            from backend.core.weather_signals import scan_for_weather_signals
            from backend.data.weather import fetch_ensemble_forecast, CITY_CONFIG

            wx_signals = await asyncio.wait_for(
                scan_for_weather_signals(mode=settings.TRADING_MODE), timeout=3.0
            )
            weather_signals_data = [
                WeatherSignalResponse(**_weather_signal_to_response(s).model_dump())
                for s in wx_signals
            ]

            city_keys = [
                c.strip() for c in settings.WEATHER_CITIES.split(",") if c.strip()
            ]
            for city_key in city_keys:
                if city_key not in CITY_CONFIG:
                    continue
                forecast = await fetch_ensemble_forecast(city_key)
                if forecast:
                    weather_forecasts_data.append(
                        WeatherForecastResponse(
                            city_key=forecast.city_key,
                            city_name=forecast.city_name,
                            target_date=forecast.target_date.isoformat(),
                            mean_high=forecast.mean_high,
                            std_high=forecast.std_high,
                            mean_low=forecast.mean_low,
                            std_low=forecast.std_low,
                            num_members=forecast.num_members,
                            ensemble_agreement=forecast.ensemble_agreement,
                        )
                    )
        except Exception as e:
            logger.warning(
                f"[api.dashboard.get_dashboard] {type(e).__name__}: Failed to fetch weather forecasts data: {e}",
                exc_info=True,
            )

    return DashboardData(
        stats=stats,
        btc_price=btc_price_data,
        microstructure=micro_data,
        windows=windows,
        active_signals=signals,
        recent_trades=recent_trades,
        top_winning_trades=top_winning_trades,
        equity_curve=equity_curve,
        calibration=calibration,
        weather_signals=weather_signals_data,
        weather_forecasts=weather_forecasts_data,
        trading_mode=settings.TRADING_MODE,
        active_modes=sorted(settings.active_modes_set),
    )
