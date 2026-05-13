"""fix id sequences and risk_allowed boolean type

Revision ID: 69fd299f8e66
Revises: 
Create Date: 2026-05-12 02:10:00.000000

"""
from alembic import op

revision = '69fd299f8e66'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Fix risk_allowed column: was double precision, should be boolean
    op.execute(
        "ALTER TABLE trade_attempts ALTER COLUMN risk_allowed "
        "TYPE boolean USING CASE WHEN risk_allowed = 0 THEN FALSE "
        "WHEN risk_allowed IS NOT NULL THEN TRUE ELSE NULL END"
    )

    # Create missing id sequences for tables that need auto-increment
    op.execute("CREATE SEQUENCE IF NOT EXISTS trades_id_seq START WITH 1476")
    op.execute("ALTER TABLE trades ALTER COLUMN id SET DEFAULT nextval('trades_id_seq')")
    op.execute("ALTER SEQUENCE trades_id_seq OWNED BY trades.id")

    op.execute("CREATE SEQUENCE IF NOT EXISTS signals_id_seq START WITH 29921")
    op.execute("ALTER TABLE signals ALTER COLUMN id SET DEFAULT nextval('signals_id_seq')")
    op.execute("ALTER SEQUENCE signals_id_seq OWNED BY signals.id")

    op.execute("CREATE SEQUENCE IF NOT EXISTS settings_id_seq START WITH 25")
    op.execute("ALTER TABLE settings ALTER COLUMN id SET DEFAULT nextval('settings_id_seq')")
    op.execute("ALTER SEQUENCE settings_id_seq OWNED BY settings.id")

    # Set PostgreSQL lock_timeout and statement_timeout per session
    # (Applied via connect event listener in database.py, not here)


def downgrade():
    op.execute("ALTER TABLE trade_attempts ALTER COLUMN risk_allowed TYPE double precision USING CASE WHEN risk_allowed THEN 1.0 ELSE 0.0 END")
    # Sequences left in place on downgrade — no data loss from keeping them