"""phase2_feature_schemas

Revision ID: 882388989398
Revises: 882388989397
Create Date: 2026-04-20 10:28:45.301000

"""
from alembic import op
import sqlalchemy as sa
import logging

logger = logging.getLogger(__name__)


revision = '882388989398'
down_revision = '882388989397'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create activity_log table
    op.create_table(
        'activity_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('strategy_name', sa.String(length=100), nullable=False),
        sa.Column('decision_type', sa.String(length=50), nullable=False),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.Column('confidence_score', sa.Float(), nullable=False),
        sa.Column('mode', sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_activity_log_id', 'activity_log', ['id'])
    op.create_index('ix_activity_log_timestamp', 'activity_log', ['timestamp'])
    op.create_index('ix_activity_log_strategy_name', 'activity_log', ['strategy_name'])

    # Create strategy_proposal table
    op.create_table(
        'strategy_proposal',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('strategy_name', sa.String(length=100), nullable=False),
        sa.Column('change_details', sa.JSON(), nullable=False),
        sa.Column('expected_impact', sa.String(length=1000), nullable=False),
        sa.Column('admin_decision', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('executed_at', sa.DateTime(), nullable=True),
        sa.Column('impact_measured', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('admin_user_id', sa.String(length=100), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_strategy_proposal_id', 'strategy_proposal', ['id'])
    op.create_index('ix_strategy_proposal_strategy_name', 'strategy_proposal', ['strategy_name'])
    op.create_index('ix_strategy_proposal_created_at', 'strategy_proposal', ['created_at'])

    # Create mirofish_signal table
    op.create_table(
        'mirofish_signal',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('prediction_topic', sa.String(length=200), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('report', sa.JSON(), nullable=False),
        sa.Column('debate_weight', sa.Float(), nullable=False, server_default='1.0'),
        sa.Column('processed', sa.Boolean(), nullable=False, server_default='0'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_mirofish_signal_id', 'mirofish_signal', ['id'])
    op.create_index('ix_mirofish_signal_timestamp', 'mirofish_signal', ['timestamp'])

    # audit_log table already exists, but ensure it has all columns
    # Check if audit_log exists and add any missing columns
    try:
        op.add_column('audit_log', sa.Column('event_type', sa.String(), nullable=True))
        logger.info("Successfully added 'event_type' column to audit_log")
    except Exception as e:
        if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
            logger.warning(f"Column 'event_type' already exists in audit_log: {e}")
        else:
            logger.error(f"Unexpected error adding 'event_type' column: {e}")
            raise

    try:
        op.add_column('audit_log', sa.Column('entity_type', sa.String(), nullable=True))
        logger.info("Successfully added 'entity_type' column to audit_log")
    except Exception as e:
        if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
            logger.warning(f"Column 'entity_type' already exists in audit_log: {e}")
        else:
            logger.error(f"Unexpected error adding 'entity_type' column: {e}")
            raise

    try:
        op.add_column('audit_log', sa.Column('entity_id', sa.String(), nullable=True))
        logger.info("Successfully added 'entity_id' column to audit_log")
    except Exception as e:
        if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
            logger.warning(f"Column 'entity_id' already exists in audit_log: {e}")
        else:
            logger.error(f"Unexpected error adding 'entity_id' column: {e}")
            raise

    try:
        op.add_column('audit_log', sa.Column('old_value', sa.JSON(), nullable=True))
        logger.info("Successfully added 'old_value' column to audit_log")
    except Exception as e:
        if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
            logger.warning(f"Column 'old_value' already exists in audit_log: {e}")
        else:
            logger.error(f"Unexpected error adding 'old_value' column: {e}")
            raise

    try:
        op.add_column('audit_log', sa.Column('new_value', sa.JSON(), nullable=True))
        logger.info("Successfully added 'new_value' column to audit_log")
    except Exception as e:
        if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
            logger.warning(f"Column 'new_value' already exists in audit_log: {e}")
        else:
            logger.error(f"Unexpected error adding 'new_value' column: {e}")
            raise

    try:
        op.add_column('audit_log', sa.Column('user_id', sa.String(), nullable=True, server_default='system'))
        logger.info("Successfully added 'user_id' column to audit_log")
    except Exception as e:
        if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
            logger.warning(f"Column 'user_id' already exists in audit_log: {e}")
        else:
            logger.error(f"Unexpected error adding 'user_id' column: {e}")
            raise


def downgrade() -> None:
    # Drop mirofish_signal table
    op.drop_index('ix_mirofish_signal_timestamp', table_name='mirofish_signal')
    op.drop_index('ix_mirofish_signal_id', table_name='mirofish_signal')
    op.drop_table('mirofish_signal')

    # Drop strategy_proposal table
    op.drop_index('ix_strategy_proposal_created_at', table_name='strategy_proposal')
    op.drop_index('ix_strategy_proposal_strategy_name', table_name='strategy_proposal')
    op.drop_index('ix_strategy_proposal_id', table_name='strategy_proposal')
    op.drop_table('strategy_proposal')

    # Drop activity_log table
    op.drop_index('ix_activity_log_strategy_name', table_name='activity_log')
    op.drop_index('ix_activity_log_timestamp', table_name='activity_log')
    op.drop_index('ix_activity_log_id', table_name='activity_log')
    op.drop_table('activity_log')
