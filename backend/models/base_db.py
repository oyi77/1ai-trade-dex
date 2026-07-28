"""Database connection, session factory, and shared infrastructure — domain-agnostic.

Split from database.py.  This is the base layer imported by every domain model file.
"""
import os
import re
import json
import asyncio
from datetime import datetime, timezone
from typing import Callable, Optional

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
    event,
)
from sqlalchemy.orm import (
    Session as SQLAlchemySession,
    declarative_base,
    relationship,
    sessionmaker,
)
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy import inspect
from sqlalchemy.ext.hybrid import hybrid_property

from backend.config import settings


# ---------------------------------------------------------------------------
# Callback registration — breaks circular import between models → core
# ---------------------------------------------------------------------------

_corruption_alert_handler = None


def register_corruption_alert_handler(handler) -> None:
    """Register a handler for corruption alerts (typically from core.event_bus).

    This replaces a lazy import of ``core.event_bus.publish_event`` that created
    a hidden circular dependency. Call once at startup from lifespan bootstrap.
    """
    global _corruption_alert_handler
    _corruption_alert_handler = handler


# ---------------------------------------------------------------------------


_is_postgres = settings.is_postgres

_engine_kwargs = {
    "pool_pre_ping": True,
    "pool_timeout": settings.POSTGRES_POOL_TIMEOUT,
    "pool_recycle": settings.POSTGRES_POOL_RECYCLE,
}

if _is_postgres:
    _engine_kwargs.update(
        {
            "pool_size": settings.POSTGRES_POOL_SIZE,
            "max_overflow": settings.POSTGRES_MAX_OVERFLOW,
            "connect_args": {
                "options": "-c idle_in_transaction_session_timeout=30000",
            },
        }
    )
else:
    # SQLite needs generous pool for concurrent strategy cycles + API + workers
    _engine_kwargs.update(
        {
            "pool_size": 20,
            "max_overflow": 40,
            "pool_timeout": 120,
            "connect_args": {"check_same_thread": False},
        }
    )

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

