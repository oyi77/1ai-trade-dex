"""Merge heads and add journal fields to trades

Merges the two current heads (add_db_integrity_constraints, add_trade_token_columns)
and adds journal_notes / journal_tags columns to the trades table.

Revision ID: 20260519_merge_and_add_journal
Revises: 20260517_add_db_integrity_constraints, 20260517_add_trade_token_columns
Create Date: 2026-05-19
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '20260519_merge_and_add_journal'
down_revision: Union[str, Sequence[str], None] = (
    '20260517_add_db_integrity_constraints',
    '20260517_add_trade_token_columns',
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return column in {c['name'] for c in insp.get_columns(table)}


def upgrade() -> None:
    if not _column_exists('trades', 'journal_notes'):
        op.add_column('trades', sa.Column('journal_notes', sa.Text(), nullable=True))
    if not _column_exists('trades', 'journal_tags'):
        op.add_column('trades', sa.Column('journal_tags', sa.JSON(), nullable=True))


def downgrade() -> None:
    if _column_exists('trades', 'journal_tags'):
        op.drop_column('trades', 'journal_tags')
    if _column_exists('trades', 'journal_notes'):
        op.drop_column('trades', 'journal_notes')
