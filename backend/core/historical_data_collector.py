"""Historical data collector — BTC candles, market outcomes, weather snapshots."""

from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from backend.models.database import SessionLocal
from backend.config import settings

from loguru import logger
class HistoricalDataCollector:
    """Collects and stores historical market data from live feeds."""

    async def collect_btc_candles(self, db: Optional[Session] = None) -> int:
        _owned = db is None
        db = db or SessionLocal()
        stored = 0
        try:
            from backend.models.historical_data import HistoricalCandle

            cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
            latest = (
                db.query(HistoricalCandle.timestamp)
                .filter(HistoricalCandle.source == "binance", HistoricalCandle.symbol == "BTCUSDT")
                .order_by(HistoricalCandle.timestamp.desc())
                .first()
            )
            since = latest[0] if latest else cutoff

            candles = await self._fetch_binance_klines(since)
            for c in candles:
                exists = (
                    db.query(HistoricalCandle.id)
                    .filter(
                        HistoricalCandle.source == "binance",
                        HistoricalCandle.symbol == "BTCUSDT",
                        HistoricalCandle.timestamp == c["timestamp"],
                    )
                    .first()
                )
                if exists:
                    continue
                row = HistoricalCandle(
                    source="binance",
                    symbol="BTCUSDT",
                    timestamp=c["timestamp"],
                    open=c["open"],
                    high=c["high"],
                    low=c["low"],
                    close=c["close"],
                    volume=c["volume"],
                    interval=c.get("interval", "1m"),
                )
                db.add(row)
                stored += 1
            if stored:
                db.commit()
            return stored
        except Exception as e:
            logger.warning("BTC candle collection failed: %s", e)
            if _owned:
                try:
                    db.rollback()
                except Exception:
                    logger.exception("[HistoricalDataCollector] Rollback failed after BTC candle collection error")
            return 0
        finally:
            if _owned:
                db.close()

    async def collect_market_outcomes(self, db: Optional[Session] = None) -> int:
        _owned = db is None
        db = db or SessionLocal()
        stored = 0
        try:
            from backend.models.historical_data import MarketOutcome

            settled_markets = await self._fetch_settled_markets()
            for m in settled_markets:
                exists = (
                    db.query(MarketOutcome.id)
                    .filter(MarketOutcome.market_ticker == m["ticker"])
                    .first()
                )
                if exists:
                    continue
                row = MarketOutcome(
                    market_ticker=m["ticker"],
                    platform=m.get("platform", "polymarket"),
                    outcome=m.get("outcome", "unknown"),
                    final_price=m.get("final_price"),
                    resolution_time=m.get("resolution_time"),
                    volume=m.get("volume"),
                    category=m.get("category"),
                    raw_data=m.get("raw_data"),
                )
                db.add(row)
                stored += 1
            if stored:
                db.commit()
            return stored
        except Exception as e:
            logger.warning("Market outcome collection failed: %s", e)
            if _owned:
                try:
                    db.rollback()
                except Exception:
                    logger.exception("[HistoricalDataCollector] Rollback failed after market outcome collection error")
            return 0
        finally:
            if _owned:
                db.close()

    async def collect_weather_snapshots(self, db: Optional[Session] = None) -> int:
        _owned = db is None
        db = db or SessionLocal()
        stored = 0
        try:
            from backend.models.historical_data import WeatherSnapshot

            snapshots = await self._fetch_weather_data()
            for w in snapshots:
                exists = (
                    db.query(WeatherSnapshot.id)
                    .filter(
                        WeatherSnapshot.city == w["city"],
                        WeatherSnapshot.timestamp == w["timestamp"],
                        WeatherSnapshot.source == w.get("source", "open-meteo"),
                    )
                    .first()
                )
                if exists:
                    continue
                row = WeatherSnapshot(
                    city=w["city"],
                    timestamp=w["timestamp"],
                    temperature_f=w.get("temperature_f"),
                    temperature_c=w.get("temperature_c"),
                    humidity=w.get("humidity"),
                    precipitation=w.get("precipitation"),
                    wind_speed=w.get("wind_speed"),
                    condition=w.get("condition"),
                    source=w.get("source", "open-meteo"),
                    forecast_hour=w.get("forecast_hour"),
                )
                db.add(row)
                stored += 1
            if stored:
                db.commit()
            return stored
        except Exception as e:
            logger.warning("Weather snapshot collection failed: %s", e)
            if _owned:
                try:
                    db.rollback()
                except Exception:
                    logger.exception("[HistoricalDataCollector] Rollback failed after weather snapshot collection error")
            return 0
        finally:
            if _owned:
                db.close()

    async def run_collection_cycle(self) -> dict:
        results = {}
        results["btc_candles"] = await self.collect_btc_candles()
        results["market_outcomes"] = await self.collect_market_outcomes()
        results["weather_snapshots"] = await self.collect_weather_snapshots()
        total = sum(results.values())
        logger.info("Historical data collection: %s (%d total rows)", results, total)
        return results

    async def _fetch_binance_klines(
        self, since: datetime, max_batches: int = 60
    ) -> list[dict]:
        """Fetch BTC 1m candles from Binance, paginating backwards from *since*.

        Each batch fetches up to 500 candles (~8 h).  With ``max_batches=60``
        we cover up to ~20 days of 1-minute history.
        """
        try:
            import httpx

            url = settings.BINANCE_KLINES_URL
            lookback_start = since - timedelta(days=20)
            start_ms = int(lookback_start.timestamp() * 1000)
            end_ms = int(since.timestamp() * 1000)

            all_candles: list[dict] = []
            async with httpx.AsyncClient(timeout=15.0) as client:
                for _ in range(max_batches):
                    params = {
                        "symbol": "BTCUSDT",
                        "interval": "1m",
                        "startTime": start_ms,
                        "endTime": end_ms,
                        "limit": 500,
                    }
                    resp = await client.get(url, params=params)
                    resp.raise_for_status()
                    data = resp.json()
                    if not data:
                        break

                    for k in data:
                        all_candles.append({
                            "timestamp": datetime.fromtimestamp(
                                k[0] / 1000, tz=timezone.utc
                            ),
                            "open": float(k[1]),
                            "high": float(k[2]),
                            "low": float(k[3]),
                            "close": float(k[4]),
                            "volume": float(k[5]),
                            "interval": "1m",
                        })

                    last_ts = data[-1][0] + 60_000
                    if last_ts >= end_ms:
                        break
                    start_ms = last_ts

            return all_candles
        except Exception as e:
            logger.warning("Binance kline fetch failed: %s", e)
            return []

    async def _fetch_settled_markets(self) -> list[dict]:
        try:
            from backend.data.gamma import fetch_settled_markets as gamma_fetch

            return await gamma_fetch()
        except Exception as e:
            logger.debug("Settled market fetch failed: %s", e)
            return []

    async def _fetch_weather_data(self) -> list[dict]:
        try:
            from backend.data.weather import fetch_current_conditions

            return await fetch_current_conditions()
        except Exception as e:
            logger.debug("Weather fetch failed: %s", e)
            return []


historical_data_collector = HistoricalDataCollector()
