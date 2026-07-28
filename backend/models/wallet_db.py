"""Domain model: wallet — split from database.py.
Keeps backward compatibility via database.py re-exports.
"""
import json
from datetime import datetime, timezone
from typing import Optional
from loguru import logger

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    Boolean,
    JSON,
    Text,
    UniqueConstraint,
    Index,
)

from backend.models.base_db import Base

class BtcPriceSnapshot(Base):
    """Cached BTC prices for momentum calculation."""

    __tablename__ = "btc_price_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    price = Column(Float)
    source = Column(String, default="coingecko")



class CopyTraderEntry(Base):
    """Copy trader position entries mirrored from tracked wallets."""

    __tablename__ = "copy_trader_entries"

    id = Column(Integer, primary_key=True)
    wallet = Column(String, nullable=False, index=True)
    condition_id = Column(String, nullable=False)
    side = Column(String, nullable=False)  # "YES" or "NO"
    size = Column(Float, nullable=False)
    pnl = Column(Float, nullable=True, default=0.0)
    opened_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("wallet", "condition_id", "side", name="uq_copy_entry"),
    )


class MarketWatch(Base):
    __tablename__ = "market_watch"
    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String, nullable=False, unique=True, index=True)
    category = Column(String, nullable=True)
    source = Column(String, nullable=True)  # strategy name or "user"
    config = Column(Text, nullable=True)  # JSON string
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class WalletConfig(Base):
    __tablename__ = "wallet_config"
    id = Column(Integer, primary_key=True, index=True)
    address = Column(String, nullable=False, unique=True, index=True)
    pseudonym = Column(String, nullable=True)
    source = Column(String, default="user")  # "leaderboard", "user", "import"
    tags = Column(Text, nullable=True)  # JSON array string
    enabled = Column(Boolean, default=True)
    notes = Column(Text, nullable=True)
    added_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    whale_score = Column(Float, nullable=True)
    balance_cache = Column(
        Text, nullable=True
    )  # JSON: {"usdc_balance", "last_updated"}



class WhaleTransaction(Base):
    __tablename__ = "whale_transactions"
    id = Column(Integer, primary_key=True)
    tx_hash = Column(String, unique=True, index=True, nullable=False)
    wallet = Column(String, index=True, nullable=False)
    market_id = Column(String, index=True, nullable=True)
    side = Column(String, nullable=True)  # buy/sell
    size_usd = Column(Float, nullable=False)
    block_number = Column(Integer, nullable=True)
    observed_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )



class ProviderCredential(Base):
    """Key-value credential and config store for market providers.

    Replaces per-provider ENV vars with a flexible DB-backed store.
    Any number of providers can be configured without code changes.

    The store is read at provider startup via :class:`ProviderConfigStore`.
    ENV vars serve as a bootstrap fallback when no DB row exists.

    Naming convention for ENV var fallback:
        ``{PROVIDER_NAME_UPPER}_{CONFIG_KEY_UPPER}``
        e.g. provider_name="azuro", config_key="graph_url" → ``AZURO_GRAPH_URL``
    """

    __tablename__ = "provider_credentials"

    id = Column(Integer, primary_key=True, index=True)
    provider_name = Column(String, nullable=False, index=True)
    config_key = Column(String, nullable=False)
    config_value = Column(Text, nullable=True)
    is_secret = Column(Boolean, default=False, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("provider_name", "config_key", name="uq_provider_credentials"),
        Index("idx_provider_credentials_name", "provider_name"),
    )
