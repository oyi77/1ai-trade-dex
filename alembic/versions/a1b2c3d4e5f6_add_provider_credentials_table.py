"""add_provider_credentials_table

Revision ID: a1b2c3d4e5f6
Revises: 2c10e32ae3fa
Create Date: 2026-05-12 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '2c10e32ae3fa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'provider_credentials',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('provider_name', sa.String(), nullable=False),
        sa.Column('config_key', sa.String(), nullable=False),
        sa.Column('config_value', sa.Text(), nullable=True),
        sa.Column('is_secret', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider_name', 'config_key', name='uq_provider_credentials'),
    )
    op.create_index('ix_provider_credentials_id', 'provider_credentials', ['id'])
    op.create_index(
        'idx_provider_credentials_name', 'provider_credentials', ['provider_name']
    )


def downgrade() -> None:
    op.drop_index('idx_provider_credentials_name', table_name='provider_credentials')
    op.drop_index('ix_provider_credentials_id', table_name='provider_credentials')
    op.drop_table('provider_credentials')
