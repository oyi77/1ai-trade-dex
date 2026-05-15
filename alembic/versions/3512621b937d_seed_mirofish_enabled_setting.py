"""seed mirofish_enabled setting

Revision ID: 3512621b937d
Revises: 8f98f43940f4
Create Date: 2026-05-15 01:10:46.037183

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3512621b937d'
down_revision: Union[str, Sequence[str], None] = '8f98f43940f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    from sqlalchemy import table, column, String, JSON
    from datetime import datetime, timezone

    # Define the system_settings table structure for bulk insert
    system_settings_table = table(
        'system_settings',
        column('key', String),
        column('value', JSON),
        column('updated_at', DateTime)
    )

    # Insert the mirofish_enabled setting with default value true
    op.bulk_insert(
        system_settings_table,
        [
            {
                'key': 'mirofish_enabled',
                'value': True,
                'updated_at': datetime.now(timezone.utc)
            }
        ]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM system_settings WHERE key = 'mirofish_enabled'")
