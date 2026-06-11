"""Add execution_status to decision_log so executors mark handled decisions.

Revision ID: arb_exec_status_001
Revises: activity_events_001
Create Date: 2026-06-11
"""

from alembic import op
import sqlalchemy as sa

revision = "arb_exec_status_001"
down_revision = "activity_events_001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "decision_log", sa.Column("execution_status", sa.String(), nullable=True)
    )
    op.create_index(
        "ix_decision_log_execution_status", "decision_log", ["execution_status"]
    )


def downgrade():
    op.drop_index("ix_decision_log_execution_status", table_name="decision_log")
    op.drop_column("decision_log", "execution_status")
