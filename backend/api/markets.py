"""Market data routes - BTC, Polymarket, Kalshi, Weather."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from backend.config import settings
from backend.models.database import get_db, MarketWatch
from backend.api.auth import require_admin
from backend.data.btc_markets import fetch_active_btc_markets
from backend.data.crypto import fetch_crypto_price
from backend.core.errors import handle_errors

from loguru import logger

router = APIRouter(tags=["markets"])


# ============================================================================
# Pydantic Response Models
# ============================================================================


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


# ============================================================================
# BTC Endpoints
# ============================================================================


@router.get("/btc/price", response_model=Optional[BtcPriceResponse])
@handle_errors(default_response=None)
async def get_btc_price():
    """Get current BTC price and momentum data."""
    btc = await fetch_crypto_price("BTC")
    if not btc:
        return None

    return BtcPriceResponse(
        price=btc.current_price,
        change_24h=btc.change_24h,
        change_7d=btc.change_7d,
        market_cap=btc.market_cap,
        volume_24h=btc.volume_24h,
        last_updated=btc.last_updated,
    )


@router.get("/btc/windows", response_model=List[BtcWindowResponse])
@handle_errors(default_response=[])
async def get_btc_windows():
    """Get upcoming BTC 5-min windows with prices."""
    try:
        markets = await fetch_active_btc_markets()
        return [
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
        logger.warning(f"Weather forecasts fetch failed: {e}")
        return []


# ============================================================================
# Kalshi Endpoints
# ============================================================================


@router.get("/kalshi/status")
async def get_kalshi_status():
    """Test Kalshi API authentication and return connection status."""
    from backend.data.kalshi_client import KalshiClient, kalshi_credentials_present

    if not kalshi_credentials_present():
        return {
            "connected": False,
            "error": "Kalshi credentials not configured (KALSHI_API_KEY_ID / KALSHI_PRIVATE_KEY_PATH)",
        }

    try:
        client = KalshiClient()
        balance_data = await client.get_balance()
        return {
            "connected": True,
            "balance": balance_data,
        }
    except Exception as e:
        return {
            "connected": False,
            "error": str(e),
        }


# ============================================================================
# Weather Endpoints
# ============================================================================


@router.get("/weather/forecasts", response_model=List[WeatherForecastResponse])
async def get_weather_forecasts():
    """Get ensemble forecasts for configured cities."""
    if not settings.WEATHER_ENABLED:
        return []

    try:
        from backend.data.weather import fetch_ensemble_forecast, CITY_CONFIG

        city_keys = [c.strip() for c in settings.WEATHER_CITIES.split(",") if c.strip()]
        forecasts = []

        for city_key in city_keys:
            if city_key not in CITY_CONFIG:
                continue
            forecast = await fetch_ensemble_forecast(city_key)
            if forecast:
                forecasts.append(
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

        return forecasts
    except Exception:
        logger.exception("Failed to fetch weather forecasts")
        return []


@router.get("/weather/markets", response_model=List[WeatherMarketResponse])
async def get_weather_markets():
    """Get active weather temperature markets."""
    if not settings.WEATHER_ENABLED:
        return []

    try:
        from backend.data.weather_markets import fetch_polymarket_weather_markets

        city_keys = [c.strip() for c in settings.WEATHER_CITIES.split(",") if c.strip()]
        markets = await fetch_polymarket_weather_markets(city_keys)

        # Also fetch Kalshi markets if enabled
        if settings.KALSHI_ENABLED:
            try:
                from backend.data.kalshi_client import kalshi_credentials_present
                from backend.data.kalshi_markets import fetch_kalshi_weather_markets

                if kalshi_credentials_present():
                    kalshi_markets = await fetch_kalshi_weather_markets(city_keys)
                    markets.extend(kalshi_markets)
            except Exception as e:
                logger.debug(f"Market detail lookup failed: {e}")

        return [
            WeatherMarketResponse(
                slug=m.slug,
                market_id=m.market_id,
                platform=m.platform,
                title=m.title,
                city_key=m.city_key,
                city_name=m.city_name,
                target_date=m.target_date.isoformat(),
                threshold_f=m.threshold_f,
                metric=m.metric,
                direction=m.direction,
                yes_price=m.yes_price,
                no_price=m.no_price,
                volume=m.volume,
            )
            for m in markets
        ]
    except Exception:
        logger.exception("Failed to fetch weather markets")
        return []


@router.get("/weather/signals", response_model=List[WeatherSignalResponse])
async def get_weather_signals():
    """Get current weather trading signals."""
    if not settings.WEATHER_ENABLED:
        return []

    try:
        from backend.core.weather_signals import scan_for_weather_signals

        signals = await scan_for_weather_signals()
        return [_weather_signal_to_response(s) for s in signals]
    except Exception:
        logger.exception("Failed to fetch weather signals")
        return []


def _weather_signal_to_response(s) -> WeatherSignalResponse:
    return WeatherSignalResponse(
        market_id=s.market.market_id,
        city_key=s.market.city_key,
        city_name=s.market.city_name,
        target_date=s.market.target_date.isoformat(),
        threshold_f=s.market.threshold_f,
        metric=s.market.metric,
        direction=s.direction,
        model_probability=s.model_probability,
        market_probability=s.market_probability,
        edge=s.edge,
        confidence=s.confidence,
        suggested_size=s.suggested_size,
        reasoning=s.reasoning,
        ensemble_mean=s.ensemble_mean,
        ensemble_std=s.ensemble_std,
        ensemble_members=s.ensemble_members,
        actionable=s.passes_threshold,
    )


# ============================================================================
# Polymarket Endpoints
# ============================================================================


@router.get("/polymarket/markets")
async def get_polymarket_markets(
    offset: int = 0, limit: int = 100, category: str | None = None
):
    """Get Polymarket CLOB markets with pagination."""
    try:
        from backend.core.market_scanner import fetch_all_active_markets

        markets = await fetch_all_active_markets(
            category=category, limit=limit + offset if limit else None
        )
        # Apply pagination
        paginated = markets[offset : offset + limit]
        return {
            "markets": [
                {
                    "ticker": m.ticker,
                    "slug": m.slug,
                    "question": m.question,
                    "category": m.category,
                    "yes_price": m.yes_price,
                    "no_price": m.no_price,
                    "volume": m.volume,
                    "liquidity": m.liquidity,
                    "end_date": m.end_date,
                }
                for m in paginated
            ],
            "total": len(markets),
            "offset": offset,
            "limit": limit,
        }
    except Exception as e:
        logger.error(
            f"Failed to fetch Polymarket markets: {e}"
        )
        return {"markets": [], "total": 0, "offset": offset, "limit": limit}


# ============================================================================
# Market Watch Endpoints
# ============================================================================


class MarketWatchCreate(BaseModel):
    ticker: str
    category: Optional[str] = None
    source: Optional[str] = "user"
    enabled: Optional[bool] = True


@router.get("/markets/watch")
async def list_market_watches(
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """List all watched markets."""
    rows = db.query(MarketWatch).order_by(MarketWatch.created_at.desc()).all()
    return {
        "items": [
            {
                "id": r.id,
                "ticker": r.ticker,
                "category": r.category,
                "source": r.source,
                "enabled": r.enabled,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.post("/markets/watch")
async def create_market_watch(
    body: MarketWatchCreate,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """Add a market to the watch list."""
    existing = db.query(MarketWatch).filter(MarketWatch.ticker == body.ticker).first()
    if existing:
        raise HTTPException(
            status_code=409, detail=f"Ticker '{body.ticker}' already watched"
        )

    row = MarketWatch(
        ticker=body.ticker,
        category=body.category,
        source=body.source or "user",
        enabled=body.enabled if body.enabled is not None else True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    return {
        "id": row.id,
        "ticker": row.ticker,
        "category": row.category,
        "source": row.source,
        "enabled": row.enabled,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.delete("/markets/watch/{watch_id}")
async def delete_market_watch(
    watch_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """Remove a market from the watch list."""
    row = db.query(MarketWatch).filter(MarketWatch.id == watch_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Watch entry not found")

    db.delete(row)
    db.commit()
    return {"status": "deleted"}
