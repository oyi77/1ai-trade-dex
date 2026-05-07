"""add_settings_table

Revision ID: 882388989397
Revises:
Create Date: 2026-04-20 08:22:15.738000

"""
from alembic import op
import sqlalchemy as sa


revision = '882388989397'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('type', sa.String(), nullable=False, server_default='string'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('updated_by_user_id', sa.String(), nullable=True, server_default='system'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_settings_key', 'settings', ['key'], unique=True)
    op.create_index('ix_settings_created_at', 'settings', ['created_at'])
    op.create_index('ix_settings_updated_at', 'settings', ['updated_at'])


def downgrade() -> None:
    op.drop_index('ix_settings_updated_at', table_name='settings')
    op.drop_index('ix_settings_created_at', table_name='settings')
    op.drop_index('ix_settings_key', table_name='settings')
    op.drop_table('settings')
