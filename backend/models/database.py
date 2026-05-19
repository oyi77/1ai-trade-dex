"""Database models and connection for BTC 5-min trading bot."""

import os
import re
from datetime import datetime, timezone

from loguru import logger

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Float,
    DateTime,
    Boolean,
    JSON,
    Text,
    text,
    UniqueConstraint,
    ForeignKey,
    Index,
    Enum,
)
from sqlalchemy import event
from sqlalchemy.orm import Session as SQLAlchemySession, declarative_base, relationship
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm import sessionmaker
from sqlalchemy import inspect
from sqlalchemy.ext.hybrid import hybrid_property
import json
import asyncio

from backend.config import settings

_is_postgres = settings.is_postgres

_engine_kwargs = {
    "pool_pre_ping": True,
    "pool_timeout": settings.POSTGRES_POOL_TIMEOUT,
    "pool_recycle": settings.POSTGRES_POOL_RECYCLE,
}

if _is_postgres:
    _engine_kwargs.update({
        "pool_size": settings.POSTGRES_POOL_SIZE,
        "max_overflow": settings.POSTGRES_MAX_OVERFLOW,
    })
else:
    # SQLite needs generous pool for concurrent strategy cycles + API + workers
    _engine_kwargs.update({
        "pool_size": 20,
        "max_overflow": 40,
        "pool_timeout": 120,
        "connect_args": {"check_same_thread": False},
    })

engine = create_engine(settings.DATABASE_URL, **_engine_kwargs)

_TS_TYPE = "TIMESTAMP" if "postgresql" in settings.DATABASE_URL else "DATETIME"
def configure_sqlite_wal(engine_obj):
    """Register a connect listener that enables WAL mode and performance PRAGMAs for SQLite."""
    if engine_obj.url.get_dialect().name != "sqlite":
        return

    @event.listens_for(engine_obj, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA cache_size=-64000")
        cursor.execute("PRAGMA mmap_size=268435456")
        cursor.execute("PRAGMA wal_autocheckpoint=1000")
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


configure_sqlite_wal(engine)


def configure_postgres_lock_timeout(engine_obj):
    if engine_obj.url.get_dialect().name != "postgresql":
        return

    @event.listens_for(engine_obj, "connect")
    def set_postgres_lock_timeout(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("SET lock_timeout = '5s'")
        cursor.execute("SET statement_timeout = '30s'")
        cursor.execute("SET idle_in_transaction_session_timeout = '60s'")
        cursor.close()


configure_postgres_lock_timeout(engine)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

botstate_mutex = asyncio.Lock()


POSTGRES_LOCK_TIMEOUT = "5s"
POSTGRES_STATEMENT_TIMEOUT = "30s"


def _apply_postgres_lock_timeouts(session) -> None:
    """Bound lock waits inside the current PostgreSQL transaction.

    Long-running scheduler jobs share the same AsyncIOScheduler event loop. If
    a stale PostgreSQL transaction holds the singleton BotState row, waiting
    indefinitely on SELECT ... FOR UPDATE can starve unrelated jobs such as
    settlement checks. SET LOCAL scopes these limits to the active transaction:
    the lock wait fails fast and rollback clears the settings, while SQLite and
    other dialects keep their existing no-op behavior.
    """
    if session.get_bind().dialect.name != "postgresql":
        return

    session.execute(
        text(
            f"SET LOCAL lock_timeout = '{POSTGRES_LOCK_TIMEOUT}'"
        )
    )
    session.execute(
        text(
            f"SET LOCAL statement_timeout = '{POSTGRES_STATEMENT_TIMEOUT}'"
        )
    )


def for_update(session, query):
    """Add FOR UPDATE clause on PostgreSQL. No-op on SQLite/MySQL.

    Uses a bounded blocking FOR UPDATE (without NOWAIT) so concurrent strategy
    jobs can wait briefly for the lock instead of immediately raising
    OperationalError or hanging behind stale transactions.  The
    previous NOWAIT behaviour caused a cascade: the lock loser raised
    OperationalError whose message contained SQLAlchemy bind-param dicts like
    ``{'mode_1': 'paper'}``; loguru then tried to format that string and
    raised ``KeyError: "'mode_1'"``, crashing the strategy job.

    For SQLite, use ``botstate_mutex`` alongside this for read-modify-write
    patterns on BotState to prevent lost updates under concurrent async access.
    """
    if session.get_bind().dialect.name == "postgresql":
        _apply_postgres_lock_timeouts(session)
        return query.with_for_update()
    return query


class TradeRole(str, Enum):
    MAKER = "maker"
    TAKER = "taker"
    UNKNOWN = "unknown"


def _set_sqlite_busy_timeout(connection_or_session, timeout_ms: int) -> None:
    """Apply a shorter busy_timeout for best-effort SQLite bootstrap work."""

    # SQLAlchemy 2.0: Connection objects don't have get_bind(), only Session does
    try:
        bind = connection_or_session.get_bind()
        dialect_name = bind.dialect.name
    except AttributeError:
        dialect_name = connection_or_session.dialect.name

    if dialect_name != "sqlite":
        return

    try:
        connection_or_session.execute(text(f"PRAGMA busy_timeout={int(timeout_ms)}"))
    except Exception as exc:
        logger.debug(f"Could not set SQLite busy_timeout={timeout_ms}: {exc}")

try:
    import backend.models.kg_models  # noqa: F401 — registers ExperimentRecord, StrategyProposal with Base.metadata
    import backend.models.outcome_tables  # noqa: F401 — registers learning tables with Base.metadata (requires kg_models first)
    import backend.models.historical_data  # noqa: F401 — registers HistoricalCandle, MarketOutcome, WeatherSnapshot
except Exception:
    logger.exception("database model imports failed")
    pass


async def execute_with_timeout(db_operation, timeout: float = None):
    """
    Execute a database operation with timeout.

    Args:
        db_operation: Callable that performs the database operation
        timeout: Timeout in seconds (defaults to DATABASE_QUERY_TIMEOUT from settings)

    Returns:
        Result of the database operation

    Raises:
        asyncio.TimeoutError: If operation exceeds timeout
    """
    if timeout is None:
        timeout = settings.DATABASE_QUERY_TIMEOUT

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(db_operation),
            timeout=timeout
        )
        return result
    except asyncio.TimeoutError:
        logger.error(f"Database query timeout after {timeout}s")
        from backend.monitoring.metrics import increment_timeouts
        increment_timeouts(timeout_type="database")
        raise


class Trade(Base):
    """Simulated and live trades for tracking P&L."""

    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    signal_id = Column(
        Integer,
        ForeignKey("signals.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Core trade identifiers
    market_ticker = Column(String, index=True)
    platform = Column(String)
    strategy = Column(String, nullable=True, index=True)
    trading_mode = Column(String, default="paper", index=True)
    market_type = Column(String, default="btc", index=True)  # "btc" or "weather"
    event_slug = Column(String, nullable=True)
    market_end_date = Column(DateTime, nullable=True)
    token_id = Column(String, nullable=True, index=True)
    condition_id = Column(String, nullable=True)

    # Trade direction, entry, and size
    direction = Column(String)  # "up" or "down"
    entry_price = Column(Float)
    size = Column(Float)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    # Execution and cost tracking
    source = Column(String, default="bot", index=True)  # "bot", "user", "import"
    role = Column(String(10), default="unknown", index=True)  # maker, taker, unknown
    clob_order_id = Column(String, nullable=True, index=True)
    clob_idempotency_key = Column(String, nullable=True)
    filled_size = Column(Float, nullable=True)
    fill_price = Column(Float, nullable=True)
    fill_ratio = Column(Float, nullable=True)
    fee = Column(Float, nullable=True)
    slippage = Column(Float, nullable=True)

    # Signal metadata
    signal_source = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)
    model_probability = Column(Float, nullable=True)
    market_price_at_entry = Column(Float, nullable=True)
    edge_at_entry = Column(Float, nullable=True)
    data_quality_flags = Column(Text, nullable=True)

    # CLOB identifiers
    token_id = Column(String, nullable=True, index=True)
    condition_id = Column(String, nullable=True, index=True)

    # Blockchain verification
    blockchain_verified = Column(Boolean, default=False)
    settlement_source = Column(String, nullable=True)
    last_sync_at = Column(DateTime, nullable=True)
    external_import_at = Column(DateTime, nullable=True)
    status = Column(String, nullable=True)

    # Settlement
    settled = Column(Boolean, default=False)
    settlement_time = Column(DateTime, nullable=True)
    settlement_value = Column(Float, nullable=True)  # 1.0=Up won, 0.0=Down won
    result = Column(
        String, default="pending"
    )  # pending, win, loss, expired, push, closed
    pnl = Column(Float, nullable=True)

    # Journal
    journal_notes = Column(Text, nullable=True)
    journal_tags = Column(JSON, nullable=True)  # list of tag strings


class HFTExecutionRecord(Base):
    """Audit trail for HFT strategy executions."""

    __tablename__ = "hft_execution_records"

    execution_id = Column(String, primary_key=True)
    signal_id = Column(String, index=True)
    order_id = Column(String, nullable=True)
    side = Column(String)  # "BUY" or "SELL"
    size = Column(Float)
    price = Column(Float)
    execution_latency_ms = Column(Float)
    status = Column(String)  # "pending", "filled", "failed", "queued", "cancelled"
    error = Column(String, nullable=True)
    timestamp = Column(Float)  # unix timestamp
    created_at = Column(DateTime, server_default=text("(CURRENT_TIMESTAMP)"), index=True)

    # Model performance tracking
    model_probability = Column(Float)
    market_price_at_entry = Column(Float)
    edge_at_entry = Column(Float)

    # Trading mode this trade was placed in
    trading_mode = Column(String, default="paper", index=True)
    role = Column(String, default="unknown", index=True)  # maker, taker, unknown

    # Strategy tracking
    strategy = Column(String, nullable=True)
    signal_source = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)

    # Partial fill tracking
    filled_size = Column(
        Float, nullable=True
    )  # actual fill amount, None = assumed full fill
    fill_price = Column(
        Float, nullable=True
    )  # actual fill price, None = assumed entry_price
    fill_ratio = Column(
        Float, nullable=True
    )  # fill_ratio = filled_size / size, None = assumed 1.0

    # On-chain order tracking (testnet / live modes)
    clob_order_id = Column(
        String, nullable=True
    )  # Order ID returned by Polymarket CLOB
    clob_idempotency_key = Column(
        String, nullable=True
    )  # UUID idempotency key per order attempt

    # Market end date for settlement tracking (when the market expires)
    market_end_date = Column(DateTime, nullable=True, index=True)

    # Fee and slippage tracking
    fee = Column(Float, nullable=True)
    slippage = Column(Float, nullable=True)

    # Reconciliation fields for blockchain sync
    source = Column(String, nullable=False, default="bot", index=True)
    blockchain_verified = Column(Boolean, nullable=False, default=False)
    settlement_source = Column(String, nullable=True, default=None)
    last_sync_at = Column(DateTime, nullable=True, default=None, index=True)
    external_import_at = Column(DateTime, nullable=True, default=None)


class GenomeRegistry(Base):
    """Registry of genetic algorithms and their configurations."""

    __tablename__ = "genome_registry"

    genome_id = Column(String, primary_key=True, index=True)  # UUID or identifier
    strategy_name = Column(String, nullable=False, index=True)
    archetype = Column(String, nullable=False)
    version = Column(String, nullable=False)
    stage = Column(String, nullable=False, index=True)  # DRAFT, SHADOW, PAPER, LIVE, GRAVEYARD
    lineage_json = Column(Text, nullable=False)
    chromosomes_json = Column(Text, nullable=False)
    fitness_json = Column(Text, nullable=False)
    chromosome_perf_json = Column(Text, nullable=True)
    death_certificate_json = Column(Text, nullable=True)

    # Native columns derived from fitness_json for efficient querying
    fitness_score = Column(Float, nullable=True, index=True)  # 0.0–1.0 composite score
    fitness_updated_at = Column(DateTime, nullable=True)  # when fitness was last recalculated
    total_pnl = Column(Float, nullable=True, default=0.0)
    win_rate = Column(Float, nullable=True, default=0.0)
    sharpe_ratio = Column(Float, nullable=True, default=0.0)
    max_drawdown_pct = Column(Float, nullable=True, default=0.0)
    trade_count = Column(Integer, nullable=True, default=0)
    last_evaluated_at = Column(DateTime, nullable=True)
    stage_entered_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=True)

    # Relationships
    evolution_logs = relationship("EvolutionLog", back_populates="genome", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_genome_stage_score", "stage", "fitness_score"),
        Index("idx_genome_stage_winrate", "stage", "win_rate"),
        Index("idx_genome_archetype_stage", "archetype", "stage"),
    )

    @hybrid_property
    def fitness_metrics(self) -> dict:
        """Deserialize fitness_json into a dict on read."""
        if self.fitness_json:
            try:
                return json.loads(self.fitness_json)
            except (json.JSONDecodeError, TypeError):
                pass
        return {}

    @fitness_metrics.setter
    def fitness_metrics(self, value: dict):
        """Serialize fitness_metrics dict into fitness_json on write."""
        self.fitness_json = json.dumps(value) if value else "{}"

    @hybrid_property
    def lineage(self) -> dict:
        if self.lineage_json:
            try:
                return json.loads(self.lineage_json)
            except (json.JSONDecodeError, TypeError):
                pass
        return {}

    @lineage.setter
    def lineage(self, value: dict):
        self.lineage_json = json.dumps(value) if value else "{}"

    @hybrid_property
    def chromosomes(self) -> dict:
        if self.chromosomes_json:
            try:
                return json.loads(self.chromosomes_json)
            except (json.JSONDecodeError, TypeError):
                pass
        return {}

    @chromosomes.setter
    def chromosomes(self, value: dict):
        self.chromosomes_json = json.dumps(value) if value else "{}"

    @hybrid_property
    def chromosome_performance(self) -> dict:
        if self.chromosome_perf_json:
            try:
                return json.loads(self.chromosome_perf_json)
            except (json.JSONDecodeError, TypeError):
                pass
        return {}

    @chromosome_performance.setter
    def chromosome_performance(self, value: dict):
        self.chromosome_perf_json = json.dumps(value) if value else "{}"

