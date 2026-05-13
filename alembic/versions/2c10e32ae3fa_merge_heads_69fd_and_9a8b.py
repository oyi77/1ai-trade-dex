"""merge heads 69fd and 9a8b

Revision ID: 2c10e32ae3fa
Revises: 69fd299f8e66, 9a8b7c6d5e4f
Create Date: 2026-05-12 03:33:54.536815

"""
from typing import Sequence, Union



# revision identifiers, used by Alembic.
revision: str = '2c10e32ae3fa'
down_revision: Union[str, Sequence[str], None] = ('69fd299f8e66', '9a8b7c6d5e4f')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
