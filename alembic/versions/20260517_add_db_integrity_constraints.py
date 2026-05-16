"""
Add missing FK constraints and CHECK constraints for data integrity

Adds 10 FK constraints that exist in ORM model definitions but were never
created via Alembic migration (tables created by metadata.create_all or
initial schema without explicit FK).

Adds CHECK constraints for enum-like String columns not covered by
20260504_add_enum_check_constraints (Trade.result, Trade.trading_mode,
Trade.market_type, Trade.role, Signal.execution_mode, Signal.market_type,
HFTExecutionRecord columns, BotState.mode, StrategyConfig.time_horizon/risk_tier,
DecisionLog.outcome).

Uses raw SQLite DDL for CHECK constraints (same approach as existing migration)
and batch_alter_table for FK constraints.

Revision ID: 20260517_add_db_integrity_constraints
Revises: merge_active_heads
Create Date: 2026-05-17
"""

from alembic import op
import sqlalchemy as sa

revision = '20260517_add_db_integrity_constraints'
down_revision = ('merge_active_heads', '20260514_add_signal_log')
branch_labels = None
depends_on = None

# ── FK constraints: (table, column, constraint_name, ref_table, ref_column, on_delete) ──
FK_CONSTRAINTS = [
    ("trades", "signal_id", "fk_trades_signal_id", "signals", "id", "SET NULL"),
    ("trade_attempts", "trade_id", "fk_trade_attempts_trade_id", "trades", "id", "SET NULL"),
    ("settlement_events", "trade_id", "fk_settlement_events_trade_id", "trades", "id", "CASCADE"),
    ("trade_context", "trade_id", "fk_trade_context_trade_id", "trades", "id", "CASCADE"),
    ("experiments", "strategy_name", "fk_experiments_strategy_name", "strategy_config", "strategy_name", "SET NULL"),
    ("proposal_feedback", "proposal_id", "fk_proposal_feedback_proposal_id", "strategy_proposal", "id", "CASCADE"),
    ("evolution_lineage", "parent_experiment_id", "fk_evolution_lineage_parent", "experiment_records", "id", "SET NULL"),
    ("evolution_lineage", "child_experiment_id", "fk_evolution_lineage_child", "experiment_records", "id", "CASCADE"),
    ("kg_relations", "from_entity_id", "fk_kg_relations_from_entity", "kg_entities", "id", "CASCADE"),
    ("kg_relations", "to_entity_id", "fk_kg_relations_to_entity", "kg_entities", "id", "CASCADE"),
]

# ── CHECK constraints: {table: {constraint_name: (column, [valid_values])}} ──
CHECKS = {
    "trades": {
        "ck_trades_result": ("result", ["pending", "win", "loss", "expired", "push", "closed"]),
        "ck_trades_trading_mode": ("trading_mode", ["paper", "testnet", "live"]),
        "ck_trades_market_type": ("market_type", ["btc", "weather"]),
        "ck_trades_role": ("role", ["maker", "taker", "unknown"]),
    },
    "signals": {
        "ck_signals_execution_mode": ("execution_mode", ["paper", "live"]),
        "ck_signals_market_type": ("market_type", ["btc", "weather"]),
    },
    "hft_execution_records": {
        "ck_hft_status": ("status", ["pending", "filled", "failed", "queued", "cancelled"]),
        "ck_hft_side": ("side", ["BUY", "SELL"]),
        "ck_hft_trading_mode": ("trading_mode", ["paper", "testnet", "live"]),
        "ck_hft_role": ("role", ["maker", "taker", "unknown"]),
    },
    "bot_state": {
        "ck_bot_state_mode": ("mode", ["paper", "testnet", "live"]),
    },
    "strategy_config": {
        "ck_strat_config_time_horizon": ("time_horizon", ["short", "mid", "long"]),
        "ck_strat_config_risk_tier": ("risk_tier", [
            "safe", "conservative", "moderate", "aggressive", "extreme", "crazy",
        ]),
    },
    "decision_log": {
        "ck_decision_log_outcome": ("outcome", ["WIN", "LOSS", "PUSH"]),
    },
    "strategy_outcomes": {
        "ck_strat_outcomes_result": ("result", ["win", "loss", "push"]),
        "ck_strat_outcomes_market_type": ("market_type", ["btc", "weather"]),
        "ck_strat_outcomes_trading_mode": ("trading_mode", ["paper", "testnet", "live"]),
    },
}


def _build_check_expr(column, valid_values):
    quoted = ", ".join(f"'{v}'" for v in valid_values)
    return f"({column} IS NULL OR {column} IN ({quoted}))"


def _rebuild_table_with_checks(raw, table, constraints):
    """Rebuild a SQLite table adding CHECK constraints via temp-table swap."""
    col_defs = raw.execute(f"PRAGMA table_info([{table}])").fetchall()
    fk_defs = raw.execute(f"PRAGMA foreign_key_list([{table}])").fetchall()

    col_sqls = []
    for cid, cname, ctype, notnull, dflt, pk in col_defs:
        parts = [f"[{cname}]", ctype]
        if pk:
            parts.append("NOT NULL")
        elif notnull:
            parts.append("NOT NULL")
        if dflt is not None:
            parts.append(f"DEFAULT {dflt}")
        col_sqls.append(" ".join(parts))

    pk_cols = [r[1] for r in col_defs if r[5] == 1]
    if pk_cols:
        col_sqls.append(f"PRIMARY KEY ({', '.join(f'[{c}]' for c in pk_cols)})")

    for fk_id, seq, ref_table, from_col, to_col, on_update, on_delete, _match in fk_defs:
        col_sqls.append(
            f"FOREIGN KEY([{from_col}]) REFERENCES [{ref_table}] ([{to_col}])"
            f" ON DELETE {on_delete or 'NO ACTION'} ON UPDATE {on_update or 'NO ACTION'}"
        )

    for ck_name, (column, valid) in constraints.items():
        col_sqls.append(f"CONSTRAINT [{ck_name}] CHECK {_build_check_expr(column, valid)}")

    col_list = ", ".join(f"[{r[1]}]" for r in col_defs)
    tmp = f"_alembic_tmp_{table}"

    raw.execute(f"CREATE TABLE [{tmp}] ({', '.join(col_sqls)})")
    raw.execute(f"INSERT INTO [{tmp}] ({col_list}) SELECT {col_list} FROM [{table}]")
    raw.execute(f"DROP TABLE [{table}]")
    raw.execute(f"ALTER TABLE [{tmp}] RENAME TO [{table}]")