class ShadowTrade(Base):
    """Shadow trades for strategy validation without real capital."""

    __tablename__ = "shadow_trade"

    id = Column(Integer, primary_key=True, index=True)
    market_ticker = Column(String, index=True)
    direction = Column(String)  # 'up' or 'down'
    entry_price = Column(Float)
    size = Column(Float)
    model_probability = Column(Float)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    strategy = Column(String, index=True)
    settled = Column(Boolean, default=False)
    settlement_value = Column(Float, nullable=True)
    pnl = Column(Float, nullable=True)
    accuracy_score = Column(Float, nullable=True)
    genome_id = Column(String, ForeignKey("genome_registry.genome_id", ondelete="SET NULL"), nullable=True, index=True)
    predicted_outcome = Column(Float, nullable=True)
    actual_outcome = Column(Float, nullable=True)


class BtcPriceSnapshot(Base):
    """Cached BTC prices for momentum calculation."""

    __tablename__ = "btc_price_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    price = Column(Float)
    source = Column(String, default="coingecko")


class BotState(Base):
    """Bot state and statistics."""

    __tablename__ = "bot_state"

    id = Column(Integer, primary_key=True)
    mode = Column(String, unique=True, index=True, default="paper")
    bankroll = Column(Float, default=100.0)
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    total_pnl = Column(Float, default=0.0)
    last_run = Column(DateTime, nullable=True)
    is_running = Column(Boolean, default=False)

    # Sync metadata for reconciliation tracking
    last_sync_at = Column(DateTime, nullable=True, default=None)
    last_live_sync_error = Column(String, nullable=True, default=None)

    # Active wallet for multi-wallet management
    active_wallet = Column(String, nullable=True, index=True)

    # Paper trading tracking
    paper_bankroll = Column(Float, default=100.0)
    paper_pnl = Column(Float, default=0.0)
    paper_trades = Column(Integer, default=0)
    paper_wins = Column(Integer, default=0)
    paper_initial_bankroll = Column(Float, nullable=True, default=None,
                                    doc="Effective initial bankroll for paper mode including top-ups. "
                                        "None means use settings.INITIAL_BANKROLL.")

    # Testnet trading tracking (isolated from live)
    testnet_bankroll = Column(Float, default=100.0)
    testnet_pnl = Column(Float, default=0.0)
    testnet_trades = Column(Integer, default=0)
    testnet_wins = Column(Integer, default=0)
    testnet_initial_bankroll = Column(Float, nullable=True, default=None,
                                      doc="Effective initial bankroll for testnet mode including top-ups. "
                                          "None means use 100.")

    # Live trading tracking
    live_initial_bankroll = Column(Float, nullable=True, default=None,
                                   doc="Effective initial bankroll for live mode. "
                                       "Set on first sync from settings.INITIAL_BANKROLL. "
                                       "Deposits do NOT update this — it stays anchored so PnL "
                                       "reflects only trading performance, never capital injections.")

    # Generic JSON blob for strategy heartbeats and ad-hoc state
    misc_data = Column(Text, nullable=True)

    # Settlement verification tracking
    settlement_last_check_at = Column(DateTime, nullable=True, default=None)

    # Wallet reconciliation tracking
    total_deposits = Column(Float, default=0.0)
    total_withdrawals = Column(Float, default=0.0)
    last_wallet_sync_at = Column(DateTime, nullable=True)
    wallet_pnl = Column(Float, default=0.0)

    def __repr__(self):
        return (f"<BotState(id={self.id}, mode={self.mode}, bankroll={self.bankroll}, "
                f"total_pnl={self.total_pnl}, total_trades={self.total_trades}, "
                f"winning_trades={self.winning_trades})>")


