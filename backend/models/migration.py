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

from ._migration_seed_default_data import (
    _add_column_if_missing,
    _create_error_log_table,
    _create_execution_metrics_table,
    _create_knowledge_graph_indexes,
    _create_knowledge_graph_tables,
    _create_market_metrics_table,
    _create_position_monitor_table,
    _create_strategy_analysis_table,
    _create_strategy_orders_table,
    _create_system_health_table,
    _create_trade_insights_table,
    _table_exists,
    log_audit,
    seed_default_data,
)

from ._migration_create_sentiment_cache_table import (
    _add_event_connection_columns,
    _add_health_check_columns,
    _add_missing_trade_columns,
    _add_risk_profile_position_monitor,
    _add_strategy_columns,
    _add_strategy_generation_columns,
    _add_withdrawal_columns,
    _create_audit_log_table,
    _create_auto_withdrawal_table,
    _create_backup_state_table,
    _create_cex_exchange_orders_table,
    _create_market_index_table,
    _create_prediction_market_tables,
    _create_provider_settings_table,
    _create_scheduled_tasks_table,
    _create_sentiment_cache_table,
    _create_trade_alerts_table,
    _update_token_limit_supply,
    ensure_schema,
    init_db,
)


__all__ = [
    "Any",
    "Base",
    "SessionLocal",
    "_TS_TYPE",
    "_add_column_if_missing",
    "_add_event_connection_columns",
    "_add_health_check_columns",
    "_add_missing_trade_columns",
    "_add_risk_profile_position_monitor",
    "_add_strategy_columns",
    "_add_strategy_generation_columns",
    "_add_withdrawal_columns",
    "_attempt_data_recovery",
    "_create_audit_log_table",
    "_create_auto_withdrawal_table",
    "_create_backup_state_table",
    "_create_cex_exchange_orders_table",
    "_create_error_log_table",
    "_create_execution_metrics_table",
    "_create_knowledge_graph_indexes",
    "_create_knowledge_graph_tables",
    "_create_market_index_table",
    "_create_market_metrics_table",
    "_create_position_monitor_table",
    "_create_prediction_market_tables",
    "_create_provider_settings_table",
    "_create_scheduled_tasks_table",
    "_create_sentiment_cache_table",
    "_create_strategy_analysis_table",
    "_create_strategy_orders_table",
    "_create_system_health_table",
    "_create_trade_alerts_table",
    "_create_trade_insights_table",
    "_publish_corruption_alert",
    "_restore_recovered_data",
    "_set_sqlite_busy_timeout",
    "_table_exists",
    "_update_token_limit_supply",
    "app_settings",
    "engine",
    "ensure_schema",
    "init_db",
    "inspect",
    "json",
    "log_audit",
    "logger",
    "os",
    "seed_default_data",
    "text",
    "time",
]
