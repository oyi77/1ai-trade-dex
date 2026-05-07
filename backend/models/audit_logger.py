"""Audit logging helper functions for money-related operations."""

import logging
from datetime import datetime, timezone
from typing import Optional, Any, Dict

from sqlalchemy.orm import Session

from backend.models.database import AuditLog

logger = logging.getLogger(__name__)


def log_audit_event(
    db: Session,
    event_type: str,
    entity_type: str,
    entity_id: str,
    old_value: Optional[Dict[str, Any]] = None,
    new_value: Optional[Dict[str, Any]] = None,
    user_id: str = "system",
) -> Optional[AuditLog]:
    """
    Log an audit event for money-related operations.

    Args:
        db: SQLAlchemy session
        event_type: Type of event (TRADE_CREATED, SETTLEMENT_COMPLETED, POSITION_UPDATED, WALLET_RECONCILED)
        entity_type: Type of entity (TRADE, POSITION, WALLET, CONFIG)
        entity_id: Unique identifier for the entity
        old_value: Previous state (JSON-serializable dict)
        new_value: New state (JSON-serializable dict)
        user_id: User or system identifier (default: "system")

    Returns:
        AuditLog entry if successful, None if failed
    """
    try:
        entry = AuditLog(
            timestamp=datetime.now(timezone.utc),
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            old_value=old_value,
            new_value=new_value,
            user_id=user_id,
            # Legacy fields for backward compatibility
            actor=user_id,
            action=event_type,
            details={
                "entity_type": entity_type,
                "entity_id": entity_id,
                "old_value": old_value,
                "new_value": new_value,
            },
        )
        db.add(entry)
        db.flush()  # Don't commit here - let caller control transaction

        logger.debug(
            f"Audit log: {event_type} for {entity_type}:{entity_id} by {user_id}"
        )
        return entry

    except Exception as e:
        logger.error(f"Failed to create audit log entry: {e}", exc_info=True)
        return None


def log_trade_created(
    db: Session,
    trade_id: int,
    trade_data: Dict[str, Any],
    user_id: str = "system",
) -> Optional[AuditLog]:
    """
    Log trade creation event.

    Args:
        db: SQLAlchemy session
        trade_id: Trade ID
        trade_data: Trade details (market_ticker, direction, size, entry_price, etc.)
        user_id: User or strategy identifier

    Returns:
        AuditLog entry if successful
    """
    return log_audit_event(
        db=db,
        event_type="TRADE_CREATED",
        entity_type="TRADE",
        entity_id=str(trade_id),
        old_value=None,  # No previous state for new trades
        new_value=trade_data,
        user_id=user_id,
    )


def log_settlement_completed(
    db: Session,
    trade_id: int,
    old_state: Dict[str, Any],
    new_state: Dict[str, Any],
    user_id: str = "system",
) -> Optional[AuditLog]:
    """
    Log trade settlement event.

    Args:
        db: SQLAlchemy session
        trade_id: Trade ID
        old_state: Pre-settlement state (settled=False, pnl=None)
        new_state: Post-settlement state (settled=True, pnl=X, result=Y)
        user_id: User or system identifier

    Returns:
        AuditLog entry if successful
    """
    return log_audit_event(
        db=db,
        event_type="SETTLEMENT_COMPLETED",
        entity_type="TRADE",
        entity_id=str(trade_id),
        old_value=old_state,
        new_value=new_state,
        user_id=user_id,
    )


def log_position_updated(
    db: Session,
    position_id: str,
    old_state: Dict[str, Any],
    new_state: Dict[str, Any],
    user_id: str = "system",
) -> Optional[AuditLog]:
    """
    Log position update event (size changes, reconciliation).

    Args:
        db: SQLAlchemy session
        position_id: Position identifier (trade_id or market_ticker)
        old_state: Previous position state
        new_state: New position state
        user_id: User or system identifier

    Returns:
        AuditLog entry if successful
    """
    return log_audit_event(
        db=db,
        event_type="POSITION_UPDATED",
        entity_type="POSITION",
        entity_id=position_id,
        old_value=old_state,
        new_value=new_state,
        user_id=user_id,
    )


def log_wallet_reconciled(
    db: Session,
    wallet_address: str,
    reconciliation_data: Dict[str, Any],
    user_id: str = "system",
) -> Optional[AuditLog]:
    """
    Log wallet reconciliation event.

    Args:
        db: SQLAlchemy session
        wallet_address: Wallet address
        reconciliation_data: Reconciliation results (imported_count, updated_count, closed_count)
        user_id: User or system identifier

    Returns:
        AuditLog entry if successful
    """
    return log_audit_event(
        db=db,
        event_type="WALLET_RECONCILED",
        entity_type="WALLET",
        entity_id=wallet_address,
        old_value=None,  # No previous state for reconciliation events
        new_value=reconciliation_data,
        user_id=user_id,
    )
