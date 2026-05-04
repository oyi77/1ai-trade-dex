"""Create genome_registry table

Revision ID: 20260504_create_genome_registry
Revises: 20260504_create_shadow_trade
Create Date: 2026-05-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260504_create_genome_registry'
down_revision = '20260504_create_shadow_trade'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'genome_registry',
        sa.Column('genome_id', sa.TEXT(), nullable=False),
        sa.Column('strategy_name', sa.TEXT(), nullable=False),
        sa.Column('archetype', sa.TEXT(), nullable=False),
        sa.Column('version', sa.TEXT(), nullable=False),
        sa.Column('stage', sa.TEXT(), nullable=False),
        sa.Column('lineage_json', sa.TEXT(), nullable=False),
        sa.Column('chromosomes_json', sa.TEXT(), nullable=False),
        sa.Column('fitness_json', sa.TEXT(), nullable=False),
        sa.Column('chromosome_perf_json', sa.TEXT(), nullable=True),
        sa.Column('death_certificate_json', sa.TEXT(), nullable=True),
        sa.Column('created_at', sa.DATETIME(), nullable=True),
        sa.Column('updated_at', sa.DATETIME(), nullable=True),
        sa.PrimaryKeyConstraint('genome_id')
    )
    op.create_index(op.f('idx_genome_stage'), 'genome_registry', ['stage'], unique=False)
    op.create_index(op.f('idx_genome_archetype'), 'genome_registry', ['archetype'], unique=False)
    op.create_index(op.f('idx_genome_fitness'), 'genome_registry', ['stage', 'created_at'], unique=False)
    
    # Add genome_id column to strategyconfig (SQLite compatible)
    op.execute("ALTER TABLE strategyconfig ADD COLUMN genome_id TEXT")
    op.execute("""
        CREATE TABLE strategyconfig_new (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            config_json TEXT NOT NULL,
            is_active BOOLEAN NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            genome_id TEXT,
            FOREIGN KEY (genome_id) REFERENCES genome_registry(genome_id)
        )
    """)
    
    # Copy data
    op.execute("""
        INSERT INTO strategyconfig_new (id, name, description, config_json, is_active, created_at, updated_at, genome_id)
        SELECT id, name, description, config_json, is_active, created_at, updated_at, genome_id
        FROM strategyconfig
    """)
    
    # Replace table
    op.execute("DROP TABLE strategyconfig")
    op.execute("ALTER TABLE strategyconfig_new RENAME TO strategyconfig")

def downgrade():
    # Remove foreign key by recreating table without it
    op.execute("""
        CREATE TABLE strategyconfig_new (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            config_json TEXT NOT NULL,
            is_active BOOLEAN NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        )
    """)
    
    # Copy data (excluding genome_id)
    op.execute("""
        INSERT INTO strategyconfig_new (id, name, description, config_json, is_active, created_at, updated_at)
        SELECT id, name, description, config_json, is_active, created_at, updated_at
        FROM strategyconfig
    """)
    
    # Replace table
    op.execute("DROP TABLE strategyconfig")
    op.execute("ALTER TABLE strategyconfig_new RENAME TO strategyconfig")
    
    # Drop genome_registry table
    op.drop_index(op.f('idx_genome_fitness'), table_name='genome_registry')
    op.drop_index(op.f('idx_genome_archetype'), table_name='genome_registry')
    op.drop_index(op.f('idx_genome_stage'), table_name='genome_registry')
    op.drop_table('genome_registry')
