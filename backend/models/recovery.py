"""Database corruption recovery and query-timeout helpers.

Split from base_db.py.  Contains the correct ``_attempt_data_recovery``
definition that was missing from ``base_db.py`` (a pre‑existing bug
where the function was called at line 429 but had no ``def`` header).
"""
import asyncio
import os
import sqlite3
from collections.abc import Callable

from loguru import logger

from backend.config import settings
from backend.models.engine import SessionLocal

# ---------------------------------------------------------------------------
# Callback registration — breaks circular import between models &rarr; core
# ---------------------------------------------------------------------------

_corruption_alert_handler: Callable | None = None


def register_corruption_alert_handler(handler: Callable) -> None:
    """Register a handler for corruption alerts (typically from core.event_bus).

    This replaces a lazy import of ``core.event_bus.publish_event`` that created
    a hidden circular dependency. Call once at startup from lifespan bootstrap.
    """
    global _corruption_alert_handler
    _corruption_alert_handler = handler


def _publish_corruption_alert(
    event: str, detail: str, data: dict | None = None
) -> None:
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


# ---------------------------------------------------------------------------
# Query timeout helper
# ---------------------------------------------------------------------------


async def execute_with_timeout(db_operation, timeout: float | None = None):
    """Execute a database operation with timeout.

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
    except TimeoutError:
        logger.error(f"Database query timeout after {timeout}s")
        from backend.monitoring.metrics import increment_timeouts

        increment_timeouts(timeout_type="database")
        raise


# ---------------------------------------------------------------------------
# Data recovery (SQLite only)
# ---------------------------------------------------------------------------

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


def _attempt_data_recovery(
    db_path: str,
) -> dict[str, list[dict]]:
    """Try to recover data from a corrupted SQLite database before wiping it.

    Uses sqlite3 directly (not SQLAlchemy) to maximise recovery chances
    on malformed databases. Returns ``{table_name: [row_dicts]}`` for any
    tables that could be read successfully. Returns empty dict for
    non-SQLite databases or missing files.
    """
    recovered: dict[str, list[dict]] = {}

    if not settings.DATABASE_URL.startswith("sqlite"):
        logger.info("Data recovery only supported for SQLite databases")
        return recovered

    if not os.path.exists(db_path):
        return recovered

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
                logger.warning(
                    f"Could not recover table {table_name}: {table_err}"
                )

        conn.close()
    except Exception as e:
        logger.warning(f"Data recovery attempt failed: {e}")

    return recovered


def _restore_recovered_data(recovered: dict[str, list[dict]]) -> None:
    """Re-insert recovered data into the fresh database.

    Uses per-table sessions with individual commits to isolate failures.
    Skips rows with IDs that already exist (idempotent). Only restores
    columns that exist on the target model to handle schema drift.
    """
    if not recovered:
        return

    model_map = {}
    try:
        from backend.models.botstate_db import BotState
        from backend.models.misc_db import CalibrationRecord, EquitySnapshot
        from backend.models.settlement_db import SettlementEvent
        from backend.models.signal_db import DecisionLog, Signal
        from backend.models.strategy_db import StrategyConfig
        from backend.models.trade_db import Trade, TradeAttempt
        from backend.models.wallet_db import MarketWatch, WalletConfig

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
                        existing = (
                            db.query(model_class).filter_by(id=row_id).first()
                        )
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
                    logger.warning(
                        f"Could not restore row in {table_name}: {row_err}"
                    )

            db.commit()
            if restored_in_table > 0:
                logger.info(
                    f"Restored {restored_in_table} rows to {table_name}"
                )
                total_restored += restored_in_table
        except Exception as e:
            db.rollback()
            logger.warning(
                f"Failed to commit {table_name} recovery: {e}"
            )
        finally:
            db.close()

    if total_restored > 0:
        logger.info(
            f"Recovery complete: {total_restored} rows restored, "
            f"{total_skipped} skipped (already exist)"
        )
    elif total_skipped > 0:
        logger.info(
            f"Recovery: all {total_skipped} rows already present, nothing to restore"
        )
