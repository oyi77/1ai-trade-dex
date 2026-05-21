"""ORM models for multi-wallet trading: TradingWallet, WalletAllocation, CopyPolicy."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from backend.models.database import Base


class TradingWallet(Base):
    """Stores per-wallet credentials and metadata for order fan-out."""

    __tablename__ = "trading_wallets"

    id = Column(Integer, primary_key=True, index=True)
    label = Column(String, unique=True, nullable=False, index=True)
    chain = Column(String, nullable=False)  # "polymarket" | "kalshi" | "sxbet" | "limitless" | "ostium" | "aster" | "lighter" | "hyperliquid"
    address = Column(String, unique=True, nullable=False, index=True)
    encrypted_private_key = Column(Text, nullable=True)  # Fernet-encrypted
    api_key = Column(String, nullable=True)  # Kalshi REST API key
    encrypted_api_secret = Column(Text, nullable=True)  # Fernet-encrypted
    enabled = Column(Boolean, default=True, nullable=False)
    is_paper = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    notes = Column(Text, nullable=True)


class WalletAllocation(Base):
    """N↔N binding between a strategy and a TradingWallet with allocation weight."""

    __tablename__ = "wallet_allocations"
    __table_args__ = (
        UniqueConstraint("strategy_name", "wallet_id", name="uq_strategy_wallet"),
        CheckConstraint(
            "weight >= 0.0 AND weight <= 1.0", name="ck_wallet_allocation_weight"
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    strategy_name = Column(
        String,
        ForeignKey("strategy_config.strategy_name", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    wallet_id = Column(
        Integer,
        ForeignKey("trading_wallets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    weight = Column(Float, nullable=False, default=1.0)  # 0.0–1.0 allocation fraction
    max_exposure_usd = Column(Float, nullable=True)
    enabled = Column(Boolean, default=True, nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class CopyPolicy(Base):
    """Per-source policy governing copy-trade signal filtering and sizing."""

    __tablename__ = "copy_policies"

    id = Column(Integer, primary_key=True, index=True)
    source_name = Column(String, unique=True, nullable=False, index=True)
    enabled = Column(Boolean, default=True, nullable=False)
    max_size_usd = Column(Float, default=50.0, nullable=False)
    confidence_floor = Column(Float, default=0.6, nullable=False)
    max_delay_seconds = Column(Integer, default=30, nullable=False)
    size_scale_factor = Column(Float, default=1.0, nullable=False)
    cooldown_seconds = Column(Integer, default=60, nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