@event.listens_for(SQLAlchemySession, "before_flush")
def protect_live_bot_state_financial_fields(session, flush_context, instances):
    """Prevent stale ORM sessions from overwriting live equity caches.

    Live bankroll and total_pnl are derived from external account equity via
    bankroll_reconciliation. Normal runtime sessions may still update live
    metadata and counters, but direct ORM changes to these financial fields are
    reverted unless a caller explicitly opts in with
    session.info["allow_live_financial_update"] = True.
    """

    if session.info.get("allow_live_financial_update"):
        return

    for obj in session.dirty:
        if not isinstance(obj, BotState) or obj.mode != "live":
            continue

        inspected = inspect(obj)
        for field_name in ("bankroll", "total_pnl"):
            history = inspected.attrs[field_name].history
            if not history.has_changes():
                continue
            previous = history.deleted[0] if history.deleted else None
            set_committed_value(obj, field_name, previous)
            logger.warning(
                "Blocked unauthorized live BotState.%s ORM mutation; use bankroll_reconciliation instead",
                field_name,
            )


class Signal(Base):
    """Trading signals generated by the bot."""

    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, index=True)
    market_ticker = Column(String, index=True)
    platform = Column(String)
    market_type = Column(String, default="btc", index=True)  # "btc" or "weather"
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    direction = Column(String)
    model_probability = Column(Float)
    market_price = Column(Float)
    edge = Column(Float)
    confidence = Column(Float)

    kelly_fraction = Column(Float)
    suggested_size = Column(Float)

    sources = Column(JSON)
    reasoning = Column(String)

    # Edge discovery tracking
    track_name = Column(
        String, nullable=True, default="legacy", index=True
    )  # Which edge track generated this signal
    execution_mode = Column(String, nullable=True, default="paper")  # 'paper' or 'live'
    token_id = Column(String, nullable=True)

    executed = Column(Boolean, default=False)

    # Calibration tracking — filled after settlement
    actual_outcome = Column(
        String, nullable=True
    )  # "up" or "down" — actual market result
    outcome_correct = Column(
        Boolean, nullable=True
    )  # did our direction prediction match?
    settlement_value = Column(Float, nullable=True)  # 1.0=UP won, 0.0=DOWN won
    settled_at = Column(DateTime, nullable=True)  # when we recorded the outcome


class AILog(Base):
    """Log of all AI API calls."""

    __tablename__ = "ai_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    provider = Column(String, index=True)
    model = Column(String)

    prompt = Column(String)
    response = Column(String)
    call_type = Column(String, index=True)

    latency_ms = Column(Float)
    tokens_used = Column(Integer)
    cost_usd = Column(Float)

    related_market = Column(String, nullable=True)
    success = Column(Boolean, default=True)
    error = Column(String, nullable=True)


class EMOSCalibrationState(Base):
    __tablename__ = "emos_calibration_state"
    city = Column(String, primary_key=True)
    obs_pairs_json = Column(Text, nullable=False)
    a = Column(Float, nullable=False)
    b = Column(Float, nullable=False)
    last_updated = Column(DateTime, nullable=True)

class ScanLog(Base):
    """Log of each market scan run."""

    __tablename__ = "scan_logs"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(String, unique=True, index=True)
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)

    categories_scanned = Column(JSON)
    platforms_scanned = Column(JSON)

    markets_found = Column(Integer, default=0)
    signals_generated = Column(Integer, default=0)
    trades_executed = Column(Integer, default=0)

    ai_calls_made = Column(Integer, default=0)
    ai_cost_usd = Column(Float, default=0.0)

    success = Column(Boolean, default=True)
    error = Column(String, nullable=True)


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


class SettlementEvent(Base):
    __tablename__ = "settlement_events"

    id = Column(Integer, primary_key=True)
    trade_id = Column(Integer, ForeignKey("trades.id"), nullable=False)
    market_ticker = Column(String, nullable=False, index=True)
    resolved_outcome = Column(String)  # "up", "down", "yes", "no"
    pnl = Column(Float)
    settled_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    source = Column(String, default="polymarket")  # "polymarket" or "kalshi"


class DecisionLog(Base):
    __tablename__ = "decision_log"
    id = Column(Integer, primary_key=True, index=True)
    strategy = Column(String, nullable=False, index=True)
    market_ticker = Column(String, nullable=False, index=True)
    decision = Column(String, nullable=False)  # BUY, SKIP, SELL, HOLD, ERROR
    confidence = Column(Float, nullable=True)
    signal_data = Column(Text, nullable=True)  # JSON string
    reason = Column(Text, nullable=True)
    outcome = Column(String, nullable=True)  # WIN, LOSS, PUSH — filled at settlement
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )


class TradeAttempt(Base):
    """Durable execution-attempt ledger for explaining why trades happen or stop."""

    __tablename__ = "trade_attempts"

    id = Column(Integer, primary_key=True, index=True)
    attempt_id = Column(String, nullable=False, unique=True, index=True)
    correlation_id = Column(String, nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        index=True,
    )

    strategy = Column(String, nullable=False, index=True)
    mode = Column(String, nullable=False, index=True)
    market_ticker = Column(String, nullable=False, index=True)
    platform = Column(String, nullable=True)
    direction = Column(String, nullable=True)
    decision = Column(String, nullable=True)

    status = Column(String, nullable=False, default="STARTED", index=True)
    phase = Column(String, nullable=False, default="created", index=True)
    reason_code = Column(String, nullable=False, default="ATTEMPT_STARTED", index=True)
    reason = Column(Text, nullable=True)

    confidence = Column(Float, nullable=True)
    edge = Column(Float, nullable=True)
    requested_size = Column(Float, nullable=True)
    adjusted_size = Column(Float, nullable=True)
    entry_price = Column(Float, nullable=True)
    bankroll = Column(Float, nullable=True)
    current_exposure = Column(Float, nullable=True)
    risk_allowed = Column(Boolean, nullable=True)
    risk_reason = Column(Text, nullable=True)

    trade_id = Column(Integer, ForeignKey("trades.id"), nullable=True, index=True)
    order_id = Column(String, nullable=True, index=True)
    latency_ms = Column(Float, nullable=True)

    factors_json = Column(Text, nullable=True)
    decision_data = Column(Text, nullable=True)
    signal_data = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_trade_attempts_mode_status_created", "mode", "status", "created_at"),
        Index("idx_trade_attempts_strategy_created", "strategy", "created_at"),
        Index("idx_trade_attempts_reason_created", "reason_code", "created_at"),
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


class StrategyConfig(Base):
    __tablename__ = "strategy_config"
    id = Column(Integer, primary_key=True, index=True)
    strategy_name = Column(String, nullable=False, unique=True, index=True)
    enabled = Column(Boolean, default=False)
    params = Column(Text, nullable=True)  # JSON string
    interval_seconds = Column(Integer, default=60)
    trading_mode = Column(
        String, nullable=True
    )  # "paper", "testnet", "live" - overrides global TRADING_MODE
    mode = Column(String, nullable=True, default=None)  # "paper", "testnet", "live" - NULL = applies to all modes
    time_horizon = Column(String, nullable=True, default="mid")  # "short", "mid", "long"
    risk_tier = Column(String, nullable=True, default="moderate")  # "safe", "conservative", "moderate", "aggressive", "extreme", "crazy"
    disabled_at = Column(DateTime, nullable=True, default=None)
    rehab_allocation_pct = Column(Float, nullable=True, default=None)  # graduated rehab: 25→50→75→100
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class TradeContext(Base):
    __tablename__ = "trade_context"
    trade_id = Column(Integer, ForeignKey("trades.id"), primary_key=True)
    strategy = Column(String, nullable=True)
    signal_source = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)
    entry_signal = Column(Text, nullable=True)  # JSON string
    exit_signal = Column(Text, nullable=True)  # JSON string
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ScheduledJob(Base):
    """Persistent APScheduler job state for crash recovery.

    Stores the registration metadata of every scheduled job so the scheduler
    can rebuild its in-memory job table after a restart. The `job_state_json`
    column captures trigger kwargs (interval, cron, etc.), function id, and
    execution kwargs needed to re-add the job via APScheduler.
    """

    __tablename__ = "scheduled_jobs"

    id = Column(Integer, primary_key=True, index=True)
    job_name = Column(String(255), unique=True, nullable=False, index=True)
    job_state_json = Column(JSON, nullable=False)
    last_run = Column(DateTime, nullable=True)
    next_run = Column(DateTime, nullable=True)
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class JobQueue(Base):
    """Persistent job queue for crash recovery."""

    __tablename__ = "job_queue"

    id = Column(Integer, primary_key=True, index=True)
    job_type = Column(String(50), nullable=False)
    idempotency_key = Column(String(255), nullable=True)
    priority = Column(String(20), default="medium")  # critical, high, medium, low
    status = Column(
        String(20), default="pending"
    )  # pending, processing, completed, failed
    payload = Column(JSON, nullable=False)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    scheduled_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("idx_job_queue_status_priority", "status", "priority"),
        UniqueConstraint("job_type", "idempotency_key", name="uq_job_idempotency"),
    )


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


