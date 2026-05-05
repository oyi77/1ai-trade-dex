"""add live_initial_bankroll to bot_state

Revision ID: a1b2c3d4e5f6
Revises: cd91e4066413
Create Date: 2026-05-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'cd91e4066413'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('bot_state') as batch_op:
        batch_op.add_column(sa.Column('live_initial_bankroll', sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('bot_state') as batch_op:
        batch_op.drop_column('live_initial_bankroll')
