"""Fix result='loss' rows with positive pnl from pre-ADR-016/018 settlements

Revision ID: fix_stale_loss_positive_pnl
Revises: fix_ledger_wallet_sync_type
Create Date: 2026-06-13

Before ADR-016 (commit f3cd8302, Bug M) and ADR-018 (commit 1e1cdb85, Bug P),
the expired_unresolved/closed_unresolved settlement branches hardcoded
trade.result = "loss" and settlement_value = 0.0 regardless of trade.direction.
For direction='no' trades, calculate_pnl(direction='no', settlement_value=0.0)
correctly computes a POSITIVE pnl (the NO/DOWN outcome occurred, a win payout
for a NO holder) -- but result stayed "loss".

15 trades settled 2026-06-10..2026-06-12 (before both fixes landed
2026-06-13) have this mismatch: result='loss' but pnl>0. credit_on_settlement
already applied the correct positive pnl to bankroll/total_pnl at settlement
time (its is_loss branch adds trade.pnl directly, same formula as the is_win
branch), so bankroll/total_pnl need no correction -- only the result label,
and the win counters that credit_on_settlement skipped because is_win was
False at the time.

6 rows: trading_mode='paper', strategy='bond_scanner' -> bot_state.paper_wins += 6
9 rows: trading_mode='live' (5 bond_scanner + 4 position_sync)
    -> bot_state.winning_trades += 9 (mode='live' row)
"""

from alembic import op
import sqlalchemy as sa

revision = "fix_stale_loss_positive_pnl"
down_revision = "fix_ledger_wallet_sync_type"
branch_labels = None
depends_on = None

# All settled before 2026-06-13 (the day ADR-016/018 fixes landed), all
# direction='no', settlement_value=0.0, result='loss', pnl>0.
PAPER_TRADE_IDS = [23903, 24156, 25087, 25265, 25328, 25440]
LIVE_TRADE_IDS = [25693, 25694, 25699, 25700, 25753, 25709, 25717, 25725, 25746]


def upgrade():
    all_ids = ",".join(str(i) for i in PAPER_TRADE_IDS + LIVE_TRADE_IDS)
    op.execute(
        sa.text(
            f"UPDATE trades SET result = 'win' "
            f"WHERE id IN ({all_ids}) AND result = 'loss' AND pnl > 0"
        )
    )
    op.execute(
        sa.text("UPDATE bot_state SET paper_wins = paper_wins + 6 WHERE mode = 'paper'")
    )
    op.execute(
        sa.text(
            "UPDATE bot_state SET winning_trades = winning_trades + 9 WHERE mode = 'live'"
        )
    )


def downgrade():
    all_ids = ",".join(str(i) for i in PAPER_TRADE_IDS + LIVE_TRADE_IDS)
    op.execute(
        sa.text(f"UPDATE trades SET result = 'loss' WHERE id IN ({all_ids}) AND result = 'win'")
    )
    op.execute(
        sa.text("UPDATE bot_state SET paper_wins = paper_wins - 6 WHERE mode = 'paper'")
    )
    op.execute(
        sa.text(
            "UPDATE bot_state SET winning_trades = winning_trades - 9 WHERE mode = 'live'"
        )
    )