class PendingApproval(Base):
    __tablename__ = "pending_approvals"
    id = Column(Integer, primary_key=True)
    market_id = Column(String, index=True, nullable=False)
    direction = Column(String, nullable=False)
    size = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)
    signal_data = Column(JSON, nullable=True)
    status = Column(String, default="pending")  # pending|approved|rejected
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    decided_at = Column(DateTime, nullable=True)


class ActivityLog(Base):
    """Log of all strategy decisions and trading activity."""
    __tablename__ = "activity_log"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    strategy_name = Column(String(100), nullable=False, index=True)
    decision_type = Column(String(50), nullable=False)  # 'entry', 'exit', 'hold', 'adjustment'
    data = Column(JSON, nullable=False)  # Full decision context
    confidence_score = Column(Float, nullable=False)  # 0.0-1.0
    mode = Column(String(20), nullable=False)  # 'paper' or 'live'


class StrategyProposal(Base):
    """Proposed strategy changes awaiting admin approval."""
    __tablename__ = "strategy_proposal"

    id = Column(Integer, primary_key=True, index=True)
    strategy_name = Column(String(100), nullable=False, index=True)
    change_details = Column(JSON, nullable=False)
    expected_impact = Column(String(1000), nullable=False)
    admin_decision = Column(String(20), default="pending")
    status = Column(String(20), default="pending")
    auto_promotable = Column(Boolean, default=False)
    proposed_params = Column(JSON, nullable=True)
    backtest_passed = Column(Boolean, default=False)
    backtest_sharpe = Column(Float, nullable=True)
    backtest_win_rate = Column(Float, nullable=True)
    executed_at = Column(DateTime, nullable=True)
    impact_measured = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    admin_user_id = Column(String(100), nullable=True)
    admin_decision_reason = Column(Text, nullable=True)


class MiroFishSignal(Base):
    """AI-generated signals from Miro Fish debate engine for prediction markets."""
    __tablename__ = "mirofish_signal"

    id = Column(Integer, primary_key=True, index=True)
    market_id = Column(String(256), nullable=False, index=True, unique=True)
    prediction = Column(Float, nullable=False)  # 0.0-1.0
    confidence = Column(Float, nullable=False)  # 0.0-1.0
    reasoning = Column(Text, nullable=False)
    source = Column(String(50), default="mirofish", nullable=False)
    weight = Column(Float, default=1.0, nullable=False)  # Weight in debate engine
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class PerformanceMetric(Base):
    """Performance metrics for request timing, database queries, WebSocket latency, and system resources."""

    __tablename__ = "performance_metrics"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True, nullable=False)
    metric_type = Column(String, nullable=False, index=True)
    endpoint = Column(String, nullable=True, index=True)
    method = Column(String, nullable=True)
    status_code = Column(Integer, nullable=True)
    duration_ms = Column(Float, nullable=True)
    query_type = Column(String, nullable=True)
    query_duration_ms = Column(Float, nullable=True)
    ws_message_type = Column(String, nullable=True)
    ws_latency_ms = Column(Float, nullable=True)
    memory_usage_mb = Column(Float, nullable=True)
    memory_percent = Column(Float, nullable=True)
    cpu_percent = Column(Float, nullable=True)
    user_agent = Column(String, nullable=True)
    error_message = Column(String, nullable=True)

    __table_args__ = (
        Index('idx_metrics_type_timestamp', 'metric_type', 'timestamp'),
        Index('idx_metrics_endpoint_timestamp', 'endpoint', 'timestamp'),
    )


class AuditLog(Base):
    """Comprehensive audit log for all money-related operations."""
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    event_type = Column(String, nullable=False, index=True)  # TRADE_CREATED, SETTLEMENT_COMPLETED, POSITION_UPDATED, WALLET_RECONCILED
    entity_type = Column(String, nullable=False)  # TRADE, POSITION, WALLET, CONFIG
    entity_id = Column(String, nullable=False, index=True)  # trade_id, position_id, wallet_address
    old_value = Column(JSON, nullable=True)  # Previous state snapshot
    new_value = Column(JSON, nullable=True)  # New state snapshot
    user_id = Column(String, default="system")  # "system", "admin", "strategy:btc_5min"

    # Legacy fields for backward compatibility
    actor = Column(String, default="system")
    action = Column(String, nullable=True)
    details = Column(JSON, nullable=True)

class EvolutionLog(Base):
    """Log of genome evolution events and stage transitions."""

    __tablename__ = "evolution_log"

    id = Column(Integer, primary_key=True, index=True)
    genome_id = Column(String, ForeignKey("genome_registry.genome_id"), index=True)
    event_type = Column(String, index=True)  # promotion, mutation, crossover, auto_killed, etc.
    from_stage = Column(String, nullable=True)  # Source stage
    to_stage = Column(String, nullable=True)  # Target stage
    data = Column(JSON, default=lambda: {})  # Additional event data
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    # Relationships
    genome = relationship("GenomeRegistry", back_populates="evolution_logs")


class Experiment(Base):
    """Track parameter experiments for each strategy."""

    __tablename__ = "experiments"
    id = Column(Integer, primary_key=True, index=True)
    strategy_name = Column(
        String,
        ForeignKey("strategy_config.strategy_name", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    params_json = Column(JSON, nullable=False)
    metrics_json = Column(JSON, nullable=True)
    status = Column(String, default="candidate")  # candidate|active|retired
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    promoted_at = Column(DateTime, nullable=True)
    notes = Column(String, nullable=True)


class EquitySnapshot(Base):
    """Daily equity curve snapshots for performance tracking."""

    __tablename__ = "equity_snapshots"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    bankroll = Column(Float, nullable=False)
    total_pnl = Column(Float, default=0.0)
    open_exposure = Column(Float, default=0.0)
    strategy_allocations = Column(JSON, nullable=True)
    trade_count = Column(Integer, default=0)
    win_count = Column(Integer, default=0)


class CalibrationRecord(Base):
    """Track predicted probability vs actual outcome for model calibration."""

    __tablename__ = "calibration_records"
    id = Column(Integer, primary_key=True, index=True)
    strategy = Column(String, nullable=False, index=True)
    market_ticker = Column(String, nullable=False)
    predicted_prob = Column(Float, nullable=False)
    direction = Column(String, nullable=False)
    actual_outcome = Column(String, nullable=True)  # "win"|"loss"|None (pending)
    settlement_value = Column(Float, nullable=True)
    price_bucket = Column(String, nullable=True, index=True)  # e.g. "5-10c", "40-50c"
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ResearchItemDB(Base):
    __tablename__ = "research_items"
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    source = Column(String, nullable=False)
    url = Column(String, nullable=False)
    content_summary = Column(String)
    relevance_score = Column(Float, nullable=False)
    fingerprint = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    used_in_decision = Column(Boolean, default=False)


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    alert_type = Column(String, nullable=False, index=True)
    severity = Column(String, nullable=False)
    entity_type = Column(String, nullable=False)
    entity_id = Column(String, nullable=False)
    message = Column(String, nullable=False)
    resolved = Column(Boolean, default=False, index=True)
    resolved_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_alerts_type_severity", "alert_type", "severity"),
        Index("idx_alerts_resolved", "resolved"),
    )

    def __repr__(self):
        return (
            f"<Alert(id={self.id}, type={self.alert_type}, severity={self.severity}, "
            f"entity={self.entity_type}:{self.entity_id}, resolved={self.resolved})>"
        )


class AlertConfig(Base):
    __tablename__ = "alert_config"

    id = Column(Integer, primary_key=True)
    alert_type = Column(String, unique=True, nullable=False)
    enabled = Column(Boolean, default=True)
    threshold_value = Column(Float, nullable=True)
    threshold_unit = Column(String, nullable=True)
    severity = Column(String, default="WARNING")

    def __repr__(self):
        return (
            f"<AlertConfig(type={self.alert_type}, enabled={self.enabled}, "
            f"threshold={self.threshold_value} {self.threshold_unit})>"
        )


class TransactionEvent(Base):
    """Immutable ledger of all bankroll movements.

    Captures every deposit, withdrawal, trade P&L, reconciliation adjustment,
    and allocation change. Serves as the single source of truth for bankroll
    audit trails, profit analysis, and regulatory reporting.
    """

    __tablename__ = "transaction_events"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True, nullable=False
    )
    # Event type discriminator
    type = Column(
        Enum(
            "deposit",
            "settlement_win",
            "settlement_loss",
            "reconciliation_adjustment",
            "allocation",
            "fee",
            "withdrawal",
            name="transaction_event_type",
        ),
        nullable=False,
        index=True,
    )
    # Amount change (positive for inflow, negative for outflow)
    amount = Column(Float, nullable=False)
    # Bankroll balance immediately after this event (null if not yet reconciled)
    balance_after = Column(Float, nullable=True)
    # Optional context: strategy, market_ticker, trade_id, experiment_id, etc.
    context = Column(JSON, nullable=True)
    # Human-readable reason/note (optional)
    note = Column(String, nullable=True)


