"""Add error_logs table for centralized error logging

Revision ID: 20260421_error_logging
Revises: 20260421_schema_sync
Create Date: 2026-04-21 06:55:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '20260421_error_logging'
down_revision = '20260421_schema_sync'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create error_logs table with indexes for error tracking and aggregation."""

    try:
        op.create_table(
            'error_logs',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('timestamp', sa.DateTime(), nullable=False),
            sa.Column('error_type', sa.String(255), nullable=False),
            sa.Column('message', sa.Text(), nullable=False),
            sa.Column('endpoint', sa.String(255), nullable=True),
            sa.Column('method', sa.String(10), nullable=True),
            sa.Column('user_id', sa.String(255), nullable=True),
            sa.Column('stack_trace', sa.Text(), nullable=True),
            sa.Column('status_code', sa.Integer(), nullable=True),
            sa.Column('request_id', sa.String(255), nullable=True),
            sa.Column('details', sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_error_logs_timestamp', 'error_logs', ['timestamp'], unique=False)
        op.create_index('ix_error_logs_error_type', 'error_logs', ['error_type'], unique=False)
        op.create_index('ix_error_logs_endpoint', 'error_logs', ['endpoint'], unique=False)
        op.create_index('ix_error_logs_user_id', 'error_logs', ['user_id'], unique=False)
        op.create_index('ix_error_logs_request_id', 'error_logs', ['request_id'], unique=False)
        op.create_index('idx_error_logs_type_timestamp', 'error_logs', ['error_type', 'timestamp'], unique=False)
        op.create_index('idx_error_logs_endpoint_timestamp', 'error_logs', ['endpoint', 'timestamp'], unique=False)
    except Exception as e:
        print(f"Error creating error_logs table: {e}")


def downgrade() -> None:
    """Drop error_logs table."""
    try:
        op.drop_table('error_logs')
    except Exception as e:
        print(f"Error dropping error_logs table: {e}")
