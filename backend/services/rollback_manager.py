"""Rollback Manager - Wave 4c

Manages strategy configuration snapshots and rollback operations for proposals.
Provides the ability to revert strategy changes when proposals have negative impact.

Features:
- Snapshot strategy configs before proposal execution
- Restore previous configs on rollback
- Track rollback history in audit logs
- Admin-only rollback operations
"""

from typing import Optional
from datetime import datetime, timezone

import backend.models.database as _db_mod
from backend.models.database import StrategyProposal, StrategyConfig

from loguru import logger


class RollbackManager:
    """Manages strategy configuration snapshots and rollback operations."""

    def __init__(self):
        self.logger = logger
        self.snapshots: dict = {}

    def create_snapshot(self, proposal_id: int, strategy_name: str) -> bool:
        """Create a snapshot of current strategy configuration before proposal execution.

        Args:
            proposal_id: ID of the proposal being executed
            strategy_name: Name of the strategy to snapshot

        Returns:
            True if snapshot created successfully, False otherwise
        """
        db = _db_mod.SessionLocal()
        try:
            config = db.query(StrategyConfig).filter(
                StrategyConfig.strategy_name == strategy_name
            ).first()

            if not config:
                self.logger.error(f"Strategy config not found: {strategy_name}")
                return False

            proposal = db.query(StrategyProposal).filter(
                StrategyProposal.id == proposal_id
            ).first()

            if not proposal:
                self.logger.error(f"Proposal not found: {proposal_id}")
                return False

            snapshot_data = {
                'strategy_name': strategy_name,
                'config_snapshot': {
                    'enabled': config.enabled,
                    'interval_seconds': config.interval_seconds,
                    'params': config.params,
                    'mode': config.mode if hasattr(config, 'mode') else None
                },
                'snapshot_at': datetime.now(timezone.utc).isoformat(),
                'proposal_id': proposal_id
            }

            if not proposal.change_details:
                proposal.change_details = {}

            proposal.change_details['config_snapshot'] = snapshot_data
            db.commit()

            self.logger.info(
                f"Created config snapshot for strategy '{strategy_name}' "
                f"(proposal {proposal_id})"
            )
            return True

        except Exception as e:
            self.logger.error(f"Failed to create snapshot: {e}")
            db.rollback()
            return False
        finally:
            db.close()

    def rollback_proposal(self, proposal_id: int) -> bool:
        """Rollback a proposal by restoring the previous strategy configuration.

        Args:
            proposal_id: ID of the proposal to rollback

        Returns:
            True if rollback successful, False otherwise
        """
        db = _db_mod.SessionLocal()
        try:
            proposal = db.query(StrategyProposal).filter(
                StrategyProposal.id == proposal_id
            ).first()

            if not proposal:
                self.logger.error(f"Proposal {proposal_id} not found")
                return False

            if proposal.admin_decision != 'approved':
                self.logger.error(
                    f"Cannot rollback proposal {proposal_id}: not approved "
                    f"(status: {proposal.admin_decision})"
                )
                return False

            snapshot_data = proposal.change_details.get('config_snapshot')
            if not snapshot_data:
                self.logger.error(
                    f"No config snapshot found for proposal {proposal_id}"
                )
                return False

            strategy_name = snapshot_data['strategy_name']
            config_snapshot = snapshot_data['config_snapshot']

            config = db.query(StrategyConfig).filter(
                StrategyConfig.strategy_name == strategy_name
            ).first()

            if not config:
                self.logger.error(f"Strategy config not found: {strategy_name}")
                return False

            old_config = {
                'enabled': config.enabled,
                'interval_seconds': config.interval_seconds,
                'params': config.params,
                'mode': config.mode if hasattr(config, 'mode') else None
            }

            config.enabled = config_snapshot['enabled']
            config.interval_seconds = config_snapshot['interval_seconds']
            config.params = config_snapshot['params']
            if hasattr(config, 'mode') and config_snapshot.get('mode'):
                config.mode = config_snapshot['mode']

            rollback_log = {
                'rolled_back_at': datetime.now(timezone.utc).isoformat(),
                'strategy_name': strategy_name,
                'config_before_rollback': old_config,
                'config_after_rollback': config_snapshot
            }

            if not proposal.change_details:
                proposal.change_details = {}

            if 'rollback_history' not in proposal.change_details:
                proposal.change_details['rollback_history'] = []

            proposal.change_details['rollback_history'].append(rollback_log)
            proposal.admin_decision = 'rolled_back'

            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(proposal, 'change_details')

            db.commit()

            self.logger.info(
                f"Rolled back proposal {proposal_id} for strategy '{strategy_name}'"
            )
            return True

        except Exception as e:
            self.logger.error(f"Failed to rollback proposal {proposal_id}: {e}")
            db.rollback()
            return False
        finally:
            db.close()

    def get_rollback_history(self, proposal_id: int) -> Optional[list]:
        """Get rollback history for a proposal.

        Args:
            proposal_id: ID of the proposal

        Returns:
            List of rollback log entries or None if not found
        """
        db = _db_mod.SessionLocal()
        try:
            proposal = db.query(StrategyProposal).filter(
                StrategyProposal.id == proposal_id
            ).first()

            if not proposal or not proposal.change_details:
                return None

            return proposal.change_details.get('rollback_history', [])

        finally:
            db.close()

    def can_rollback(self, proposal_id: int) -> bool:
        """Check if a proposal can be rolled back.

        Args:
            proposal_id: ID of the proposal

        Returns:
            True if rollback is possible, False otherwise
        """
        db = _db_mod.SessionLocal()
        try:
            proposal = db.query(StrategyProposal).filter(
                StrategyProposal.id == proposal_id
            ).first()

            if not proposal:
                return False

            if proposal.admin_decision != 'approved':
                return False

            if not proposal.change_details:
                return False

            if 'config_snapshot' not in proposal.change_details:
                return False

            return True

        finally:
            db.close()