class Setting(Base):
    """Application settings persisted in database."""

    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, nullable=False, index=True)
    value = Column(Text, nullable=False)
    description = Column(String, nullable=True)
    type = Column(String, default="string")  # string, int, bool, float
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), index=True)
    updated_by_user_id = Column(String, nullable=True, default="system")

    def __repr__(self):
        return f"<Setting(key={self.key}, type={self.type}, value={self.value[:50]}...)>"


class SystemSettings(Base):
    """System settings for runtime configuration (MiroFish, strategies, risk params)."""

    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(JSON, nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<SystemSettings(key={self.key}, value={self.value})>"


class ErrorLog(Base):
    """Centralized error logging with structured context."""

    __tablename__ = "error_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True, nullable=False)
    error_type = Column(String(255), nullable=False, index=True)
    message = Column(Text, nullable=False)
    endpoint = Column(String(255), nullable=True, index=True)
    method = Column(String(10), nullable=True)
    user_id = Column(String(255), nullable=True, index=True)
    stack_trace = Column(Text, nullable=True)
    status_code = Column(Integer, nullable=True)
    request_id = Column(String(255), nullable=True, index=True)
    details = Column(Text, nullable=True)

    __table_args__ = (
        Index('idx_error_logs_type_timestamp', 'error_type', 'timestamp'),
        Index('idx_error_logs_endpoint_timestamp', 'endpoint', 'timestamp'),
    )


def _attempt_data_recovery(db_path: str) -> dict[str, list[dict]]:
    """Try to recover data from a corrupted SQLite database before wiping it.

    Uses sqlite3 directly (not SQLAlchemy) to maximize recovery chances
    on malformed databases. Returns {table_name: [row_dicts]} for any
    tables that could be read successfully. Returns empty dict for
    non-SQLite databases or missing files.
    """
    import sqlite3

    recovered: dict[str, list[dict]] = {}

    if not settings.DATABASE_URL.startswith("sqlite"):
        logger.info("Data recovery only supported for SQLite databases")
        return recovered

    if not os.path.exists(db_path):
        return recovered

    RECOVERABLE_TABLES = (
        "trades", "signals", "bot_state", "strategy_config",
        "decision_log", "trade_attempts", "market_watch", "wallet_config",
        "settlement_events", "equity_snapshots", "calibration_records",
        "activity_log", "ai_logs", "scan_logs",
    )

    try:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        cursor = conn.cursor()

        for table_name in RECOVERABLE_TABLES:
            try:
                cursor.execute(f'SELECT * FROM "{table_name}"')
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                if not columns:
                    continue
                rows = []
                for row in cursor.fetchall():
                    rows.append(dict(zip(columns, row)))
                if rows:
                    recovered[table_name] = rows
                    logger.info(f"Recovered {len(rows)} rows from {table_name}")
            except Exception as table_err:
                logger.warning(f"Could not recover table {table_name}: {table_err}")

        conn.close()
    except Exception as e:
        logger.warning(f"Data recovery attempt failed: {e}")

    return recovered


def _restore_recovered_data(recovered: dict[str, list[dict]]):
    """Re-insert recovered data into the fresh database.

    Uses per-table sessions with individual commits to isolate failures.
    Skips rows with IDs that already exist (idempotent). Only restores
    columns that exist on the target model to handle schema drift.
    """
    if not recovered:
        return

    model_map = {
        "trades": Trade,
        "signals": Signal,
        "bot_state": BotState,
        "strategy_config": StrategyConfig,
        "decision_log": DecisionLog,
        "trade_attempts": TradeAttempt,
        "market_watch": MarketWatch,
        "wallet_config": WalletConfig,
        "settlement_events": SettlementEvent,
        "equity_snapshots": EquitySnapshot,
        "calibration_records": CalibrationRecord,
        "activity_log": ActivityLog,
        "ai_logs": AILog,
        "scan_logs": ScanLog,
    }

    total_restored = 0
    total_skipped = 0

    for table_name, rows in recovered.items():
        model_class = model_map.get(table_name)
        if not model_class:
            logger.warning(f"No model mapping for {table_name} — {len(rows)} rows unrecoverable")
            continue

        db = SessionLocal()
        try:
            restored_in_table = 0
            for row_data in rows:
                try:
                    # Check if row already exists (idempotent)
                    row_id = row_data.get("id")
                    if row_id is not None:
                        existing = db.query(model_class).filter_by(id=row_id).first()
                        if existing:
                            total_skipped += 1
                            continue

                    # Only include columns the model actually has (handles schema drift)
                    clean_data = {
                        k: v for k, v in row_data.items()
                        if k != "id" and hasattr(model_class, k)
                    }
                    obj = model_class(**clean_data)
                    db.add(obj)
                    restored_in_table += 1
                except Exception as row_err:
                    db.rollback()
                    logger.warning(f"Could not restore row in {table_name}: {row_err}")

            db.commit()
            if restored_in_table > 0:
                logger.info(f"Restored {restored_in_table} rows to {table_name}")
                total_restored += restored_in_table
        except Exception as e:
            db.rollback()
            logger.warning(f"Failed to commit {table_name} recovery: {e}")
        finally:
            db.close()

    if total_restored > 0:
        logger.info(f"Recovery complete: {total_restored} rows restored, {total_skipped} skipped (already exist)")
    elif total_skipped > 0:
        logger.info(f"Recovery: all {total_skipped} rows already present, nothing to restore")


def _publish_corruption_alert(event: str, detail: str, data: dict | None = None):
    try:
        from backend.core.event_bus import publish_event
        publish_event(event, {
            "source": "database",
            "detail": detail,
            **(data or {}),
        })
    except Exception:
        logger.exception("database publish_corruption_alert failed")
        pass


def init_db(repair_if_needed: bool = True):
    try:
        Base.metadata.create_all(bind=engine, checkfirst=True)
        ensure_schema()
        seed_default_data()
    except Exception as e:
        if "database disk image is malformed" in str(e) and repair_if_needed:
            logger.warning(f"Database corrupted, attempting repair: {e}")
            _publish_corruption_alert("database_corruption_detected", str(e))

            db_path = settings.DATABASE_URL.replace("sqlite:///", "").replace("./", "")
            recovered = _attempt_data_recovery(db_path)
            recovered_table_count = len(recovered)
            recovered_row_count = sum(len(rows) for rows in recovered.values())
            logger.info(f"Recovered data from {recovered_table_count} table(s), {recovered_row_count} total rows before wiping")

            try:
                engine.dispose()

                if os.path.exists(db_path):
                    os.unlink(db_path)
                    logger.info(f"Removed corrupted database: {db_path}")

                Base.metadata.create_all(bind=engine, checkfirst=True)
                ensure_schema()
                seed_default_data()

                if recovered:
                    _restore_recovered_data(recovered)

                _publish_corruption_alert("database_repair_succeeded", "Database repaired after corruption", {
                    "tables_recovered": recovered_table_count,
                    "rows_recovered": recovered_row_count,
                })
                logger.info("Database repaired successfully")
            except Exception as repair_error:
                _publish_corruption_alert("database_repair_failed", str(repair_error))
                logger.error(f"Database repair failed: {repair_error}")
                raise
        else:
            raise


def seed_default_data():
    """Seed database with default data."""
    from backend.config import settings as app_settings

    db = SessionLocal()
    try:
        _set_sqlite_busy_timeout(db, 1000)

        for mode in ["paper", "testnet", "live"]:
            existing = db.query(BotState).filter_by(mode=mode).first()
            if not existing:
                initial_bankroll = app_settings.INITIAL_BANKROLL
                if mode == "testnet":
                    initial_bankroll = 100.0

                bot_state = BotState(
                    mode=mode,
                    bankroll=initial_bankroll,
                    total_trades=0,
                    winning_trades=0,
                    total_pnl=0.0,
                    is_running=False,
                    paper_bankroll=initial_bankroll if mode == "paper" else 100.0,
                    paper_pnl=0.0,
                    paper_trades=0,
                    paper_wins=0,
                    paper_initial_bankroll=initial_bankroll if mode == "paper" else None,
                    testnet_bankroll=100.0,
                    testnet_pnl=0.0,
                    testnet_trades=0,
                    testnet_wins=0,
                    testnet_initial_bankroll=100.0 if mode == "testnet" else None,
                    live_initial_bankroll=initial_bankroll if mode == "live" else None,
                )
                db.add(bot_state)
                logger.info(f"Seeded BotState for mode: {mode}")
            else:
                if mode == "live" and existing.live_initial_bankroll is None:
                    existing.live_initial_bankroll = app_settings.INITIAL_BANKROLL
                    db.info["allow_live_financial_update"] = True
                    logger.info(
                        f"Backfilled live_initial_bankroll = {app_settings.INITIAL_BANKROLL}"
                    )
                if mode == "paper" and existing.paper_initial_bankroll is None:
                    existing.paper_initial_bankroll = app_settings.INITIAL_BANKROLL
                    logger.info(
                        f"Backfilled paper_initial_bankroll = {app_settings.INITIAL_BANKROLL}"
                    )
                if mode == "testnet" and existing.testnet_initial_bankroll is None:
                    existing.testnet_initial_bankroll = 100.0
                    logger.info("Backfilled testnet_initial_bankroll = 100.0")

        from backend.strategies.loader import load_all_strategies
        from backend.strategies.registry import STRATEGY_REGISTRY
        load_all_strategies()

        for strategy_name in STRATEGY_REGISTRY.keys():
            existing = db.query(StrategyConfig).filter_by(strategy_name=strategy_name).first()
            if not existing:
                strategy_config = StrategyConfig(
                    strategy_name=strategy_name,
                    enabled=False,
                    params=None,
                    interval_seconds=60,
                    trading_mode=None,
                )
                db.add(strategy_config)
                logger.info(f"Seeded StrategyConfig for: {strategy_name}")

        db.commit()
        logger.info("Database seeding completed")
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to seed database: {e}")
        raise
    finally:
        db.close()


_DDL_COL_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')
_DDL_TYPE_RE = re.compile(r'^(VARCHAR|TEXT|INTEGER|REAL|BOOLEAN|TIMESTAMP|DATETIME|JSON)(\s+.*)?$', re.IGNORECASE)


def _safe_ddl_identifier(name: str) -> str:
    if not _DDL_COL_RE.match(name):
        raise ValueError(f"Invalid DDL identifier: {name!r}")
    return name


def _safe_ddl_type(type_str: str) -> str:
    if not _DDL_TYPE_RE.match(type_str):
        raise ValueError(f"Invalid DDL type: {type_str!r}")
    return type_str


def ensure_schema():
    """Ensure newer schema fields exist even if migration wasn't run."""
    inspector = inspect(engine)

    try:
        columns = [col["name"] for col in inspector.get_columns("trades")]
    except Exception:
        logger.exception("database ensure_schema: failed to inspect trades columns")
        return

    if "event_slug" not in columns:
        stmt = "ALTER TABLE trades ADD COLUMN event_slug VARCHAR"
        if engine.dialect.name not in ("sqlite", "mysql"):
            stmt = "ALTER TABLE trades ADD COLUMN IF NOT EXISTS event_slug VARCHAR"

        with engine.connect() as conn:
            with conn.begin():
                conn.execute(text(stmt))

    if "market_type" not in columns:
        with engine.connect() as conn:
            with conn.begin():
                conn.execute(
                    text(
                        "ALTER TABLE trades ADD COLUMN market_type VARCHAR DEFAULT 'btc'"
                    )
                )

    if "trading_mode" not in columns:
        with engine.connect() as conn:
            with conn.begin():
                conn.execute(
                    text(
                        "ALTER TABLE trades ADD COLUMN trading_mode VARCHAR DEFAULT 'paper'"
                    )
                )
        try:
            with engine.connect() as conn:
                with conn.begin():
                    conn.execute(
                        text(
                            "UPDATE trades SET trading_mode = 'paper' WHERE trading_mode IS NULL"
                        )
                    )
        except Exception as e:
            logger.warning(f"Schema migration: could not backfill trading_mode: {e}")

    # Add paper tracking columns to bot_state
    try:
        bot_state_columns = [col["name"] for col in inspector.get_columns("bot_state")]
    except Exception:
        logger.exception("database ensure_schema: failed to inspect bot_state columns (paper tracking)")
        bot_state_columns = []

    if bot_state_columns:
        with engine.connect() as conn:
            for col, coltype in [
                ("paper_bankroll", "FLOAT DEFAULT 10000.0"),
                ("paper_pnl", "FLOAT DEFAULT 0.0"),
                ("paper_trades", "INTEGER DEFAULT 0"),
                ("paper_wins", "INTEGER DEFAULT 0"),
                ("testnet_bankroll", "FLOAT DEFAULT 100.0"),
                ("testnet_pnl", "FLOAT DEFAULT 0.0"),
                ("testnet_trades", "INTEGER DEFAULT 0"),
                ("testnet_wins", "INTEGER DEFAULT 0"),
                ("misc_data", "TEXT"),
                ("active_wallet", "TEXT"),
            ]:
                if col not in bot_state_columns:
                    try:
                        with conn.begin():
                            conn.execute(
                                text(
                                    f"ALTER TABLE bot_state ADD COLUMN {col} {coltype}"
                                )
                            )
                    except Exception as e:
                        logger.warning(
                            f"Schema migration: could not add bot_state column {col}: {e}"
                        )

    # Add calibration columns to signals table
    try:
        signal_columns = [col["name"] for col in inspector.get_columns("signals")]
    except Exception:
        logger.exception("database ensure_schema: failed to inspect signals columns")
        signal_columns = []

    if signal_columns:
        with engine.connect() as conn:
            for col, coltype in [
                ("actual_outcome", "TEXT"),
                ("outcome_correct", "BOOLEAN"),
                ("settlement_value", "FLOAT"),
                ("settled_at", _TS_TYPE),
                ("market_type", "VARCHAR DEFAULT 'btc'"),
            ]:
                if col not in signal_columns:
                    try:
                        with conn.begin():
                            conn.execute(
                                text(f"ALTER TABLE signals ADD COLUMN {col} {coltype}")
                            )
                    except Exception as e:
                        logger.warning(
                            f"Schema migration: could not add signals column {col}: {e}"
                        )

    # Add edge discovery tracking columns to signals table
    with engine.connect() as conn:
        for col, coltype in [
            (
                "track_name",
                "VARCHAR DEFAULT 'legacy'",
            ),  # Which edge track generated this signal
            ("execution_mode", "VARCHAR DEFAULT 'paper'"),  # 'paper' or 'live'
        ]:
            if col not in signal_columns:
                try:
                    with conn.begin():
                        conn.execute(
                            text(f"ALTER TABLE signals ADD COLUMN {col} {coltype}")
                        )
                except Exception as e:
                    logger.warning(
                        f"Schema migration: could not add signals edge-track column {col}: {e}"
                    )

    try:
        bot_state_columns = {col["name"] for col in inspector.get_columns("bot_state")}
    except Exception:
        logger.exception("database ensure_schema: failed to inspect bot_state columns (mode)")
        bot_state_columns = set()

    if bot_state_columns and "mode" not in bot_state_columns:
        try:
            with engine.connect() as conn:
                with conn.begin():
                    conn.execute(
                        text("ALTER TABLE bot_state ADD COLUMN mode VARCHAR DEFAULT 'paper'")
                    )
                    logger.info("Added 'mode' column to bot_state")
        except Exception as e:
            logger.warning(f"Schema migration: could not add bot_state.mode: {e}")

        try:
            with engine.connect() as conn:
                with conn.begin():
                    result = conn.execute(
                        text("SELECT COUNT(*) FROM bot_state")
                    )
                    count = result.scalar()

                    if count == 1:
                        result = conn.execute(
                            text("SELECT id, bankroll, total_trades, winning_trades, total_pnl, "
                                 "paper_bankroll, paper_pnl, paper_trades, paper_wins, "
                                 "testnet_bankroll, testnet_pnl, testnet_trades, testnet_wins "
                                 "FROM bot_state LIMIT 1")
                        )
                        row = result.fetchone()

                        if row:
                            (id_val, bankroll, total_trades, winning_trades, total_pnl,
                             paper_bankroll, paper_pnl, paper_trades, paper_wins,
                             testnet_bankroll, testnet_pnl, testnet_trades, testnet_wins) = row

                            conn.execute(
                                text("UPDATE bot_state SET bankroll = :bankroll, "
                                     "total_trades = :total_trades, winning_trades = :winning_trades, "
                                     "total_pnl = :total_pnl WHERE id = :id"),
                                {"bankroll": paper_bankroll or bankroll,
                                 "total_trades": paper_trades or total_trades,
                                 "winning_trades": paper_wins or winning_trades,
                                 "total_pnl": paper_pnl or total_pnl,
                                 "id": id_val}
                            )
                            logger.info("Migrated existing bot_state row to paper mode")
        except Exception as e:
            logger.warning(f"Schema migration: could not migrate bot_state to mode-based schema: {e}")

    # Add per-track bankroll and PNL tracking to bot_state
    try:
        bot_state_columns = [col["name"] for col in inspector.get_columns("bot_state")]
    except Exception:
        logger.exception("database ensure_schema: failed to inspect bot_state columns (per-track)")
        bot_state_columns = []

    if bot_state_columns:
        with engine.connect() as conn:
            for col, coltype in [
                # Per-track bankrolls (for isolation)
                ("track_bankroll_realtime", "FLOAT DEFAULT 100.0"),
                ("track_bankroll_whale", "FLOAT DEFAULT 100.0"),
                ("track_bankroll_commodity", "FLOAT DEFAULT 100.0"),
                # Per-track PNL tracking
                ("track_pnl_realtime", "FLOAT DEFAULT 0.0"),
                ("track_pnl_whale", "FLOAT DEFAULT 0.0"),
                ("track_pnl_commodity", "FLOAT DEFAULT 0.0"),
                # Per-track loss limits
                ("track_loss_limit_realtime", "FLOAT DEFAULT 50.0"),
                ("track_loss_limit_whale", "FLOAT DEFAULT 50.0"),
                ("track_loss_limit_commodity", "FLOAT DEFAULT 50.0"),
            ]:
                if col not in bot_state_columns:
                    try:
                        with conn.begin():
                            conn.execute(
                                text(
                                    f"ALTER TABLE bot_state ADD COLUMN {col} {coltype}"
                                )
                            )
                    except Exception as e:
                        logger.warning(
                            f"Schema migration: could not add bot_state per-track column {col}: {e}"
                        )

    # Ensure copy_trader_entries table exists
    try:
        copy_entry_tables = inspector.get_table_names()
    except Exception:
        logger.exception("database ensure_schema: failed to inspect table names")
        copy_entry_tables = []

    if "copy_trader_entries" not in copy_entry_tables:
        CopyTraderEntry.__table__.create(bind=engine, checkfirst=True)
    else:
        # Migrate: add pnl column if missing
        try:
            copy_cols = {
                c["name"] for c in inspector.get_columns("copy_trader_entries")
            }
            if "pnl" not in copy_cols:
                with engine.connect() as conn:
                    with conn.begin():
                        conn.execute(
                            text(
                                "ALTER TABLE copy_trader_entries ADD COLUMN pnl REAL DEFAULT 0.0"
                            )
                        )
        except Exception as e:
            logger.warning(
                f"Schema migration: could not add copy_trader_entries pnl column: {e}"
            )

    # Ensure settlement_events table exists
    if "settlement_events" not in copy_entry_tables:
        SettlementEvent.__table__.create(bind=engine, checkfirst=True)

    # Ensure audit_log table exists
    if "audit_log" not in copy_entry_tables:
        AuditLog.__table__.create(bind=engine, checkfirst=True)

    # Ensure new tables exist (DecisionLog, MarketWatch, WalletConfig, StrategyConfig, TradeContext)
    # checkfirst=True prevents "already exists" errors when ensure_schema is called more than once
    # on the same database (e.g. during test setup or after a hot-restart).
    Base.metadata.create_all(bind=engine, checkfirst=True)

    # Add whale_score column to wallet_config if missing
    try:
        wallet_columns = {col["name"] for col in inspector.get_columns("wallet_config")}
        if "whale_score" not in wallet_columns:
            with engine.connect() as conn:
                with conn.begin():
                    conn.execute(
                        text("ALTER TABLE wallet_config ADD COLUMN whale_score FLOAT")
                    )
    except Exception as e:
        logger.warning(
            f"Schema migration: could not add wallet_config whale_score column: {e}"
        )

    # Add new columns to trades table if missing
    inspector = inspect(engine)
    existing_cols = {col["name"] for col in inspector.get_columns("trades")}
    with engine.connect() as conn:
        for col_def in [
            "ALTER TABLE trades ADD COLUMN strategy TEXT",
            "ALTER TABLE trades ADD COLUMN signal_source TEXT",
            "ALTER TABLE trades ADD COLUMN confidence REAL",
            "ALTER TABLE trades ADD COLUMN clob_order_id TEXT",
            "ALTER TABLE trades ADD COLUMN clob_idempotency_key TEXT",
            "ALTER TABLE trades ADD COLUMN filled_size REAL",
            "ALTER TABLE trades ADD COLUMN fill_price REAL",
            "ALTER TABLE trades ADD COLUMN fill_ratio REAL",
        ]:
            col_name = col_def.split("ADD COLUMN ")[1].split()[0]
            if col_name not in existing_cols:
                with conn.begin():
                    conn.execute(text(col_def))

    # Create indexes for hot query paths
    try:
        with engine.connect() as conn:
            with conn.begin():
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_trades_settled_mode ON trades(settled, trading_mode)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_trades_ticker_settled ON trades(market_ticker, settled)"
                    )
                )
    except Exception as e:
        logger.warning(f"Could not create trades indexes: {e}")

    try:
        with engine.connect() as conn:
            with conn.begin():
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_pending_approvals_status ON pending_approvals(status)"
                    )
                )
    except Exception as e:
        logger.warning(f"Could not create pending_approvals index: {e}")

    try:
        with engine.connect() as conn:
            with conn.begin():
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_settlement_events_trade_id ON settlement_events(trade_id)"
                    )
                )
    except Exception as e:
        logger.warning(f"Could not create settlement_events index: {e}")

    # Migration: Add unified state sync columns to trades table
    inspector = inspect(engine)
    try:
        existing_cols = {col["name"] for col in inspector.get_columns("trades")}
    except Exception:
        logger.exception("database ensure_schema: failed to inspect trades columns (state sync)")
        existing_cols = set()

    if existing_cols:
        # NEW FIELD 1: source
        if "source" not in existing_cols:
            try:
                with engine.connect() as conn:
                    with conn.begin():
                        conn.execute(
                            text("ALTER TABLE trades ADD COLUMN source VARCHAR DEFAULT 'bot'")
                        )
                        logger.info("Added 'source' column to trades")
            except Exception as e:
                logger.warning(f"Schema migration: could not add trades.source: {e}")

        # NEW FIELD 2: blockchain_verified
        if "blockchain_verified" not in existing_cols:
            try:
                with engine.connect() as conn:
                    with conn.begin():
                        conn.execute(
                            text("ALTER TABLE trades ADD COLUMN blockchain_verified BOOLEAN DEFAULT 0")
                        )
                        logger.info("Added 'blockchain_verified' column to trades")
            except Exception as e:
                logger.warning(f"Schema migration: could not add trades.blockchain_verified: {e}")

        # NEW FIELD 3: settlement_source
        if "settlement_source" not in existing_cols:
            try:
                with engine.connect() as conn:
                    with conn.begin():
                        conn.execute(
                            text("ALTER TABLE trades ADD COLUMN settlement_source VARCHAR DEFAULT NULL")
                        )
                        logger.info("Added 'settlement_source' column to trades")
            except Exception as e:
                logger.warning(f"Schema migration: could not add trades.settlement_source: {e}")

        # NEW FIELD 4: last_sync_at
        if "last_sync_at" not in existing_cols:
            try:
                with engine.connect() as conn:
                    with conn.begin():
                        conn.execute(
                            text(f"ALTER TABLE trades ADD COLUMN last_sync_at {_TS_TYPE} DEFAULT NULL")
                        )
                        logger.info("Added 'last_sync_at' column to trades")
            except Exception as e:
                logger.warning(f"Schema migration: could not add trades.last_sync_at: {e}")

        # NEW FIELD 5: external_import_at
        if "external_import_at" not in existing_cols:
            try:
                with engine.connect() as conn:
                    with conn.begin():
                        conn.execute(
                            text(f"ALTER TABLE trades ADD COLUMN external_import_at {_TS_TYPE} DEFAULT NULL")
                        )
                        logger.info("Added 'external_import_at' column to trades")
            except Exception as e:
                logger.warning(f"Schema migration: could not add trades.external_import_at: {e}")

    # Migration: Add unified state sync columns to bot_state table
    try:
        bot_state_columns = {col["name"] for col in inspector.get_columns("bot_state")}
    except Exception:
        logger.exception("database ensure_schema: failed to inspect bot_state columns (state sync)")
        bot_state_columns = set()

    if bot_state_columns:
        # NEW FIELD 1: last_sync_at
        if "last_sync_at" not in bot_state_columns:
            try:
                with engine.connect() as conn:
                    with conn.begin():
                        conn.execute(
                            text(f"ALTER TABLE bot_state ADD COLUMN last_sync_at {_TS_TYPE} DEFAULT NULL")
                        )
                        logger.info("Added 'last_sync_at' column to bot_state")
            except Exception as e:
                logger.warning(f"Schema migration: could not add bot_state.last_sync_at: {e}")

        # NEW FIELD 2: last_live_sync_error
        if "last_live_sync_error" not in bot_state_columns:
            try:
                with engine.connect() as conn:
                    with conn.begin():
                        conn.execute(
                            text("ALTER TABLE bot_state ADD COLUMN last_live_sync_error VARCHAR DEFAULT NULL")
                        )
                        logger.info("Added 'last_live_sync_error' column to bot_state")
            except Exception as e:
                logger.warning(f"Schema migration: could not add bot_state.last_live_sync_error: {e}")

        # NEW FIELD 3: settlement_last_check_at
        if "settlement_last_check_at" not in bot_state_columns:
            try:
                with engine.connect() as conn:
                    with conn.begin():
                        conn.execute(
                            text(f"ALTER TABLE bot_state ADD COLUMN settlement_last_check_at {_TS_TYPE} DEFAULT NULL")
                        )
                        logger.info("Added 'settlement_last_check_at' column to bot_state")
            except Exception as e:
                logger.warning(f"Schema migration: could not add bot_state.settlement_last_check_at: {e}")

    # Create indexes for new fields
    try:
        with engine.connect() as conn:
            with conn.begin():
                # Index for source filtering (Tasks 6-10, Task 11)
                conn.execute(
                    text("CREATE INDEX IF NOT EXISTS idx_trades_source ON trades(source)")
                )
                # Index for last_sync_at filtering
                conn.execute(
                    text("CREATE INDEX IF NOT EXISTS idx_trades_last_sync_at ON trades(last_sync_at)")
                )
                # Index for blockchain_verified filtering
                conn.execute(
                    text("CREATE INDEX IF NOT EXISTS idx_trades_blockchain_verified ON trades(blockchain_verified)")
                )
                # Index for clob_order_id uniqueness check (Task 5)
                conn.execute(
                    text("CREATE INDEX IF NOT EXISTS idx_trades_clob_order_id ON trades(clob_order_id)")
                )
                logger.info("Created indexes for unified state sync fields")
    except Exception as e:
        logger.warning(f"Could not create unified state sync indexes: {e}")

    # Backfill logic for existing trades (preserve data)
    try:
        with engine.connect() as conn:
            with conn.begin():
                if "sqlite" in settings.DATABASE_URL:
                    _set_sqlite_busy_timeout(conn, 1000)
                # Set source="bot" for all existing trades (assume bot-executed)
                conn.execute(
                    text("UPDATE trades SET source = 'bot' WHERE source IS NULL")
                )
                logger.info("Backfilled 'source' field for existing trades")

                # Set blockchain_verified=false for all existing trades (conservative)
                if "postgresql" in settings.DATABASE_URL:
                    conn.execute(
                        text("UPDATE trades SET blockchain_verified = FALSE WHERE blockchain_verified IS NULL")
                    )
                else:
                    # For SQLite and other databases
                    conn.execute(
                        text("UPDATE trades SET blockchain_verified = 0 WHERE blockchain_verified IS NULL")
                    )
                logger.info("Backfilled 'blockchain_verified' field for existing trades")
    except Exception as e:
        logger.warning(f"Could not backfill unified state sync fields: {e}")

    # Add mode column to strategy_config for per-mode strategy control
    try:
        strategy_config_columns = {col["name"] for col in inspector.get_columns("strategy_config")}
    except Exception:
        logger.exception("database ensure_schema: failed to inspect strategy_config columns")
        strategy_config_columns = set()

    if strategy_config_columns and "mode" not in strategy_config_columns:
        try:
            with engine.connect() as conn:
                with conn.begin():
                    conn.execute(
                        text("ALTER TABLE strategy_config ADD COLUMN mode TEXT")
                    )
                    logger.info("Added 'mode' column to strategy_config")
        except Exception as e:
            logger.warning(f"Schema migration: could not add strategy_config.mode: {e}")

    if strategy_config_columns and "disabled_at" not in strategy_config_columns:
        try:
            with engine.connect() as conn:
                with conn.begin():
                    conn.execute(
                        text(f"ALTER TABLE strategy_config ADD COLUMN disabled_at {_TS_TYPE}")
                    )
                    logger.info("Added 'disabled_at' column to strategy_config")
        except Exception as e:
            logger.warning(f"Schema migration: could not add strategy_config.disabled_at: {e}")

    # Add strategy_proposal columns for auto-promotion (v2 learning loop)
    try:
        proposal_columns = inspect(engine).get_columns("strategy_proposal")
        proposal_col_names = {c["name"] for c in proposal_columns} if proposal_columns else set()
    except Exception:
        logger.exception("database ensure_schema: failed to inspect strategy_proposal columns")
        proposal_col_names = set()
    for col, col_type in [("status", "TEXT DEFAULT 'pending'"), ("auto_promotable", "BOOLEAN DEFAULT 0"), ("proposed_params", "JSON"), ("backtest_passed", "BOOLEAN DEFAULT 0"), ("backtest_sharpe", "REAL"), ("backtest_win_rate", "REAL")]:
        if col not in proposal_col_names:
            try:
                safe_col = _safe_ddl_identifier(col)
                safe_type = _safe_ddl_type(col_type)
                with engine.connect() as conn:
                    with conn.begin():
                        conn.execute(text(f"ALTER TABLE strategy_proposal ADD COLUMN {safe_col} {safe_type}"))
                        logger.info(f"Added '{col}' column to strategy_proposal")
            except Exception as e:
                logger.warning(f"Schema migration: could not add strategy_proposal.{col}: {e}")

    # Add denormalized metric columns + composite indexes to genome_registry
    try:
        gr_cols = {c["name"] for c in inspector.get_columns("genome_registry")}
    except Exception:
        logger.exception("database ensure_schema: failed to inspect genome_registry columns")
        gr_cols = set()

    for col, coltype in [
        ("fitness_score", "REAL"),
        ("fitness_updated_at", _TS_TYPE),
        ("total_pnl", "REAL DEFAULT 0.0"),
        ("win_rate", "REAL DEFAULT 0.0"),
        ("sharpe_ratio", "REAL DEFAULT 0.0"),
        ("max_drawdown_pct", "REAL DEFAULT 0.0"),
        ("trade_count", "INTEGER DEFAULT 0"),
        ("last_evaluated_at", _TS_TYPE),
        ("stage_entered_at", _TS_TYPE),
    ]:
        if col not in gr_cols:
            try:
                safe_col = _safe_ddl_identifier(col)
                safe_type = _safe_ddl_type(coltype)
                with engine.connect() as conn:
                    with conn.begin():
                        conn.execute(text(f"ALTER TABLE genome_registry ADD COLUMN {safe_col} {safe_type}"))
                        logger.info(f"Added '{col}' column to genome_registry")
            except Exception as e:
                logger.warning(f"Schema migration: could not add genome_registry.{col}: {e}")

    # Create composite indexes on genome_registry (idempotent — ignores errors if already exists)
    try:
        with engine.connect() as conn:
            with conn.begin():
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_genome_stage_score ON genome_registry(stage, fitness_score)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_genome_stage_winrate ON genome_registry(stage, win_rate)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_genome_archetype_stage ON genome_registry(archetype, stage)"))
                logger.info("Created composite indexes on genome_registry")
    except Exception as e:
        logger.warning(f"Could not create genome_registry composite indexes: {e}")


