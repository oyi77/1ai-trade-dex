"""Database schema management, seeding, and migration infrastructure.

Split from base_db.py.
"""
import json
import os
import time
from typing import Any

from loguru import logger
from sqlalchemy import inspect, text

from backend.config import settings as app_settings
from backend.models.engine import (
    _TS_TYPE,
    Base,
    SessionLocal,
    _set_sqlite_busy_timeout,
    engine,
)
from backend.models.recovery import (
    _attempt_data_recovery,
    _publish_corruption_alert,
    _restore_recovered_data,
)

# ---------------------------------------------------------------------------
# Initialisation / migration
# ---------------------------------------------------------------------------


def init_db(repair_if_needed: bool = True) -> None:
    """Initialise the database schema: create all tables, run migrations, seed defaults.

    If the database is corrupted and *repair_if_needed* is ``True``, attempt
    data recovery, wipe the file, recreate, and restore recovered rows.
    Safe to call repeatedly.
    """
    try:
        Base.metadata.create_all(bind=engine, checkfirst=True)
        ensure_schema()
        seed_default_data()
    except Exception as e:
        if "database disk image is malformed" in str(e) and repair_if_needed:
            logger.warning(f"Database corrupted, attempting repair: {e}")
            _publish_corruption_alert("database_corruption_detected", str(e))

            db_path = app_settings.DATABASE_URL.replace(
                "sqlite:///", ""
            ).replace("./", "")
            recovered = _attempt_data_recovery(db_path)
            recovered_table_count = len(recovered)
            recovered_row_count = sum(
                len(rows) for rows in recovered.values()
            )
            logger.info(
                f"Recovered data from {recovered_table_count} table(s), "
                f"{recovered_row_count} total rows before wiping"
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
                _publish_corruption_alert(
                    "database_repair_failed", str(repair_error)
                )
                logger.error(f"Database repair failed: {repair_error}")
                raise
        else:
            raise


def seed_default_data() -> None:
    """Seed database with default data."""
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
                    live_initial_bankroll=(
                        initial_bankroll if mode == "live" else None
                    ),
                )
                db.add(bot_state)
                logger.info(f"Seeded BotState for mode: {mode}")
            else:
                if (
                    mode == "live"
                    and existing.live_initial_bankroll is None
                ):
                    existing.live_initial_bankroll = (
                        app_settings.INITIAL_BANKROLL
                    )
                    logger.info(
                        f"Backfilled live_initial_bankroll = {app_settings.INITIAL_BANKROLL}"
                    )
                if (
                    mode == "paper"
                    and existing.paper_initial_bankroll is None
                ):
                    existing.paper_initial_bankroll = (
                        app_settings.INITIAL_BANKROLL
                    )
                    logger.info(
                        f"Backfilled paper_initial_bankroll = {app_settings.INITIAL_BANKROLL}"
                    )
                if (
                    mode == "testnet"
                    and existing.testnet_initial_bankroll is None
                ):
                    existing.testnet_initial_bankroll = 100.0
                    logger.info(
                        "Backfilled testnet_initial_bankroll = 100.0"
                    )

        from backend.models.strategy_db import StrategyConfig
        from backend.strategies.loader import load_all_strategies
        from backend.strategies.registry import STRATEGY_REGISTRY

        load_all_strategies()

        for strategy_name in STRATEGY_REGISTRY.keys():
            existing = (
                db.query(StrategyConfig)
                .filter_by(strategy_name=strategy_name)
                .first()
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
                logger.info(
                    f"Seeded StrategyConfig for: {strategy_name}"
                )

        db.commit()
        logger.info("Database seeding completed")
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to seed database: {e}")
        raise
    finally:
        db.close()


def _table_exists(conn, table_name: str) -> bool:
    """Check whether *table_name* exists in the current database."""
    inspector = inspect(conn)
    return table_name in inspector.get_table_names()


def log_audit(
    action: str,
    entity_type: str,
    entity_id: Any,
    details: Any = None,
    user_id: int | None = None,
) -> None:
    """Record an audit‑log entry in the database."""
    db = SessionLocal()
    try:
        db.execute(
            text(
                """INSERT INTO audit_log (action, entity_type, entity_id, details, user_id)
                   VALUES (:action, :entity_type, :entity_id, :details, :user_id)"""
            ),
            {
                "action": action,
                "entity_type": entity_type,
                "entity_id": str(entity_id) if entity_id else None,
                "details": json.dumps(details) if details else None,
                "user_id": user_id,
            },
        )
        db.commit()
    except Exception as exc:
        logger.warning(
            f"Audit log failed for {action} on {entity_type}/{entity_id}: {exc}"
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Schema migration helpers
# ---------------------------------------------------------------------------


def ensure_schema() -> None:
    """Migrate the database schema to the latest version.

    Creates missing tables, adds missing columns, and runs data fixups.
    May be called on every startup — designed to be idempotent.
    """
    t0 = time.time()

    db = SessionLocal()
    try:
        conn = db.connection()
        _add_column_if_missing(
            conn, "system_settings", "telegram_channel_status", "VARCHAR(255)"
        )
        _add_column_if_missing(
            conn,
            "system_settings",
            "telegram_notify_errors",
            "BOOLEAN",
        )
        _add_column_if_missing(
            conn, "risk_profiles", "max_concurrent_trades", "FLOAT"
        )
        _add_column_if_missing(
            conn, "strategy_performance", "target_asset", "VARCHAR(50)"
        )

        _create_strategy_orders_table(db)
        _create_knowledge_graph_indexes(db)
        _create_system_health_table(db)
        _create_market_metrics_table(db)
        _create_strategy_analysis_table(db)
        _create_execution_metrics_table(db)
        _create_error_log_table(db)
        _create_knowledge_graph_tables(db)
        _create_trade_insights_table(db)
        _create_position_monitor_table(db)
        _create_sentiment_cache_table(db)
        _create_prediction_market_tables(db)
        _create_audit_log_table(db)
        _update_token_limit_supply(db)
        _add_risk_profile_position_monitor(db)
        _create_trade_alerts_table(db)
        _add_strategy_columns(db)
        _create_backup_state_table(db)
        _create_scheduled_tasks_table(db)
        _add_strategy_generation_columns(db)
        _create_auto_withdrawal_table(db)
        _add_withdrawal_columns(db)
        _create_market_index_table(db)
        _add_missing_trade_columns(db)
        _add_event_connection_columns(db)
        _add_health_check_columns(db)
        _create_provider_settings_table(db)
        _create_cex_exchange_orders_table(db)

        logger.info(
            f"ensure_schema completed in {time.time() - t0:.2f}s — "
            f"all migrations applied"
        )
    except Exception as exc:
        logger.error(f"ensure_schema migration failed: {exc}")
        raise
    finally:
        db.close()


def _add_column_if_missing(
    conn, table: str, column: str, type_sql: str
) -> None:
    """Add *column* to *table* if it does not already exist."""
    if _table_exists(conn, table):
        col_names = [
            c["name"] for c in inspect(conn).get_columns(table)
        ]
        if column not in col_names:
            try:
                conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN {column} {type_sql}")
                )
                conn.connection.commit()
            except Exception as exc:
                logger.warning(
                    f"Could not add {table}.{column}: {exc}"
                )


def _create_strategy_orders_table(db) -> None:
    conn = db.connection()
    if not _table_exists(conn, "strategy_orders"):
        try:
            conn.execute(
                text(
                    """CREATE TABLE IF NOT EXISTS strategy_orders (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        strategy_id INTEGER,
                        strategy_name VARCHAR(255),
                        exchange VARCHAR(50),
                        symbol VARCHAR(50),
                        side VARCHAR(10),
                        order_type VARCHAR(50),
                        quantity FLOAT,
                        price FLOAT,
                        status VARCHAR(50),
                        error_message TEXT,
                        order_response TEXT,
                        created_at TIMESTAMP,
                        updated_at TIMESTAMP
                    )"""
                )
            )
            conn.connection.commit()
        except Exception as exc:
            logger.warning(
                f"Could not create strategy_orders: {exc}"
            )


def _create_knowledge_graph_indexes(db) -> None:
    conn = db.connection()
    for table, index_name, columns in [
        ("kg_knowledge_points", "idx_kp_strategy_id", "strategy_id"),
        ("kg_knowledge_points", "idx_kp_created_at", "created_at"),
        ("kg_relationships", "idx_rel_source", "source_id"),
        ("kg_relationships", "idx_rel_target", "target_id"),
        (
            "kg_relationships",
            "idx_rel_type",
            "relationship_type",
        ),
    ]:
        if _table_exists(conn, table):
            try:
                conn.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({columns})"
                    )
                )
            except Exception as exc:
                logger.warning(
                    f"Could not create index {index_name}: {exc}"
                )
    conn.connection.commit()


