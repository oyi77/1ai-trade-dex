"""add_stage_fields_to_genome_registry

Revision ID: 6d6ce46da9e4
Revises: 111722833a8d
Create Date: 2026-05-05 00:51:12.912368

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6d6ce46da9e4'
down_revision: Union[str, Sequence[str], None] = '111722833a8d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('genome_registry', sa.Column('stage_entered_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('genome_registry', 'stage_entered_at')