def log_audit(action: str, actor: str = "system", details: dict = None):
    db = SessionLocal()
    try:
        entry = AuditLog(action=action, actor=actor, details=details)
        db.add(entry)
        db.commit()
    except Exception:
        logger.exception("database log_audit failed")
        db.rollback()
    finally:
        db.close()


# Knowledge Graph models for Wave 10
class KgNode(Base):
    """Knowledge Graph Node - represents entities in the graph."""

    __tablename__ = "kg_node"

    node_id = Column(String, primary_key=True, index=True)
    node_type = Column(String, nullable=False, index=True)  # 'strategy', 'gene', 'market', 'trade', 'regime', 'event'
    label = Column(String, nullable=False)
    properties_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class KgEdge(Base):
    """Knowledge Graph Edge - represents relationships between nodes."""

    __tablename__ = "kg_edge"

    edge_id = Column(String, primary_key=True, index=True)
    from_node_id = Column(String, ForeignKey("kg_node.node_id"), nullable=False, index=True)
    to_node_id = Column(String, ForeignKey("kg_node.node_id"), nullable=False, index=True)
    relationship = Column(String, nullable=False)  # 'HAS_GENE', 'TRADED_ON', 'MUTATED_FROM', 'KILLED_BY', etc.
    weight = Column(Float, default=1.0)
    properties_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