def _create_system_health_table(db) -> None:
    conn = db.connection()
    if not _table_exists(conn, "system_health"):
        try:
            conn.execute(
                text(
                    """CREATE TABLE IF NOT EXISTS system_health (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        component VARCHAR(100),
                        status VARCHAR(50),
                        metric_name VARCHAR(100),
                        metric_value FLOAT,
                        details TEXT,
                        checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )"""
                )
            )
            conn.connection.commit()
        except Exception as exc:
            logger.warning(
                f"Could not create system_health: {exc}"
            )


def _create_market_metrics_table(db) -> None:
    conn = db.connection()
    if not _table_exists(conn, "market_metrics"):
        try:
            conn.execute(
                text(
                    """CREATE TABLE IF NOT EXISTS market_metrics (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        symbol VARCHAR(20),
                        metric_type VARCHAR(50),
                        value FLOAT,
                        additional_data TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )"""
                )
            )
            conn.connection.commit()
        except Exception as exc:
            logger.warning(
                f"Could not create market_metrics: {exc}"
            )


def _create_strategy_analysis_table(db) -> None:
    conn = db.connection()
    if not _table_exists(conn, "strategy_analysis"):
        try:
            conn.execute(
                text(
                    """CREATE TABLE IF NOT EXISTS strategy_analysis (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        strategy_id INTEGER,
                        analysis_type VARCHAR(100),
                        metrics TEXT,
                        recommendations TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )"""
                )
            )
            conn.connection.commit()
        except Exception as exc:
            logger.warning(
                f"Could not create strategy_analysis: {exc}"
            )


