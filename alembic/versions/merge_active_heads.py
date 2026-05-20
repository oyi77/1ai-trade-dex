"""Merge all active heads

Revision ID: merge_active_heads
Revises: 3512621b937d, fix_shadow_trade_schema
Create Date: 2026-05-14 22:00:00
"""

from typing import Sequence, Union

revision: str = "merge_active_heads"
down_revision: Union[str, Sequence[str], None] = (
    "3512621b937d",
    "fix_shadow_trade_schema",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op: All migrations already applied."""
    pass


def downgrade() -> None:
    pass
