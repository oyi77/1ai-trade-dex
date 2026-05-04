"""Create evolution_log table

Revision ID: 20260504_create_evolution_log
Revises: 20260504_create_genome_registry
Create Date: 2026-05-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260504_create_evolution_log'
down_revision = '20260504_create_genome_registry'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'evolution_log',
        sa.Column('id', sa.INTEGER(), nullable=False),
        sa.Column('action', sa.TEXT(), nullable=False),
        sa.Column('target_genome_id', sa.TEXT(), nullable=False),
        sa.Column('new_genome_id', sa.TEXT(), nullable=True),
        sa.Column('reasoning', sa.TEXT(), nullable=False),
        sa.Column('genome_snapshot_json', sa.TEXT(), nullable=False),
        sa.Column('mutations_applied_json', sa.TEXT(), nullable=False),
        sa.Column('expected_outcomes_json', sa.TEXT(), nullable=False),
        sa.Column('risk_flags_json', sa.TEXT(), nullable=True),
        sa.Column('confidence', sa.REAL(), nullable=False),
        sa.Column('timestamp', sa.DATETIME(), nullable=True),
        sa.ForeignKeyConstraint(['target_genome_id'], ['genome_registry.genome_id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_evolution_log_genome_id'), 'evolution_log', ['target_genome_id'], unique=False)
    op.create_index(op.f('ix_evolution_log_action'), 'evolution_log', ['action'], unique=False)
    op.create_index(op.f('ix_evolution_log_timestamp'), 'evolution_log', ['timestamp'], unique=False)

def downgrade():
    op.drop_index(op.f('ix_evolution_log_timestamp'), table_name='evolution_log')
    op.drop_index(op.f('ix_evolution_log_action'), table_name='evolution_log')
    op.drop_index(op.f('ix_evolution_log_genome_id'), table_name='evolution_log')
    op.drop_table('evolution_log')