def _create_execution_metrics_table(db) -> None:
    conn = db.connection()
    if not _table_exists(conn, "execution_metrics"):
        try:
            conn.execute(
                text(
                    """CREATE TABLE IF NOT EXISTS execution_metrics (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        strategy_id INTEGER,
                        execution_time_ms FLOAT,
                        success BOOLEAN,
                        error_type VARCHAR(100),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )"""
                )
            )
            conn.connection.commit()
        except Exception as exc:
            logger.warning(
                f"Could not create execution_metrics: {exc}"
            )


def _create_error_log_table(db) -> None:
    conn = db.connection()
    if not _table_exists(conn, "error_log"):
        try:
            conn.execute(
                text(
                    """CREATE TABLE IF NOT EXISTS error_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        source VARCHAR(100),
                        error_type VARCHAR(100),
                        error_message TEXT,
                        stack_trace TEXT,
                        context TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )"""
                )
            )
            conn.connection.commit()
        except Exception as exc:
            logger.warning(
                f"Could not create error_log: {exc}"
            )


def _create_knowledge_graph_tables(db) -> None:
    conn = db.connection()
    for table_ddl in [
        """CREATE TABLE IF NOT EXISTS kg_knowledge_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            source VARCHAR(50),
            strategy_id INTEGER,
            context TEXT,
            importance FLOAT DEFAULT 0.5,
            embedding BLOB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS kg_relationships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER REFERENCES kg_knowledge_points(id),
            target_id INTEGER REFERENCES kg_knowledge_points(id),
            relationship_type VARCHAR(50),
            weight FLOAT DEFAULT 1.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
    ]:
        try:
            conn.execute(text(table_ddl))
        except Exception as exc:
            logger.warning(
                f"Could not create KG table: {exc}"
            )


def _create_trade_insights_table(db) -> None:
    conn = db.connection()
    if not _table_exists(conn, "trade_insights"):
        try:
            conn.execute(
                text(
                    """CREATE TABLE IF NOT EXISTS trade_insights (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        trade_id INTEGER,
                        insight_type VARCHAR(100),
                        insight_text TEXT,
                        confidence FLOAT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )"""
                )
            )
            conn.connection.commit()
        except Exception as exc:
            logger.warning(
                f"Could not create trade_insights: {exc}"
            )


def _create_position_monitor_table(db) -> None:
    conn = db.connection()
    if not _table_exists(conn, "position_monitor"):
        try:
            conn.execute(
                text(
                    """CREATE TABLE IF NOT EXISTS position_monitor (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        exchange VARCHAR(50),
                        symbol VARCHAR(20),
                        position_type VARCHAR(20),
                        size FLOAT,
                        entry_price FLOAT,
                        current_price FLOAT,
                        unrealized_pnl FLOAT,
                        status VARCHAR(20),
                        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )"""
                )
            )
            conn.connection.commit()
        except Exception as exc:
            logger.warning(
                f"Could not create position_monitor: {exc}"
            )


def _create_sentiment_cache_table(db) -> None:
    conn = db.connection()
    if not _table_exists(conn, "sentiment_cache"):
        try:
            conn.execute(
                text(
                    """CREATE TABLE IF NOT EXISTS sentiment_cache (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        source VARCHAR(100),
                        symbol VARCHAR(20),
                        sentiment_score FLOAT,
                        confidence FLOAT,
                        details TEXT,
                        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )"""
                )
            )
            conn.connection.commit()
        except Exception as exc:
            logger.warning(
                f"Could not create sentiment_cache: {exc}"
            )


def _create_prediction_market_tables(db) -> None:
    conn = db.connection()
    for table_ddl in [
        """CREATE TABLE IF NOT EXISTS prediction_markets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform VARCHAR(50),
            market_id VARCHAR(255) UNIQUE,
            question TEXT,
            description TEXT,
            outcome VARCHAR(50),
            probability FLOAT,
            volume FLOAT,
            liquidity FLOAT,
            close_time TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS prediction_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform VARCHAR(50),
            market_id VARCHAR(255),
            trade_type VARCHAR(20),
            amount FLOAT,
            price FLOAT,
            outcome VARCHAR(50),
            pnl FLOAT,
            status VARCHAR(20),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
    ]:
        try:
            conn.execute(text(table_ddl))
        except Exception as exc:
            logger.warning(
                f"Could not create prediction_market table: {exc}"
            )


