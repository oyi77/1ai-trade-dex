"""Add execution_status to decision_log so executors mark handled decisions

Revision ID: add_decision_execution_status
Revises: add_arb_bundle_tracking
Create Date: 2026-06-13

Re-creates (idempotently) the schema change originally applied via the
legacy root alembic/ directory's "arb_exec_status_001" revision, which is
not part of this (backend/alembic, canonical) revision graph — see
docs/alembic-dirs.md. That stray migration already ran against the shared
DB (decision_log.execution_status + its index exist there), so this
migration no-ops on that DB while still applying cleanly on a fresh one.
"""

from alembic import op
import sqlalchemy as sa

revision = "add_decision_execution_status"
down_revision = "add_arb_bundle_tracking"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    columns = {c["name"] for c in inspector.get_columns("decision_log")}
    if "execution_status" not in columns:
        op.add_column(
            "decision_log", sa.Column("execution_status", sa.String(), nullable=True)
        )

    indexes = {ix["name"] for ix in inspector.get_indexes("decision_log")}
    if "ix_decision_log_execution_status" not in indexes:
        op.create_index(
            "ix_decision_log_execution_status", "decision_log", ["execution_status"]
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    indexes = {ix["name"] for ix in inspector.get_indexes("decision_log")}
    if "ix_decision_log_execution_status" in indexes:
        op.drop_index("ix_decision_log_execution_status", table_name="decision_log")

    columns = {c["name"] for c in inspector.get_columns("decision_log")}
    if "execution_status" in columns:
        op.drop_column("decision_log", "execution_status")
