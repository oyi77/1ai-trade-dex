"""add misc_data to experiment_records

Revision ID: a1b2c3d4misc0
Revises: f993aa61ad7d
Create Date: 2026-05-19 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4misc0"
down_revision = "f993aa61ad7d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("experiment_records", sa.Column("misc_data", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("experiment_records", "misc_data")
