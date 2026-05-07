"""add_hft_execution_record

Revision ID: 1e3104ecfae7
Revises: add_calibration_price_bucket
Create Date: 2026-05-07 12:12:53.601412

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1e3104ecfae7'
down_revision: Union[str, Sequence[str], None] = 'add_calibration_price_bucket'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'hft_execution_records',
        sa.Column('execution_id', sa.String(), nullable=False),
        sa.Column('signal_id', sa.String(), nullable=True),
        sa.Column('order_id', sa.String(), nullable=True),
        sa.Column('side', sa.String(), nullable=True),
        sa.Column('size', sa.Float(), nullable=True),
        sa.Column('price', sa.Float(), nullable=True),
        sa.Column('execution_latency_ms', sa.Float(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('error', sa.String(), nullable=True),
        sa.Column('timestamp', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.PrimaryKeyConstraint('execution_id')
    )
    op.create_index(op.f('ix_hft_execution_records_signal_id'), 'hft_execution_records', ['signal_id'], unique=False)
    op.create_index(op.f('ix_hft_execution_records_created_at'), 'hft_execution_records', ['created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_hft_execution_records_created_at'), table_name='hft_execution_records')
    op.drop_index(op.f('ix_hft_execution_records_signal_id'), table_name='hft_execution_records')
    op.drop_table('hft_execution_records')