# Indexes for Knowledge Graph
Index('idx_kg_from', KgEdge.from_node_id, KgEdge.relationship)
Index('idx_kg_to', KgEdge.to_node_id, KgEdge.relationship)
Index('idx_kg_type', KgNode.node_type)


class ClobEvent(Base):
    __tablename__ = "clob_events"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(String, nullable=False)
    maker = Column(String, nullable=False)
    taker = Column(String, nullable=False)
    market_id = Column(String, nullable=False)
    side = Column(String, nullable=False)  # "BUY" or "SELL"
    size = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    fee = Column(Float, nullable=False)
    block_number = Column(Integer, nullable=False)
    tx_hash = Column(String, nullable=False, unique=True)
    timestamp = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        # Only the unique constraint lives here; individual column indexes are
        # declared via index=True on the Column definitions above to avoid
        # duplicate index creation errors when create_all() is called more than
        # once on the same database.
        UniqueConstraint('tx_hash', name='uq_clob_events_tx_hash'),
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
        UniqueConstraint(
            "provider_name", "config_key", name="uq_provider_credentials"
        ),
        Index("idx_provider_credentials_name", "provider_name"),
    )


def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Re-import to ensure table registration without failing on circular import orderings.
try:
    from backend.core.strategy_performance_registry import StrategyPerformanceSnapshot  # noqa: E402, F401
except ImportError as exc:
    logger.debug(
        "Deferred StrategyPerformanceSnapshot registration during database import: {}",
        exc,
    )