POSTGRES_LOCK_TIMEOUT = "10s"
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

    session.execute(text(f"SET LOCAL lock_timeout = '{POSTGRES_LOCK_TIMEOUT}'"))
    session.execute(
        text(f"SET LOCAL statement_timeout = '{POSTGRES_STATEMENT_TIMEOUT}'")
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
    import backend.models.kg_models
    import backend.models.outcome_tables
    import backend.models.historical_data
    import backend.core.risk.risk_profiles
except ImportError:
    logger.exception("database model imports failed")


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
            asyncio.to_thread(db_operation), timeout=timeout
        )
        return result
    except asyncio.TimeoutError:
        logger.error(f"Database query timeout after {timeout}s")
        from backend.monitoring.metrics import increment_timeouts

        increment_timeouts(timeout_type="database")
        raise


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
        "trades",
        "signals",
        "bot_state",
        "strategy_config",
        "decision_log",
        "trade_attempts",
        "market_watch",
        "wallet_config",
        "settlement_events",
        "equity_snapshots",
        "calibration_records",
        "activity_log",
        "ai_logs",
        "scan_logs",
    )

    try:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        cursor = conn.cursor()

        for table_name in RECOVERABLE_TABLES:
            try:
                cursor.execute(f'SELECT * FROM "{table_name}"')
                columns = (
                    [desc[0] for desc in cursor.description]
                    if cursor.description
                    else []
                )
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

    model_map = {}
    try:
        from backend.models.trade_db import Trade, TradeAttempt
        from backend.models.botstate_db import BotState
        from backend.models.strategy_db import StrategyConfig
        from backend.models.signal_db import Signal, DecisionLog
        from backend.models.wallet_db import MarketWatch, WalletConfig
        from backend.models.settlement_db import SettlementEvent
        from backend.models.misc_db import EquitySnapshot, CalibrationRecord
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
        }
    except ImportError:
        logger.exception("Failed to load model classes for data recovery")
        return

    total_restored = 0
    total_skipped = 0

    for table_name, rows in recovered.items():
        model_class = model_map.get(table_name)
        if not model_class:
            logger.warning(
                f"No model mapping for {table_name} — {len(rows)} rows unrecoverable"
            )
            continue

        db = SessionLocal()
        try:
            restored_in_table = 0
            for row_data in rows:
                try:
                    row_id = row_data.get("id")
                    if row_id is not None:
                        existing = db.query(model_class).filter_by(id=row_id).first()
                        if existing:
                            total_skipped += 1
                            continue

                    clean_data = {
                        k: v
                        for k, v in row_data.items()
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
        logger.info(
            f"Recovery complete: {total_restored} rows restored, {total_skipped} skipped (already exist)"
        )
    elif total_skipped > 0:
        logger.info(
            f"Recovery: all {total_skipped} rows already present, nothing to restore"
        )


def _publish_corruption_alert(event: str, detail: str, data: dict | None = None):
    """Publish a corruption alert via the registered handler or fall back to logging."""
    handler = _corruption_alert_handler
    if handler is not None:
        try:
            handler(
                event,
                {
                    "source": "database",
                    "detail": detail,
                    **(data or {}),
                },
            )
        except Exception:
            logger.exception("database corruption alert handler raised an error")
    else:
        logger.error(f"CORRUPTION_ALERT [{event}]: {detail}")


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
            logger.info(
                f"Recovered data from {recovered_table_count} table(s), {recovered_row_count} total rows before wiping"
            )

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

                _publish_corruption_alert(
                    "database_repair_succeeded",
                    "Database repaired after corruption",
                    {
                        "tables_recovered": recovered_table_count,
                        "rows_recovered": recovered_row_count,
                    },
                )
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

        # Lazy import to avoid circular dependency — BotState is in botstate_db.py
        from backend.models.botstate_db import BotState

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
                    paper_initial_bankroll=(
                        initial_bankroll if mode == "paper" else None
                    ),
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
        from backend.models.strategy_db import StrategyConfig

        load_all_strategies()

        for strategy_name in STRATEGY_REGISTRY.keys():
            existing = (
                db.query(StrategyConfig).filter_by(strategy_name=strategy_name).first()
            )
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


_DDL_COL_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_DDL_TYPE_RE = re.compile(
    r"^(VARCHAR|TEXT|INTEGER|REAL|BOOLEAN|TIMESTAMP|DATETIME|JSON)(\s+.*)?$",
    re.IGNORECASE,
)


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
    # NOTE: ensure_schema() bypasses alembic migrations. This creates drift risk.
    # Lazy imports to avoid circular dependency with domain model files
    from backend.models.wallet_db import CopyTraderEntry
    from backend.models.settlement_db import SettlementEvent
    from backend.models.audit_db import AuditLog

    # For production, prefer alembic-only schema management.
    # See: IMPLEMENTATION_GAPS.md #14
    inspector = inspect(engine)

    try:
        columns = [col["name"] for col in inspector.get_columns("trades")]
    except ImportError:
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

    if "maker_size" not in columns:
        try:
            with engine.connect() as conn:
                with conn.begin():
                    conn.execute(text("ALTER TABLE trades ADD COLUMN maker_size FLOAT"))
        except Exception as e:
            logger.warning(f"Schema migration: could not add maker_size column: {e}")

    if "taker_size" not in columns:
        try:
            with engine.connect() as conn:
                with conn.begin():
                    conn.execute(text("ALTER TABLE trades ADD COLUMN taker_size FLOAT"))
        except Exception as e:
            logger.warning(f"Schema migration: could not add taker_size column: {e}")

    # Add paper tracking columns to bot_state
    try:
        bot_state_columns = [col["name"] for col in inspector.get_columns("bot_state")]
    except ImportError:
        logger.exception(
            "database ensure_schema: failed to inspect bot_state columns (paper tracking)"
        )
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
    except ImportError:
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
    except ImportError:
        logger.exception(
            "database ensure_schema: failed to inspect bot_state columns (mode)"
        )
        bot_state_columns = set()

    if bot_state_columns and "mode" not in bot_state_columns:
        try:
            with engine.connect() as conn:
                with conn.begin():
                    conn.execute(
                        text(
                            "ALTER TABLE bot_state ADD COLUMN mode VARCHAR DEFAULT 'paper'"
                        )
                    )
                    logger.info("Added 'mode' column to bot_state")
        except Exception as e:
            logger.warning(f"Schema migration: could not add bot_state.mode: {e}")

        try:
            with engine.connect() as conn:
                with conn.begin():
                    result = conn.execute(text("SELECT COUNT(*) FROM bot_state"))
                    count = result.scalar()

                    if count == 1:
                        result = conn.execute(
                            text(
                                "SELECT id, bankroll, total_trades, winning_trades, total_pnl, "
                                "paper_bankroll, paper_pnl, paper_trades, paper_wins, "
                                "testnet_bankroll, testnet_pnl, testnet_trades, testnet_wins "
                                "FROM bot_state LIMIT 1"
                            )
                        )
                        row = result.fetchone()

                        if row:
                            (
                                id_val,
                                bankroll,
                                total_trades,
                                winning_trades,
                                total_pnl,
                                paper_bankroll,
                                paper_pnl,
                                paper_trades,
                                paper_wins,
                                testnet_bankroll,
                                testnet_pnl,
                                testnet_trades,
                                testnet_wins,
                            ) = row

                            conn.execute(
                                text(
                                    "UPDATE bot_state SET bankroll = :bankroll, "
                                    "total_trades = :total_trades, winning_trades = :winning_trades, "
                                    "total_pnl = :total_pnl WHERE id = :id"
                                ),
                                {
                                    "bankroll": paper_bankroll or bankroll,
                                    "total_trades": paper_trades or total_trades,
                                    "winning_trades": paper_wins or winning_trades,
                                    "total_pnl": paper_pnl or total_pnl,
                                    "id": id_val,
                                },
                            )
                            logger.info("Migrated existing bot_state row to paper mode")
        except Exception as e:
            logger.warning(
                f"Schema migration: could not migrate bot_state to mode-based schema: {e}"
            )

    # Add per-track bankroll and PNL tracking to bot_state
    try:
        bot_state_columns = [col["name"] for col in inspector.get_columns("bot_state")]
    except ImportError:
        logger.exception(
            "database ensure_schema: failed to inspect bot_state columns (per-track)"
        )
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
    except ImportError:
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
    except ImportError:
        logger.exception(
            "database ensure_schema: failed to inspect trades columns (state sync)"
        )
        existing_cols = set()

    if existing_cols:
        if "source" not in existing_cols:
            try:
                with engine.connect() as conn:
                    with conn.begin():
                        conn.execute(
                            text(
                                "ALTER TABLE trades ADD COLUMN source VARCHAR DEFAULT 'bot'"
                            )
                        )
                        logger.info("Added 'source' column to trades")
            except Exception as e:
                logger.warning(f"Schema migration: could not add trades.source: {e}")

        if "blockchain_verified" not in existing_cols:
            try:
                with engine.connect() as conn:
                    with conn.begin():
                        conn.execute(
                            text(
                                "ALTER TABLE trades ADD COLUMN blockchain_verified BOOLEAN DEFAULT 0"
                            )
                        )
                        logger.info("Added 'blockchain_verified' column to trades")
            except Exception as e:
                logger.warning(
                    f"Schema migration: could not add trades.blockchain_verified: {e}"
                )

        if "settlement_source" not in existing_cols:
            try:
                with engine.connect() as conn:
                    with conn.begin():
                        conn.execute(
                            text(
                                "ALTER TABLE trades ADD COLUMN settlement_source VARCHAR DEFAULT NULL"
                            )
                        )
                        logger.info("Added 'settlement_source' column to trades")
            except Exception as e:
                logger.warning(
                    f"Schema migration: could not add trades.settlement_source: {e}"
                )

        if "last_sync_at" not in existing_cols:
            try:
                with engine.connect() as conn:
                    with conn.begin():
                        conn.execute(
                            text(
                                f"ALTER TABLE trades ADD COLUMN last_sync_at {_TS_TYPE} DEFAULT NULL"
                            )
                        )
                        logger.info("Added 'last_sync_at' column to trades")
            except Exception as e:
                logger.warning(
                    f"Schema migration: could not add trades.last_sync_at: {e}"
                )

        if "external_import_at" not in existing_cols:
            try:
                with engine.connect() as conn:
                    with conn.begin():
                        conn.execute(
                            text(
                                f"ALTER TABLE trades ADD COLUMN external_import_at {_TS_TYPE} DEFAULT NULL"
                            )
                        )
                        logger.info("Added 'external_import_at' column to trades")
            except Exception as e:
                logger.warning(
                    f"Schema migration: could not add trades.external_import_at: {e}"
                )

    # Migration: Add unified state sync columns to bot_state table
    try:
        bot_state_columns = {col["name"] for col in inspector.get_columns("bot_state")}
    except ImportError:
        logger.exception(
            "database ensure_schema: failed to inspect bot_state columns (state sync)"
        )
        bot_state_columns = set()

    if bot_state_columns:
        if "last_sync_at" not in bot_state_columns:
            try:
                with engine.connect() as conn:
                    with conn.begin():
                        conn.execute(
                            text(
                                f"ALTER TABLE bot_state ADD COLUMN last_sync_at {_TS_TYPE} DEFAULT NULL"
                            )
                        )
                        logger.info("Added 'last_sync_at' column to bot_state")
            except Exception as e:
                logger.warning(
                    f"Schema migration: could not add bot_state.last_sync_at: {e}"
                )

        if "last_live_sync_error" not in bot_state_columns:
            try:
                with engine.connect() as conn:
                    with conn.begin():
                        conn.execute(
                            text(
                                "ALTER TABLE bot_state ADD COLUMN last_live_sync_error VARCHAR DEFAULT NULL"
                            )
                        )
                        logger.info("Added 'last_live_sync_error' column to bot_state")
            except Exception as e:
                logger.warning(
                    f"Schema migration: could not add bot_state.last_live_sync_error: {e}"
                )

        if "settlement_last_check_at" not in bot_state_columns:
            try:
                with engine.connect() as conn:
                    with conn.begin():
                        conn.execute(
                            text(
                                f"ALTER TABLE bot_state ADD COLUMN settlement_last_check_at {_TS_TYPE} DEFAULT NULL"
                            )
                        )
                        logger.info(
                            "Added 'settlement_last_check_at' column to bot_state"
                        )
            except Exception as e:
                logger.warning(
                    f"Schema migration: could not add bot_state.settlement_last_check_at: {e}"
                )

    # Create indexes for new fields
    try:
        with engine.connect() as conn:
            with conn.begin():
                # Index for source filtering (Tasks 6-10, Task 11)
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_trades_source ON trades(source)"
                    )
                )
                # Index for last_sync_at filtering
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_trades_last_sync_at ON trades(last_sync_at)"
                    )
                )
                # Index for blockchain_verified filtering
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_trades_blockchain_verified ON trades(blockchain_verified)"
                    )
                )
                # Index for clob_order_id uniqueness check (Task 5)
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_trades_clob_order_id ON trades(clob_order_id)"
                    )
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
                        text(
                            "UPDATE trades SET blockchain_verified = FALSE WHERE blockchain_verified IS NULL"
                        )
                    )
                else:
                    # For SQLite and other databases
                    conn.execute(
                        text(
                            "UPDATE trades SET blockchain_verified = 0 WHERE blockchain_verified IS NULL"
                        )
                    )
                logger.info(
                    "Backfilled 'blockchain_verified' field for existing trades"
                )
    except Exception as e:
        logger.warning(f"Could not backfill unified state sync fields: {e}")

    # Add mode column to strategy_config for per-mode strategy control
    try:
        strategy_config_columns = {
            col["name"] for col in inspector.get_columns("strategy_config")
        }
    except ImportError:
        logger.exception(
            "database ensure_schema: failed to inspect strategy_config columns"
        )
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
                        text(
                            f"ALTER TABLE strategy_config ADD COLUMN disabled_at {_TS_TYPE}"
                        )
                    )
                    logger.info("Added 'disabled_at' column to strategy_config")
        except Exception as e:
            logger.warning(
                f"Schema migration: could not add strategy_config.disabled_at: {e}"
            )

    # Add strategy_proposal columns for auto-promotion (v2 learning loop)
    try:
        proposal_columns = inspect(engine).get_columns("strategy_proposal")
        proposal_col_names = (
            {c["name"] for c in proposal_columns} if proposal_columns else set()
        )
    except ImportError:
        logger.exception(
            "database ensure_schema: failed to inspect strategy_proposal columns"
        )
        proposal_col_names = set()
    for col, col_type in [
        ("status", "TEXT DEFAULT 'pending'"),
        ("auto_promotable", "BOOLEAN DEFAULT 0"),
        ("proposed_params", "JSON"),
        ("backtest_passed", "BOOLEAN DEFAULT 0"),
        ("backtest_sharpe", "REAL"),
        ("backtest_win_rate", "REAL"),
    ]:
        if col not in proposal_col_names:
            try:
                safe_col = _safe_ddl_identifier(col)
                safe_type = _safe_ddl_type(col_type)
                with engine.connect() as conn:
                    with conn.begin():
                        conn.execute(
                            text(
                                f"ALTER TABLE strategy_proposal ADD COLUMN {safe_col} {safe_type}"
                            )
                        )
                        logger.info(f"Added '{col}' column to strategy_proposal")
            except Exception as e:
                logger.warning(
                    f"Schema migration: could not add strategy_proposal.{col}: {e}"
                )

    # Add denormalized metric columns + composite indexes to genome_registry
    try:
        gr_cols = {c["name"] for c in inspector.get_columns("genome_registry")}
    except ImportError:
        logger.exception(
            "database ensure_schema: failed to inspect genome_registry columns"
        )
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
                        conn.execute(
                            text(
                                f"ALTER TABLE genome_registry ADD COLUMN {safe_col} {safe_type}"
                            )
                        )
                        logger.info(f"Added '{col}' column to genome_registry")
            except Exception as e:
                logger.warning(
                    f"Schema migration: could not add genome_registry.{col}: {e}"
                )

    # Create composite indexes on genome_registry (idempotent — ignores errors if already exists)
    try:
        with engine.connect() as conn:
            with conn.begin():
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_genome_stage_score ON genome_registry(stage, fitness_score)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_genome_stage_winrate ON genome_registry(stage, win_rate)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_genome_archetype_stage ON genome_registry(archetype, stage)"
                    )
                )
                logger.info("Created composite indexes on genome_registry")
    except Exception as e:
        logger.warning(f"Could not create genome_registry composite indexes: {e}")

    # Add max_concentration_pct column to risk_profiles if missing
    try:
        tables = inspector.get_table_names()
        if "risk_profiles" in tables:
            rp_columns = {col["name"] for col in inspector.get_columns("risk_profiles")}
            if "max_concentration_pct" not in rp_columns:
                with engine.connect() as conn:
                    with conn.begin():
                        conn.execute(
                            text(
                                "ALTER TABLE risk_profiles ADD COLUMN max_concentration_pct FLOAT DEFAULT 0.3"
                            )
                        )
                logger.info("Added 'max_concentration_pct' column to risk_profiles")

            if "max_correlated_exposure_pct" not in rp_columns:
                with engine.connect() as conn:
                    with conn.begin():
                        conn.execute(
                            text(
                                "ALTER TABLE risk_profiles ADD COLUMN max_correlated_exposure_pct FLOAT DEFAULT 0.8"
                            )
                        )
                logger.info(
                    "Added 'max_correlated_exposure_pct' column to risk_profiles"
                )
    except Exception as e:
        logger.warning(f"Schema migration: could not add risk_profiles columns: {e}")


def log_audit(action: str, actor: str = "system", details: dict = None):
    db = SessionLocal()
    try:
        entry = AuditLog(action=action, actor=actor, details=details)
        db.add(entry)
        db.commit()
    except ImportError:
        logger.exception("database log_audit failed")
        db.rollback()
    finally:
        db.close()


def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


