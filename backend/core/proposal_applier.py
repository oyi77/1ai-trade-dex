"""Proposal Applier - Wave 5c

Integrates approved proposals with strategy executor for real-time config updates.
Implements the proposal → config change → execution workflow:

1. On proposal approval: snapshot current config + apply change to StrategyConfig
2. On next strategy cycle: executor reads updated StrategyConfig from DB
3. Config changes take effect immediately on next execution cycle
4. Rollback scenario: restore config from snapshot if impact negative

This module bridges:
- ProposalExecutor (Wave 4e) for execution and rollback
- StrategyExecutor for reading live configs from DB
- StrategyConfig table for persistent config storage
"""

import logging
import json
from typing import Optional, Dict, Any
from datetime import datetime, timezone

from backend.models.database import (
    SessionLocal,
    StrategyConfig,
    StrategyProposal,
    AuditLog
)

logger = logging.getLogger(__name__)


class ProposalApplier:
    """Applies approved proposals to live strategy configs."""
    
    def __init__(self):
        """Initialize the ProposalApplier."""
        self.logger = logging.getLogger(__name__)
    
    def apply_proposal_to_config(
        self, 
        proposal_id: int,
        db: Optional[Any] = None
    ) -> bool:
        """Apply an approved proposal to the strategy config.
        
        This is called after admin approval to update the live config.
        The strategy executor will read the updated config on its next cycle.
        
        Args:
            proposal_id: Database ID of the approved proposal
            db: Optional database session (creates new if None)
        
        Returns:
            True if config was updated successfully, False otherwise
        """
        from backend.db.utils import get_db_session

        if db is not None:
            return self._apply(db, proposal_id)

        try:
            with get_db_session() as db:
                return self._apply(db, proposal_id)
        except Exception as e:
            self.logger.error(
                f"Failed to apply proposal {proposal_id}: {e}",
                exc_info=True
            )
            return False

    def _apply(self, db, proposal_id: int) -> bool:
        try:
            # Load proposal
            proposal = db.query(StrategyProposal).filter(
                StrategyProposal.id == proposal_id
            ).first()
            
            if not proposal:
                self.logger.error(f"Proposal {proposal_id} not found")
                return False
            
            if proposal.admin_decision != "approved":
                self.logger.error(
                    f"Proposal {proposal_id} not approved (status: {proposal.admin_decision})"
                )
                return False
            
            strategy_name = proposal.strategy_name
            change_details = proposal.change_details
            
            # Load current config
            config = db.query(StrategyConfig).filter(
                StrategyConfig.strategy_name == strategy_name
            ).first()
            
            if not config:
                self.logger.error(f"Strategy config not found for '{strategy_name}'")
                return False
            
            # Parse current params
            current_params = json.loads(config.params) if config.params else {}
            
            # Create snapshot before applying changes
            old_snapshot = {
                "strategy_name": config.strategy_name,
                "enabled": config.enabled,
                "interval_seconds": config.interval_seconds,
                "params": current_params.copy()
            }
            
            # Apply changes from proposal
            new_params = current_params.copy()
            for key, value in change_details.items():
                if key == "enabled":
                    config.enabled = value
                elif key == "interval_seconds":
                    config.interval_seconds = value
                else:
                    # Update params JSON
                    new_params[key] = value
            
            # Save updated params
            config.params = json.dumps(new_params)
            
            # Create new snapshot
            new_snapshot = {
                "strategy_name": config.strategy_name,
                "enabled": config.enabled,
                "interval_seconds": config.interval_seconds,
                "params": new_params
            }
            
            # Log config change to audit log
            audit_entry = AuditLog(
                timestamp=datetime.now(timezone.utc),
                event_type="CONFIG_UPDATED",
                entity_type="STRATEGY_CONFIG",
                entity_id=strategy_name,
                old_value=old_snapshot,
                new_value=new_snapshot,
                user_id=proposal.admin_user_id or "system",
                actor=proposal.admin_user_id or "system",
                action="apply_proposal",
                details={
                    "proposal_id": proposal_id,
                    "change_details": change_details,
                    "expected_impact": proposal.expected_impact
                }
            )
            db.add(audit_entry)
            
            # Commit changes
            db.commit()
            
            self.logger.info(
                f"Applied proposal {proposal_id} to strategy '{strategy_name}': {change_details}"
            )
            
            return True
            
        except Exception as e:
            db.rollback()
            self.logger.error(
                f"Failed to apply proposal {proposal_id}: {e}",
                exc_info=True
            )
            return False
    
    def get_active_config(
        self,
        strategy_name: str,
        db: Optional[Any] = None
    ) -> Optional[Dict[str, Any]]:
        """Get the current active config for a strategy.
        
        This is called by the strategy executor to read the latest config
        from the database before each execution cycle.
        
        Args:
            strategy_name: Name of the strategy
            db: Optional database session
        
        Returns:
            Config dict with enabled, interval_seconds, and params, or None
        """
        from backend.db.utils import get_db_session

        if db is not None:
            return self._get_config(db, strategy_name)

        try:
            with get_db_session() as db:
                return self._get_config(db, strategy_name)
        except Exception as e:
            self.logger.error(
                f"Failed to get config for '{strategy_name}': {e}",
                exc_info=True
            )
            return None

    def _get_config(self, db, strategy_name: str) -> Optional[Dict[str, Any]]:
        try:
            config = db.query(StrategyConfig).filter(
                StrategyConfig.strategy_name == strategy_name
            ).first()
            
            if not config:
                return None
            
            params = json.loads(config.params) if config.params else {}
            
            return {
                "strategy_name": config.strategy_name,
                "enabled": config.enabled,
                "interval_seconds": config.interval_seconds,
                "params": params
            }
        except Exception as e:
            self.logger.error(
                f"Failed to get config for '{strategy_name}': {e}",
                exc_info=True
            )
            return None
    
    def get_config_timeline(
        self,
        strategy_name: str,
        limit: int = 20,
        db: Optional[Any] = None
    ) -> list[Dict[str, Any]]:
        """Get the config change timeline for a strategy.
        
        Returns a list of config changes from the audit log, showing
        when proposals were applied and what changed.
        
        Args:
            strategy_name: Name of the strategy
            limit: Maximum number of changes to return
            db: Optional database session
        
        Returns:
            List of config change events with timestamps and details
        """
        from backend.db.utils import get_db_session

        if db is not None:
            return self._get_timeline(db, strategy_name, limit)

        try:
            with get_db_session() as db:
                return self._get_timeline(db, strategy_name, limit)
        except Exception as e:
            self.logger.error(
                f"Failed to get config timeline for '{strategy_name}': {e}",
                exc_info=True
            )
            return []

    def _get_timeline(self, db, strategy_name: str, limit: int) -> list[Dict[str, Any]]:
        try:
            changes = db.query(AuditLog).filter(
                AuditLog.event_type == "CONFIG_UPDATED",
                AuditLog.entity_id == strategy_name
            ).order_by(AuditLog.timestamp.desc()).limit(limit).all()
            
            timeline = []
            for change in changes:
                timeline.append({
                    "timestamp": change.timestamp.isoformat() if change.timestamp else None,
                    "user_id": change.user_id,
                    "old_value": change.old_value,
                    "new_value": change.new_value,
                    "details": change.details
                })
            
            return timeline
        except Exception as e:
            self.logger.error(
                f"Failed to get config timeline for '{strategy_name}': {e}",
                exc_info=True
            )
            return []


# Global instance for easy access
_applier_instance = None

def get_applier() -> ProposalApplier:
    """Get the global ProposalApplier instance."""
    global _applier_instance
    if _applier_instance is None:
        _applier_instance = ProposalApplier()
    return _applier_instance
