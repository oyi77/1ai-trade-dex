"""fix_shadow_trade_genome_fk

Revision ID: 16eab768dc02
Revises: 6d6ce46da9e4
Create Date: 2026-05-05 01:10:30.415497

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '16eab768dc02'
down_revision: Union[str, Sequence[str], None] = '6d6ce46da9e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # First, drop the existing foreign key constraint
    op.drop_constraint('shadow_trade_genome_id_fkey', 'shadow_trade', type_='foreignkey')
    
    # Change the genome_id column from INTEGER to String
    op.alter_column('shadow_trade', 'genome_id', existing_type=sa.INTEGER(), type_=sa.String(), nullable=True)
    
    # Add the new foreign key constraint
    op.create_foreign_key('shadow_trade_genome_id_fkey', 'shadow_trade', 'genome_registry', ['genome_id'], ['genome_id'], ondelete='SET NULL')


def downgrade() -> None:
    """Downgrade schema."""
    # Drop the new foreign key constraint
    op.drop_constraint('shadow_trade_genome_id_fkey', 'shadow_trade', type_='foreignkey')
    
    # Change the genome_id column back from String to INTEGER
    op.alter_column('shadow_trade', 'genome_id', existing_type=sa.String(), type_=sa.INTEGER(), nullable=True)
    
    # Add the original foreign key constraint
    op.create_foreign_key('shadow_trade_genome_id_fkey', 'shadow_trade', 'genome_registry', ['genome_id'], ['id'], ondelete='SET NULL')
