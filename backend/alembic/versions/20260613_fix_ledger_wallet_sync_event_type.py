"""Fix transaction_events rows with invalid type='ledger_wallet_sync'

Revision ID: fix_ledger_wallet_sync_type
Revises: add_decision_execution_status
Create Date: 2026-06-13

BotStateLedger._apply previously wrote TransactionEvent.type =
f"ledger_{operation}" (e.g. "ledger_wallet_sync"), which is not a member of
the transaction_event_type enum. SQLite accepts this on INSERT (no
constraint enforcement), but any later ORM SELECT of the table raises
LookupError for these rows — 989 rows in production, all from
sync_to_absolute(operation="wallet_sync").

botstate_ledger.py now maps "wallet_sync" (and other non-enum operations) to
"reconciliation_adjustment" going forward. This migration backfills the
existing rows to the same valid value — amount/balance_after/context/note
are untouched, so the wallet-sync narrative is preserved in `note` and
`context.source`; only the schema-invalid `type` discriminator is corrected.
"""

from alembic import op
import sqlalchemy as sa

revision = "fix_ledger_wallet_sync_type"
down_revision = "add_decision_execution_status"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        sa.text(
            "UPDATE transaction_events SET type = 'reconciliation_adjustment' "
            "WHERE type = 'ledger_wallet_sync'"
        )
    )


def downgrade():
    # The original "ledger_wallet_sync" value was never a valid enum member;
    # there is nothing to restore.
    pass