def _rebuild_table_without_checks(raw, table, constraint_names_to_drop):
    """Rebuild a SQLite table removing CHECK constraints by name."""
    col_defs = raw.execute(f"PRAGMA table_info([{table}])").fetchall()
    fk_defs = raw.execute(f"PRAGMA foreign_key_list([{table}])").fetchall()

    col_sqls = []
    for cid, cname, ctype, notnull, dflt, pk in col_defs:
        parts = [f"[{cname}]", ctype]
        if pk:
            parts.append("NOT NULL")
        elif notnull:
            parts.append("NOT NULL")
        if dflt is not None:
            parts.append(f"DEFAULT {dflt}")
        col_sqls.append(" ".join(parts))

    pk_cols = [r[1] for r in col_defs if r[5] == 1]
    if pk_cols:
        col_sqls.append(f"PRIMARY KEY ({', '.join(f'[{c}]' for c in pk_cols)})")

    for fk_id, seq, ref_table, from_col, to_col, on_update, on_delete, _match in fk_defs:
        col_sqls.append(
            f"FOREIGN KEY([{from_col}]) REFERENCES [{ref_table}] ([{to_col}])"
            f" ON DELETE {on_delete or 'NO ACTION'} ON UPDATE {on_update or 'NO ACTION'}"
        )

    col_list = ", ".join(f"[{r[1]}]" for r in col_defs)
    tmp = f"_alembic_tmp_{table}"

    raw.execute(f"CREATE TABLE [{tmp}] ({', '.join(col_sqls)})")
    raw.execute(f"INSERT INTO [{tmp}] ({col_list}) SELECT {col_list} FROM [{table}]")
    raw.execute(f"DROP TABLE [{table}]")
    raw.execute(f"ALTER TABLE [{tmp}] RENAME TO [{table}]")


def upgrade() -> None:
    conn = op.get_bind()
    raw = conn.connection.dbapi_connection

    # ── Part 1: Add FK constraints using batch_alter_table ──
    conn.execute(sa.text("PRAGMA foreign_keys=OFF"))
    raw.execute("PRAGMA foreign_keys=OFF")

    # Clean up any leftover temp tables
    for name in raw.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '_alembic_tmp%'"
    ).fetchall():
        raw.execute('DROP TABLE IF EXISTS [' + name[0] + ']')

    insp = sa.inspect(conn)
    existing_tables = set(insp.get_table_names())

    for table, column, constraint_name, ref_table, ref_column, on_delete in FK_CONSTRAINTS:
        if table not in existing_tables:
            continue
        # Check if FK already exists
        fk_defs = raw.execute(f"PRAGMA foreign_key_list([{table}])").fetchall()
        existing_fks = {
            (fk[2], fk[3], fk[4])  # (ref_table, from_col, to_col)
            for fk in fk_defs
        }
        if (ref_table, column, ref_column) in existing_fks:
            continue

        try:
            with op.batch_alter_table(table, schema=None) as batch_op:
                batch_op.create_foreign_key(
                    constraint_name,
                    referent_table=ref_table,
                    local_cols=[column],
                    remote_cols=[ref_column],
                    ondelete=on_delete,
                )
        except Exception as e:
            print(f"FK {constraint_name}: {e}")

    # ── Part 2: Add CHECK constraints via table rebuild ──
    for table, constraints in CHECKS.items():
        if table not in existing_tables or not constraints:
            continue

        orig_ddl = raw.execute(
            f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table}'"
        ).fetchone()
        if orig_ddl:
            existing_cks = {ck for ck in constraints if f'CONSTRAINT [{ck}]' in orig_ddl[0]}
            if len(existing_cks) == len(constraints):
                continue

        _rebuild_table_with_checks(raw, table, constraints)

    raw.execute("PRAGMA foreign_keys=ON")


def downgrade() -> None:
    conn = op.get_bind()
    raw = conn.connection.dbapi_connection

    conn.execute(sa.text("PRAGMA foreign_keys=OFF"))
    raw.execute("PRAGMA foreign_keys=OFF")

    insp = sa.inspect(conn)
    existing_tables = set(insp.get_table_names())

    # ── Drop CHECK constraints ──
    for table, constraints in CHECKS.items():
        if table not in existing_tables or not constraints:
            continue
        _rebuild_table_without_checks(raw, table, set(constraints.keys()))

    # ── Drop FK constraints ──
    for table, column, constraint_name, ref_table, ref_column, on_delete in reversed(FK_CONSTRAINTS):
        if table not in existing_tables:
            continue
        try:
            with op.batch_alter_table(table, schema=None) as batch_op:
                batch_op.drop_constraint(constraint_name, type_='foreignkey')
        except Exception as e:
            print(f"Drop FK {constraint_name}: {e}")

    raw.execute("PRAGMA foreign_keys=ON")
