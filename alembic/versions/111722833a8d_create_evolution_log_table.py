"""create_evolution_log_table

Revision ID: 111722833a8d
Revises: 20260504_create_knowledge_graph
Create Date: 2026-05-05 00:43:46.212974

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '111722833a8d'
down_revision: Union[str, Sequence[str], None] = '20260504_create_knowledge_graph'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'evolution_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('genome_id', sa.String(), nullable=True),
        sa.Column('event_type', sa.String(), nullable=True),
        sa.Column('from_stage', sa.String(), nullable=True),
        sa.Column('to_stage', sa.String(), nullable=True),
        sa.Column('data', sa.JSON(), nullable=True),
        sa.Column('timestamp', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['genome_id'], ['genome_registry.genome_id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_evolution_log_genome_id'), 'evolution_log', ['genome_id'], unique=False)
    op.create_index(op.f('ix_evolution_log_timestamp'), 'evolution_log', ['timestamp'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_evolution_log_timestamp'), table_name='evolution_log')
    op.drop_index(op.f('ix_evolution_log_genome_id'), table_name='evolution_log')
    op.drop_table('evolution_log')
