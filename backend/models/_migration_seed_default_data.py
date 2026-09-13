"""Carved verbatim out of ``backend/models/migration.py`` — statements moved, no logic changed."""

from .migration import (
    Any,
)

from . import migration as _facade

def seed_default_data() -> None:
    """Seed database with default data."""
    db = _facade.SessionLocal()
    try:
        _facade._set_sqlite_busy_timeout(db, 1000)

        # Lazy import to avoid circular dependency — BotState is in botstate_db.py
        from backend.models.botstate_db import BotState

        for mode in ["paper", "testnet", "live"]:
            existing = db.query(BotState).filter_by(mode=mode).first()
            if not existing:
                initial_bankroll = _facade.app_settings.INITIAL_BANKROLL
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
                _facade.logger.info(f"Seeded BotState for mode: {mode}")
            else:
                if (
                    mode == "live"
                    and existing.live_initial_bankroll is None
                ):
                    existing.live_initial_bankroll = (
                        _facade.app_settings.INITIAL_BANKROLL
                    )
                    _facade.logger.info(
                        f"Backfilled live_initial_bankroll = {_facade.app_settings.INITIAL_BANKROLL}"
                    )
                if (
                    mode == "paper"
                    and existing.paper_initial_bankroll is None
                ):
                    existing.paper_initial_bankroll = (
                        _facade.app_settings.INITIAL_BANKROLL
                    )
                    _facade.logger.info(
                        f"Backfilled paper_initial_bankroll = {_facade.app_settings.INITIAL_BANKROLL}"
                    )
                if (
                    mode == "testnet"
                    and existing.testnet_initial_bankroll is None
                ):
                    existing.testnet_initial_bankroll = 100.0
                    _facade.logger.info(
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
                _facade.logger.info(
                    f"Seeded StrategyConfig for: {strategy_name}"
                )

        db.commit()
        _facade.logger.info("Database seeding completed")
    except Exception as e:
        db.rollback()
        _facade.logger.error(f"Failed to seed database: {e}")
        raise
    finally:
        db.close()
def _table_exists(conn, table_name: str) -> bool:
    """Check whether *table_name* exists in the current database."""
    inspector = _facade.inspect(conn)
    return table_name in inspector.get_table_names()
def log_audit(
    action: str,
    entity_type: str,
    entity_id: Any,
    details: Any = None,
    user_id: int | None = None,
) -> None:
    """Record an audit‑log entry in the database."""
    db = _facade.SessionLocal()
    try:
        db.execute(
            _facade.text(
                """INSERT INTO audit_log (action, entity_type, entity_id, details, user_id)
                   VALUES (:action, :entity_type, :entity_id, :details, :user_id)"""
            ),
            {
                "action": action,
                "entity_type": entity_type,
                "entity_id": str(entity_id) if entity_id else None,
                "details": _facade.json.dumps(details) if details else None,
                "user_id": user_id,
            },
        )
        db.commit()
    except Exception as exc:
        _facade.logger.warning(
            f"Audit log failed for {action} on {entity_type}/{entity_id}: {exc}"
        )
    finally:
        db.close()
def _add_column_if_missing(
    conn, table: str, column: str, type_sql: str
) -> None:
    """Add *column* to *table* if it does not already exist."""
    if _table_exists(conn, table):
        col_names = [
            c["name"] for c in _facade.inspect(conn).get_columns(table)
        ]
        if column not in col_names:
            try:
                conn.execute(
                    _facade.text(f"ALTER TABLE {table} ADD COLUMN {column} {type_sql}")
                )
                conn.connection.commit()
            except Exception as exc:
                _facade.logger.warning(
                    f"Could not add {table}.{column}: {exc}"
                )
def _create_strategy_orders_table(db) -> None:
    conn = db.connection()
    if not _table_exists(conn, "strategy_orders"):
        try:
            conn.execute(
                _facade.text(
                    """CREATE TABLE IF NOT EXISTS strategy_orders (
                        id INTEGER PRIMARY KEY GENERATED BY DEFAULT AS IDENTITY,
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
            _facade.logger.warning(
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
                    _facade.text(
                        f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({columns})"
                    )
                )
            except Exception as exc:
                _facade.logger.warning(
                    f"Could not create index {index_name}: {exc}"
                )
    conn.connection.commit()
def _create_system_health_table(db) -> None:
    conn = db.connection()
    if not _table_exists(conn, "system_health"):
        try:
            conn.execute(
                _facade.text(
                    """CREATE TABLE IF NOT EXISTS system_health (
                        id INTEGER PRIMARY KEY GENERATED BY DEFAULT AS IDENTITY,
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
            _facade.logger.warning(
                f"Could not create system_health: {exc}"
            )
def _create_market_metrics_table(db) -> None:
    conn = db.connection()
    if not _table_exists(conn, "market_metrics"):
        try:
            conn.execute(
                _facade.text(
                    """CREATE TABLE IF NOT EXISTS market_metrics (
                        id INTEGER PRIMARY KEY GENERATED BY DEFAULT AS IDENTITY,
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
            _facade.logger.warning(
                f"Could not create market_metrics: {exc}"
            )
def _create_strategy_analysis_table(db) -> None:
    conn = db.connection()
    if not _table_exists(conn, "strategy_analysis"):
        try:
            conn.execute(
                _facade.text(
                    """CREATE TABLE IF NOT EXISTS strategy_analysis (
                        id INTEGER PRIMARY KEY GENERATED BY DEFAULT AS IDENTITY,
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
            _facade.logger.warning(
                f"Could not create strategy_analysis: {exc}"
            )
def _create_execution_metrics_table(db) -> None:
    conn = db.connection()
    if not _table_exists(conn, "execution_metrics"):
        try:
            conn.execute(
                _facade.text(
                    """CREATE TABLE IF NOT EXISTS execution_metrics (
                        id INTEGER PRIMARY KEY GENERATED BY DEFAULT AS IDENTITY,
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
            _facade.logger.warning(
                f"Could not create execution_metrics: {exc}"
            )
def _create_error_log_table(db) -> None:
    conn = db.connection()
    if not _table_exists(conn, "error_log"):
        try:
            conn.execute(
                _facade.text(
                    """CREATE TABLE IF NOT EXISTS error_log (
                        id INTEGER PRIMARY KEY GENERATED BY DEFAULT AS IDENTITY,
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
            _facade.logger.warning(
                f"Could not create error_log: {exc}"
            )
def _create_knowledge_graph_tables(db) -> None:
    conn = db.connection()
    for table_ddl in [
        """CREATE TABLE IF NOT EXISTS kg_knowledge_points (
            id INTEGER PRIMARY KEY GENERATED BY DEFAULT AS IDENTITY,
            content TEXT NOT NULL,
            source VARCHAR(50),
            strategy_id INTEGER,
            context TEXT,
            importance FLOAT DEFAULT 0.5,
            embedding BYTEA,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS kg_relationships (
            id INTEGER PRIMARY KEY GENERATED BY DEFAULT AS IDENTITY,
            source_id INTEGER REFERENCES kg_knowledge_points(id),
            target_id INTEGER REFERENCES kg_knowledge_points(id),
            relationship_type VARCHAR(50),
            weight FLOAT DEFAULT 1.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
    ]:
        try:
            conn.execute(_facade.text(table_ddl))
        except Exception as exc:
            _facade.logger.warning(
                f"Could not create KG table: {exc}"
            )
def _create_trade_insights_table(db) -> None:
    conn = db.connection()
    if not _table_exists(conn, "trade_insights"):
        try:
            conn.execute(
                _facade.text(
                    """CREATE TABLE IF NOT EXISTS trade_insights (
                        id INTEGER PRIMARY KEY GENERATED BY DEFAULT AS IDENTITY,
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
            _facade.logger.warning(
                f"Could not create trade_insights: {exc}"
            )
def _create_position_monitor_table(db) -> None:
    conn = db.connection()
    if not _table_exists(conn, "position_monitor"):
        try:
            conn.execute(
                _facade.text(
                    """CREATE TABLE IF NOT EXISTS position_monitor (
                        id INTEGER PRIMARY KEY GENERATED BY DEFAULT AS IDENTITY,
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
            _facade.logger.warning(
                f"Could not create position_monitor: {exc}"
            )
