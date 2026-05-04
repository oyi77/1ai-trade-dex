"""Create knowledge graph tables

Revision ID: 20260504_create_knowledge_graph
Revises: 20260504_create_evolution_log
Create Date: 2026-05-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260504_create_knowledge_graph'
down_revision = '20260504_create_evolution_log'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'kg_node',
        sa.Column('id', sa.INTEGER(), nullable=False),
        sa.Column('type', sa.TEXT(), nullable=False),
        sa.Column('content_json', sa.TEXT(), nullable=False),
        sa.Column('metadata_json', sa.TEXT(), nullable=True),
        sa.Column('created_at', sa.DATETIME(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_kg_node_type'), 'kg_node', ['type'], unique=False)
    
    op.create_table(
        'kg_edge',
        sa.Column('id', sa.INTEGER(), nullable=False),
        sa.Column('source_id', sa.INTEGER(), nullable=False),
        sa.Column('target_id', sa.INTEGER(), nullable=False),
        sa.Column('relationship', sa.TEXT(), nullable=False),
        sa.Column('weight', sa.REAL(), nullable=False),
        sa.Column('metadata_json', sa.TEXT(), nullable=True),
        sa.Column('created_at', sa.DATETIME(), nullable=True),
        sa.ForeignKeyConstraint(['source_id'], ['kg_node.id'], ),
        sa.ForeignKeyConstraint(['target_id'], ['kg_node.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_kg_edge_source'), 'kg_edge', ['source_id'], unique=False)
    op.create_index(op.f('ix_kg_edge_target'), 'kg_edge', ['target_id'], unique=False)
    op.create_index(op.f('ix_kg_edge_relationship'), 'kg_edge', ['relationship'], unique=False)

def downgrade():
    op.drop_index(op.f('ix_kg_edge_relationship'), table_name='kg_edge')
    op.drop_index(op.f('ix_kg_edge_target'), table_name='kg_edge')
    op.drop_index(op.f('ix_kg_edge_source'), table_name='kg_edge')
    op.drop_table('kg_edge')
    op.drop_index(op.f('ix_kg_node_type'), table_name='kg_node')
    op.drop_table('kg_node')
