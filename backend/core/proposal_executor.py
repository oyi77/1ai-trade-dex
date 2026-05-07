"""Proposal Executor Module - Wave 4e

Executes approved strategy proposals and measures their impact with auto-rollback.
Implements a learning loop that:
1. Executes approved proposals by applying config changes
2. Measures impact on recent trades (Sharpe ratio delta)
3. Auto-rolls back if impact is negative
4. Logs all execution and rollback events

This module integrates with:
- ProposalGenerator (Wave 4b) for proposal approval workflow
- ImpactMeasurer (Wave 4c) for measuring strategy performance
- StrategyConfig table for applying/reverting configuration changes
- APScheduler for periodic impact measurement and rollback checks
"""

import logging
import json
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass

from backend.models.database import (
    StrategyProposal,
    StrategyConfig,
    Trade,
    AuditLog
)

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result of proposal execution."""
    success: bool
    proposal_id: int
    message: str
    snapshot: Optional[Dict[str, Any]] = None


@dataclass
class ImpactResult:
    """Result of impact measurement."""
    sharpe_ratio_delta: float
    win_rate_delta: float
    pnl_delta: float
    trade_count: int
    measurement_window_hours: int


class ProposalExecutor:
    """Executes approved proposals and manages learning loop with auto-rollback."""
    
    # Auto-rollback threshold: if Sharpe ratio drops by more than this, rollback
    ROLLBACK_THRESHOLD = -0.1
    
    # Impact measurement window: analyze last N hours of trades
    IMPACT_WINDOW_HOURS = 48
    
    # Minimum trades required for impact measurement
    MIN_TRADES_FOR_IMPACT = 5
    
    def __init__(self):
        """Initialize the ProposalExecutor."""
        self.logger = logging.getLogger(__name__)
    
    def execute_proposal(self, proposal_id: int) -> bool:
        """Execute an approved proposal by applying config changes.
        
        This function:
        1. Validates proposal status is 'approved'
        2. Snapshots current strategy configs
        3. Applies proposal changes to strategy_config table
        4. Logs execution with old/new config
        5. Updates proposal status to 'executed'
        
        Args:
            proposal_id: Database ID of the proposal to execute
        
        Returns:
            True if execution succeeded, False otherwise
        """
        try:
            from backend.db.utils import get_db_session
            with get_db_session() as db:
                    proposal = db.query(StrategyProposal).filter(
                        StrategyProposal.id == proposal_id
                    ).first()
            
                    if not proposal:
                        self.logger.error(f"Proposal {proposal_id} not found")
                        return False
            
                    if proposal.admin_decision != "approved":
                        self.logger.error(
                            f"Proposal {proposal_id} status is '{proposal.admin_decision}', "
                            f"expected 'approved'"
                        )
                        return False
            
                    if proposal.executed_at is not None:
                        self.logger.warning(f"Proposal {proposal_id} already executed")
                        return False
            
                    strategy_name = proposal.strategy_name
                    change_details = proposal.change_details
            
                    # Step 2: Snapshot current config
                    current_config = db.query(StrategyConfig).filter(
                        StrategyConfig.strategy_name == strategy_name
                    ).first()
            
                    if not current_config:
                        self.logger.error(
                            f"Strategy config not found for '{strategy_name}'"
                        )
                        return False
            
                    # Create snapshot of old config
                    old_config_snapshot = {
                        "strategy_name": current_config.strategy_name,
                        "enabled": current_config.enabled,
                        "interval_seconds": current_config.interval_seconds,
                        "params": json.loads(current_config.params) if current_config.params else {}
                    }
            
                    self.logger.info(
                        f"Snapshotted config for '{strategy_name}': {old_config_snapshot}"
                    )
            
                    # Step 3: Apply changes from proposal
                    new_params = json.loads(current_config.params) if current_config.params else {}
            
                    # Merge change_details into params
                    for key, value in change_details.items():
                        new_params[key] = value
            
                    current_config.params = json.dumps(new_params)
            
                    # Create snapshot of new config
                    new_config_snapshot = {
                        "strategy_name": current_config.strategy_name,
                        "enabled": current_config.enabled,
                        "interval_seconds": current_config.interval_seconds,
                        "params": new_params
                    }
            
                    # Step 4: Log execution to audit log
                    audit_entry = AuditLog(
                        timestamp=datetime.now(timezone.utc),
                        event_type="PROPOSAL_EXECUTED",
                        entity_type="STRATEGY_CONFIG",
                        entity_id=str(proposal_id),
                        old_value=old_config_snapshot,
                        new_value=new_config_snapshot,
                        user_id=proposal.admin_user_id or "system",
                        actor=proposal.admin_user_id or "system",
                        action="execute_proposal",
                        details={
                            "proposal_id": proposal_id,
                            "strategy_name": strategy_name,
                            "expected_impact": proposal.expected_impact
                        }
                    )
                    db.add(audit_entry)
            
                    # Step 5: Update proposal status
                    proposal.admin_decision = "executed"
                    proposal.executed_at = datetime.now(timezone.utc)
            
                    # Commit all changes atomically
                    db.commit()
            
                    self.logger.info(
                        f"Successfully executed proposal {proposal_id} for strategy '{strategy_name}'"
                    )
            
                    return True
        except Exception as e:
            db.rollback()
            self.logger.error(f"Failed to execute proposal {proposal_id}: {e}", exc_info=True)
            return False
    
    def measure_impact(self, proposal_id: int) -> Optional[ImpactResult]:
        """Measure the impact of an executed proposal on recent trades.
        
        Analyzes trades from the last IMPACT_WINDOW_HOURS and compares:
        - Sharpe ratio before vs after execution
        - Win rate before vs after
        - Average PnL before vs after
        
        Args:
            proposal_id: Database ID of the executed proposal
        
        Returns:
            ImpactResult with deltas, or None if measurement fails
        """
        try:
            from backend.db.utils import get_db_session
            with get_db_session() as db:
                    proposal = db.query(StrategyProposal).filter(
                        StrategyProposal.id == proposal_id
                    ).first()
            
                    if not proposal:
                        self.logger.error(f"Proposal {proposal_id} not found")
                        return None
            
                    if proposal.admin_decision != "executed":
                        self.logger.warning(
                            f"Proposal {proposal_id} not executed, cannot measure impact"
                        )
                        return None
            
                    if not proposal.executed_at:
                        self.logger.error(f"Proposal {proposal_id} missing executed_at timestamp")
                        return None
            
                    strategy_name = proposal.strategy_name
                    execution_time = proposal.executed_at
            
                    # Define time windows
                    window_start = execution_time - timedelta(hours=self.IMPACT_WINDOW_HOURS)
                    window_end = datetime.now(timezone.utc)
            
                    # Get trades before execution
                    trades_before = db.query(Trade).filter(
                        Trade.strategy == strategy_name,
                        Trade.timestamp >= window_start,
                        Trade.timestamp < execution_time,
                        Trade.pnl.isnot(None)
                    ).all()
            
                    # Get trades after execution
                    trades_after = db.query(Trade).filter(
                        Trade.strategy == strategy_name,
                        Trade.timestamp >= execution_time,
                        Trade.timestamp <= window_end,
                        Trade.pnl.isnot(None)
                    ).all()
            
                    # Check minimum trade count
                    if len(trades_after) < self.MIN_TRADES_FOR_IMPACT:
                        self.logger.info(
                            f"Not enough trades after execution ({len(trades_after)} < {self.MIN_TRADES_FOR_IMPACT}), "
                            f"skipping impact measurement"
                        )
                        return None
            
                    # Calculate metrics before
                    sharpe_before = self._calculate_sharpe_ratio(trades_before)
                    win_rate_before = self._calculate_win_rate(trades_before)
                    avg_pnl_before = self._calculate_avg_pnl(trades_before)
            
                    # Calculate metrics after
                    sharpe_after = self._calculate_sharpe_ratio(trades_after)
                    win_rate_after = self._calculate_win_rate(trades_after)
                    avg_pnl_after = self._calculate_avg_pnl(trades_after)
            
                    # Calculate deltas
                    sharpe_delta = sharpe_after - sharpe_before
                    win_rate_delta = win_rate_after - win_rate_before
                    pnl_delta = avg_pnl_after - avg_pnl_before
            
                    result = ImpactResult(
                        sharpe_ratio_delta=sharpe_delta,
                        win_rate_delta=win_rate_delta,
                        pnl_delta=pnl_delta,
                        trade_count=len(trades_after),
                        measurement_window_hours=self.IMPACT_WINDOW_HOURS
                    )
            
                    # Store impact measurement in proposal
                    proposal.impact_measured = {
                        "sharpe_ratio_delta": sharpe_delta,
                        "win_rate_delta": win_rate_delta,
                        "pnl_delta": pnl_delta,
                        "trade_count_after": len(trades_after),
                        "trade_count_before": len(trades_before),
                        "measured_at": datetime.now(timezone.utc).isoformat()
                    }
                    db.commit()
            
                    self.logger.info(
                        f"Impact measured for proposal {proposal_id}: "
                        f"Sharpe Δ={sharpe_delta:.3f}, Win Rate Δ={win_rate_delta:.3f}, "
                        f"PnL Δ=${pnl_delta:.2f}"
                    )
            
                    return result
        except Exception as e:
            self.logger.error(f"Failed to measure impact for proposal {proposal_id}: {e}", exc_info=True)
            return None
    
    def auto_rollback_if_negative(self, proposal_id: int) -> bool:
        """Check impact and auto-rollback if negative.
        
        If the Sharpe ratio delta is below ROLLBACK_THRESHOLD, this function:
        1. Restores the strategy config from the audit log snapshot
        2. Logs the rollback event
        3. Updates proposal status to 'rolled_back'
        4. Notifies admin (via log)
        
        Args:
            proposal_id: Database ID of the executed proposal
        
        Returns:
            True if rollback was performed, False otherwise
        """
        try:
            from backend.db.utils import get_db_session
            with get_db_session() as db:
                    impact = self.measure_impact(proposal_id)
            
                    if impact is None:
                        self.logger.debug(f"No impact measurement available for proposal {proposal_id}")
                        return False
            
                    # Check if rollback is needed
                    if impact.sharpe_ratio_delta >= self.ROLLBACK_THRESHOLD:
                        self.logger.info(
                            f"Proposal {proposal_id} impact is positive "
                            f"(Sharpe Δ={impact.sharpe_ratio_delta:.3f}), no rollback needed"
                        )
                        return False
            
                    # Impact is negative, perform rollback
                    self.logger.warning(
                        f"Proposal {proposal_id} impact is negative "
                        f"(Sharpe Δ={impact.sharpe_ratio_delta:.3f} < {self.ROLLBACK_THRESHOLD}), "
                        f"initiating auto-rollback"
                    )
            
                    # Load proposal
                    proposal = db.query(StrategyProposal).filter(
                        StrategyProposal.id == proposal_id
                    ).first()
            
                    if not proposal:
                        self.logger.error(f"Proposal {proposal_id} not found")
                        return False
            
                    strategy_name = proposal.strategy_name
            
                    # Find the execution audit log entry to get old config
                    audit_entry = db.query(AuditLog).filter(
                        AuditLog.event_type == "PROPOSAL_EXECUTED",
                        AuditLog.entity_id == str(proposal_id)
                    ).order_by(AuditLog.timestamp.desc()).first()
            
                    if not audit_entry or not audit_entry.old_value:
                        self.logger.error(
                            f"Cannot rollback proposal {proposal_id}: no audit log snapshot found"
                        )
                        return False
            
                    old_config_snapshot = audit_entry.old_value
            
                    # Restore old config
                    current_config = db.query(StrategyConfig).filter(
                        StrategyConfig.strategy_name == strategy_name
                    ).first()
            
                    if not current_config:
                        self.logger.error(f"Strategy config not found for '{strategy_name}'")
                        return False
            
                    # Restore params from snapshot
                    current_config.params = json.dumps(old_config_snapshot.get("params", {}))
            
                    # Log rollback to audit log
                    rollback_entry = AuditLog(
                        timestamp=datetime.now(timezone.utc),
                        event_type="PROPOSAL_ROLLED_BACK",
                        entity_type="STRATEGY_CONFIG",
                        entity_id=str(proposal_id),
                        old_value=audit_entry.new_value,  # Current (bad) config
                        new_value=old_config_snapshot,    # Restored (old) config
                        user_id="system",
                        actor="system",
                        action="auto_rollback",
                        details={
                            "proposal_id": proposal_id,
                            "strategy_name": strategy_name,
                            "reason": f"Impact below threshold (Sharpe Δ={impact.sharpe_ratio_delta:.3f})",
                            "sharpe_ratio_delta": impact.sharpe_ratio_delta,
                            "win_rate_delta": impact.win_rate_delta,
                            "pnl_delta": impact.pnl_delta
                        }
                    )
                    db.add(rollback_entry)
            
                    # Update proposal status
                    proposal.admin_decision = "rolled_back"
            
                    # Commit changes
                    db.commit()
            
                    self.logger.warning(
                        f"Successfully rolled back proposal {proposal_id} for strategy '{strategy_name}' "
                        f"due to negative impact (Sharpe Δ={impact.sharpe_ratio_delta:.3f})"
                    )
            
                    # Notify admin (log only, no external alerts in this implementation)
                    self.logger.warning(
                        f"ADMIN NOTIFICATION: Proposal {proposal_id} auto-rolled back. "
                        f"Strategy '{strategy_name}' restored to previous config."
                    )
            
                    return True
        except Exception as e:
            db.rollback()
            self.logger.error(f"Failed to rollback proposal {proposal_id}: {e}", exc_info=True)
            return False
    
    def get_executed_proposals(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recently executed proposals for impact monitoring.
        
        Args:
            limit: Maximum number of proposals to return
        
        Returns:
            List of proposal dictionaries with execution details
        """
        from backend.db.utils import get_db_session
        with get_db_session() as db:
                proposals = db.query(StrategyProposal).filter(
                    StrategyProposal.admin_decision == "executed"
                ).order_by(StrategyProposal.executed_at.desc()).limit(limit).all()
            
                result = []
                for p in proposals:
                    result.append({
                        "id": p.id,
                        "strategy_name": p.strategy_name,
                        "change_details": p.change_details,
                        "expected_impact": p.expected_impact,
                        "executed_at": p.executed_at.isoformat() if p.executed_at else None,
                        "impact_measured": p.impact_measured,
                        "admin_user_id": p.admin_user_id
                    })
            
                return result
    
    def _calculate_sharpe_ratio(self, trades: List[Trade]) -> float:
        """Calculate Sharpe ratio from trades.
        
        Args:
            trades: List of Trade ORM objects
        
        Returns:
            Sharpe ratio (annualized)
        """
        if not trades:
            return 0.0
        
        import numpy as np
        
        pnls = [t.pnl for t in trades if t.pnl is not None]
        
        if len(pnls) < 2:
            return 0.0
        
        mean_pnl = np.mean(pnls)
        std_pnl = np.std(pnls)
        
        if std_pnl == 0:
            return 0.0
        
        # Annualize: assume ~250 trading days per year
        sharpe = (mean_pnl / std_pnl) * np.sqrt(250)
        
        return float(sharpe)
    
    def _calculate_win_rate(self, trades: List[Trade]) -> float:
        """Calculate win rate from trades.
        
        Args:
            trades: List of Trade ORM objects
        
        Returns:
            Win rate (0.0-1.0)
        """
        if not trades:
            return 0.0
        
        winning_trades = sum(1 for t in trades if t.pnl and t.pnl > 0)
        total_trades = len(trades)
        
        return winning_trades / total_trades if total_trades > 0 else 0.0
    
    def _calculate_avg_pnl(self, trades: List[Trade]) -> float:
        """Calculate average PnL from trades.
        
        Args:
            trades: List of Trade ORM objects
        
        Returns:
            Average PnL per trade
        """
        if not trades:
            return 0.0
        
        total_pnl = sum(t.pnl for t in trades if t.pnl is not None)
        return total_pnl / len(trades)