def _create_audit_log_table(db) -> None:
    conn = db.connection()
    if not _table_exists(conn, "audit_log"):
        try:
            conn.execute(
                text(
                    """CREATE TABLE IF NOT EXISTS audit_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        action VARCHAR(255),
                        entity_type VARCHAR(100),
                        entity_id VARCHAR(100),
                        details TEXT,
                        user_id INTEGER,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )"""
                )
            )
            conn.connection.commit()
        except Exception as exc:
            logger.warning(
                f"Could not create audit_log: {exc}"
            )


def _update_token_limit_supply(db) -> None:
    conn = db.connection()
    if _table_exists(conn, "trading_settings"):
        _add_column_if_missing(
            conn, "trading_settings", "token_limit_supply", "FLOAT"
        )


def _add_risk_profile_position_monitor(db) -> None:
    conn = db.connection()
    if _table_exists(conn, "risk_profiles"):
        _add_column_if_missing(
            conn, "risk_profiles", "max_positions", "INTEGER"
        )


def _create_trade_alerts_table(db) -> None:
    conn = db.connection()
    if not _table_exists(conn, "trade_alerts"):
        try:
            conn.execute(
                text(
                    """CREATE TABLE IF NOT EXISTS trade_alerts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        strategy_id INTEGER,
                        alert_type VARCHAR(100),
                        message TEXT,
                        severity VARCHAR(20),
                        is_read BOOLEAN DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )"""
                )
            )
            conn.connection.commit()
        except Exception as exc:
            logger.warning(
                f"Could not create trade_alerts: {exc}"
            )


def _add_strategy_columns(db) -> None:
    conn = db.connection()
    if _table_exists(conn, "strategies"):
        _add_column_if_missing(conn, "strategies", "risk_score", "FLOAT")
        _add_column_if_missing(conn, "strategies", "is_active", "BOOLEAN")
        _add_column_if_missing(conn, "strategies", "config", "TEXT")


def _create_backup_state_table(db) -> None:
    conn = db.connection()
    if not _table_exists(conn, "backup_state"):
        try:
            conn.execute(
                text(
                    """CREATE TABLE IF NOT EXISTS backup_state (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        backup_type VARCHAR(50),
                        state TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )"""
                )
            )
            conn.connection.commit()
        except Exception as exc:
            logger.warning(
                f"Could not create backup_state: {exc}"
            )


def _create_scheduled_tasks_table(db) -> None:
    conn = db.connection()
    if not _table_exists(conn, "scheduled_tasks"):
        try:
            conn.execute(
                text(
                    """CREATE TABLE IF NOT EXISTS scheduled_tasks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        task_name VARCHAR(255),
                        task_type VARCHAR(100),
                        interval_seconds INTEGER,
                        last_run TIMESTAMP,
                        next_run TIMESTAMP,
                        is_active BOOLEAN DEFAULT 1,
                        config TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )"""
                )
            )
            conn.connection.commit()
        except Exception as exc:
            logger.warning(
                f"Could not create scheduled_tasks: {exc}"
            )


def _add_strategy_generation_columns(db) -> None:
    conn = db.connection()
    if _table_exists(conn, "strategies"):
        _add_column_if_missing(
            conn, "strategies", "generation", "INTEGER"
        )
        _add_column_if_missing(
            conn, "strategies", "parent_strategy_id", "INTEGER"
        )
        _add_column_if_missing(
            conn, "strategies", "evolution_score", "FLOAT"
        )


