"""add calibration price bucket

Revision ID: add_calibration_price_bucket
Revises: 20260507_add_trade_role
Create Date: 2026-05-08
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_calibration_price_bucket'
down_revision = '20260507_add_trade_role'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('calibration_records', sa.Column('price_bucket', sa.String(), nullable=True))
    op.create_index('ix_calibration_records_price_bucket', 'calibration_records', ['price_bucket'])

def downgrade():
    op.drop_index('ix_calibration_records_price_bucket', table_name='calibration_records')
    op.drop_column('calibration_records', 'price_bucket')
