"""ORM models for historical market data storage (candles, outcomes, weather)."""

from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Index
from sqlalchemy.sql import func

from backend.models.database import Base


class HistoricalCandle(Base):
    __tablename__ = "historical_candle"
    __table_args__ = (
        Index("ix_candle_source_ts", "source", "symbol", "timestamp", unique=True),
    )

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String(20), nullable=False)
    symbol = Column(String(30), nullable=False)
    timestamp = Column(DateTime, nullable=False)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, default=0.0)
    interval = Column(String(10), default="1m")
    created_at = Column(DateTime, server_default=func.now())


class MarketOutcome(Base):
    __tablename__ = "market_outcome"
    __table_args__ = (Index("ix_outcome_market", "market_ticker", "resolved_at"),)

    id = Column(Integer, primary_key=True, index=True)
    market_ticker = Column(String(256), nullable=False, index=True)
    platform = Column(String(20), nullable=False, default="polymarket")
    outcome = Column(String(20), nullable=False)
    final_price = Column(Float, nullable=True)
    resolution_time = Column(DateTime, nullable=True)
    volume = Column(Float, nullable=True)
    category = Column(String(100), nullable=True)
    raw_data = Column(Text, nullable=True)
    resolved_at = Column(DateTime, server_default=func.now())


class WeatherSnapshot(Base):
    __tablename__ = "weather_snapshot"
    __table_args__ = (Index("ix_weather_city_ts", "city", "timestamp"),)

    id = Column(Integer, primary_key=True, index=True)
    city = Column(String(100), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False)
    temperature_f = Column(Float, nullable=True)
    temperature_c = Column(Float, nullable=True)
    humidity = Column(Float, nullable=True)
    precipitation = Column(Float, nullable=True)
    wind_speed = Column(Float, nullable=True)
    condition = Column(String(50), nullable=True)
    source = Column(String(30), nullable=True)
    forecast_hour = Column(Integer, nullable=True)
    raw_data = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