def _create_auto_withdrawal_table(db) -> None:
    conn = db.connection()
    if not _table_exists(conn, "auto_withdrawal"):
        try:
            conn.execute(
                text(
                    """CREATE TABLE IF NOT EXISTS auto_withdrawal (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        exchange VARCHAR(50),
                        asset VARCHAR(20),
                        amount FLOAT,
                        withdrawal_address TEXT,
                        status VARCHAR(20),
                        tx_hash VARCHAR(255),
                        error_message TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )"""
                )
            )
            conn.connection.commit()
        except Exception as exc:
            logger.warning(
                f"Could not create auto_withdrawal: {exc}"
            )


def _add_withdrawal_columns(db) -> None:
    conn = db.connection()
    if _table_exists(conn, "withdrawals"):
        _add_column_if_missing(
            conn, "withdrawals", "network_fee", "FLOAT"
        )
        _add_column_if_missing(
            conn, "withdrawals", "confirmations", "INTEGER"
        )
        _add_column_if_missing(
            conn, "withdrawals", "completed_at", _TS_TYPE
        )


def _create_market_index_table(db) -> None:
    conn = db.connection()
    if not _table_exists(conn, "market_index"):
        try:
            conn.execute(
                text(
                    """CREATE TABLE IF NOT EXISTS market_index (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        exchange VARCHAR(50),
                        symbol VARCHAR(20),
                        price FLOAT,
                        volume FLOAT,
                        change_24h FLOAT,
                        high_24h FLOAT,
                        low_24h FLOAT,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )"""
                )
            )
            conn.connection.commit()
        except Exception as exc:
            logger.warning(
                f"Could not create market_index: {exc}"
            )


def _add_missing_trade_columns(db) -> None:
    conn = db.connection()
    if _table_exists(conn, "trades"):
        _add_column_if_missing(
            conn, "trades", "is_simulated", "BOOLEAN"
        )
        _add_column_if_missing(
            conn, "trades", "take_profit_price", "FLOAT"
        )
        _add_column_if_missing(
            conn, "trades", "stop_loss_price", "FLOAT"
        )
        _add_column_if_missing(
            conn, "trades", "partial_fill", "BOOLEAN"
        )
        _add_column_if_missing(
            conn, "trades", "fill_ratio", "FLOAT"
        )
        _add_column_if_missing(
            conn, "trades", "risk_reward_ratio", "FLOAT"
        )


def _add_event_connection_columns(db) -> None:
    conn = db.connection()
    if _table_exists(conn, "event_connections"):
        _add_column_if_missing(
            conn, "event_connections", "max_retries", "INTEGER"
        )
        _add_column_if_missing(
            conn, "event_connections", "retry_delay", "FLOAT"
        )


def _add_health_check_columns(db) -> None:
    conn = db.connection()
    if _table_exists(conn, "health_checks"):
        _add_column_if_missing(
            conn, "health_checks", "subsystem", "VARCHAR(100)"
        )
        _add_column_if_missing(
            conn, "health_checks", "duration_ms", "FLOAT"
        )


def _create_provider_settings_table(db) -> None:
    conn = db.connection()
    if not _table_exists(conn, "provider_settings"):
        try:
            conn.execute(
                text(
                    """CREATE TABLE IF NOT EXISTS provider_settings (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        provider_name VARCHAR(100),
                        setting_key VARCHAR(100),
                        setting_value TEXT,
                        is_encrypted BOOLEAN DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(provider_name, setting_key)
                    )"""
                )
            )
            conn.connection.commit()
        except Exception as exc:
            logger.warning(
                f"Could not create provider_settings: {exc}"
            )


def _create_cex_exchange_orders_table(db) -> None:
    conn = db.connection()
    if not _table_exists(conn, "cex_exchange_orders"):
        try:
            conn.execute(
                text(
                    """CREATE TABLE IF NOT EXISTS cex_exchange_orders (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        exchange VARCHAR(50),
                        order_id VARCHAR(255),
                        symbol VARCHAR(20),
                        side VARCHAR(10),
                        order_type VARCHAR(50),
                        quantity FLOAT,
                        price FLOAT,
                        status VARCHAR(50),
                        filled_quantity FLOAT,
                        remaining_quantity FLOAT,
                        cost FLOAT,
                        fees TEXT,
                        raw_response TEXT,
                        strategy_id INTEGER,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )"""
                )
            )
            conn.connection.commit()
        except Exception as exc:
            logger.warning(
                f"Could not create cex_exchange_orders: {exc}"
            )