# Scheduled job functions for APScheduler integration

async def execute_approved_proposals_job():
    """Background job: Execute all approved proposals.
    
    This job runs periodically (e.g., every 30 minutes) and executes
    any proposals that have been approved but not yet executed.
    """
    executor = ProposalExecutor()
    try:
        from backend.db.utils import get_db_session
        with get_db_session() as db:
                approved_proposals = db.query(StrategyProposal).filter(
                    StrategyProposal.admin_decision == "approved",
                    StrategyProposal.executed_at.is_(None)
                ).all()
        
                if not approved_proposals:
                    logger.debug("No approved proposals to execute")
                    return
        
                proposal_ids = [p.id for p in approved_proposals]
                logger.info(f"Found {len(proposal_ids)} approved proposals to execute")
        
                for proposal_id in proposal_ids:
                    success = executor.execute_proposal(proposal_id)
                    if success:
                        logger.info(f"Executed proposal {proposal_id}")
                    else:
                        logger.error(f"Failed to execute proposal {proposal_id}")
    except Exception as e:
        logger.error(f"Error in execute_approved_proposals_job: {e}", exc_info=True)


async def measure_impact_and_rollback_job():
    """Background job: Measure impact and auto-rollback if negative.
    
    This job runs every 2 hours and:
    1. Measures impact of recently executed proposals
    2. Auto-rolls back proposals with negative impact
    """
    executor = ProposalExecutor()
    
    try:
        # Get recently executed proposals (last 20)
        executed_proposals = executor.get_executed_proposals(limit=20)
        
        if not executed_proposals:
            logger.debug("No executed proposals to measure")
            return
        
        logger.info(f"Measuring impact for {len(executed_proposals)} executed proposals")
        
        rollback_count = 0
        for proposal in executed_proposals:
            proposal_id = proposal["id"]
            
            # Check if already rolled back
            if proposal.get("admin_decision") == "rolled_back":
                continue
            
            # Attempt auto-rollback if impact is negative
            rolled_back = executor.auto_rollback_if_negative(proposal_id)
            if rolled_back:
                rollback_count += 1
        
        if rollback_count > 0:
            logger.warning(f"Auto-rolled back {rollback_count} proposals due to negative impact")
        else:
            logger.info("No proposals required rollback")
        
    except Exception as e:
        logger.error(f"Error in measure_impact_and_rollback_job: {e}", exc_info=True)
