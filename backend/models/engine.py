"""Database engine, session factory, and shared infrastructure — domain-agnostic.

Split from base_db.py.
"""
import asyncio
from collections.abc import Generator

from loguru import logger
from sqlalchemy import (
    create_engine,
    event,
    text,
)
from sqlalchemy.orm import (
    Session as SQLAlchemySession,
)
from sqlalchemy.orm import (
    declarative_base,
    sessionmaker,
)

from backend.config import settings

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
    """Bound lock waits inside the current PostgreSQL transaction."""
    if session.get_bind().dialect.name != "postgresql":
        return

    session.execute(text(f"SET LOCAL lock_timeout = '{POSTGRES_LOCK_TIMEOUT}'"))
    session.execute(
        text(f"SET LOCAL statement_timeout = '{POSTGRES_STATEMENT_TIMEOUT}'")
    )


def for_update(session, query):
    """Add FOR UPDATE clause on PostgreSQL. No-op on SQLite/MySQL."""
    if session.get_bind().dialect.name == "postgresql":
        _apply_postgres_lock_timeouts(session)
        return query.with_for_update()
    return query


def _set_sqlite_busy_timeout(connection_or_session, timeout_ms: int) -> None:
    """Apply a shorter busy_timeout for best-effort SQLite bootstrap work."""
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


# Side-effect model imports — these register tables with Base.metadata
try:
    import backend.core.risk.risk_profiles  # noqa: F401
    import backend.models.historical_data  # noqa: F401
    import backend.models.kg_models  # noqa: F401
    import backend.models.outcome_tables  # noqa: F401
except ImportError:
    logger.exception("database model imports failed")


def get_db() -> Generator[SQLAlchemySession, None, None]:
    """Get database session (FastAPI dependency)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
