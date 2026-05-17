"""Add journal fields to trades

Revision ID: add_journal_fields
Revises: 20260421_error_logging
Create Date: 2026-05-17
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_journal_fields'
down_revision = '20260421_error_logging'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('trades', sa.Column('journal_notes', sa.Text(), nullable=True))
    op.add_column('trades', sa.Column('journal_tags', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('trades', 'journal_tags')
    op.drop_column('trades', 'journal_notes')
