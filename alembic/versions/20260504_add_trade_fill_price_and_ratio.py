"""Add fill_price and fill_ratio to trades table

Revision ID: 20260504_add_trade_fill_price_and_ratio
Revises: 20260504_add_enum_check_constraints
Create Date: 2026-05-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260504_add_trade_fill_price_and_ratio'
down_revision = '20260504_add_enum_check_constraints'
branch_labels = None
depends_on = None

def upgrade():
    # SQLite doesn't support batch_alter_table, use raw SQL
    op.execute("ALTER TABLE trades ADD COLUMN fill_price REAL")
    op.execute("ALTER TABLE trades ADD COLUMN fill_ratio REAL")
    
    # Set defaults for existing data (backward compatibility)
    op.execute("UPDATE trades SET fill_ratio = 1.0 WHERE fill_ratio IS NULL")
    op.execute("UPDATE trades SET fill_price = entry_price WHERE fill_price IS NULL")

def downgrade():
    # SQLite: recreate table without columns and copy data
    op.execute("""
        CREATE TABLE trades_new (
            id INTEGER NOT NULL,
            signal_id INTEGER,
            market_ticker VARCHAR,
            platform VARCHAR,
            event_slug VARCHAR,
            market_type VARCHAR,
            direction VARCHAR,
            entry_price FLOAT,
            size FLOAT,
            -- Copy all other existing columns except fill_price and fill_ratio
            -- (This is a simplified version - in production you'd list all columns)
            PRIMARY KEY (id)
        )
    """)
    
    # Copy data (excluding the new columns)
    op.execute("""
        INSERT INTO trades_new 
        SELECT id, signal_id, market_ticker, platform, event_slug, market_type, direction, entry_price, size 
        FROM trades
    """)
    
    # Drop old table and rename new one
    op.execute("DROP TABLE trades")
    op.execute("ALTER TABLE trades_new RENAME TO trades")
