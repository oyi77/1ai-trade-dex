"""merge all heads

Revision ID: 1badad08bfb2
Revises: 1e3104ecfae7, a9f3c1e2b4d5, create_genome_shadow_trade
Create Date: 2026-05-10 19:55:29.392476

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1badad08bfb2'
down_revision: Union[str, Sequence[str], None] = ('1e3104ecfae7', 'a9f3c1e2b4d5', 'create_genome_shadow_trade')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
