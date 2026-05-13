"""merge heads

Revision ID: f993aa61ad7d
Revises: 16eab768dc02, a1b2c3d4e5f6
Create Date: 2026-05-06 16:05:31.392348

"""
from typing import Sequence, Union



# revision identifiers, used by Alembic.
revision: str = 'f993aa61ad7d'
down_revision: Union[str, Sequence[str], None] = ('16eab768dc02', 'a1b2c3d4e5f6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
