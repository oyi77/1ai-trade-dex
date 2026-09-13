"""
DEPRECATED: Use backend.core.wallet_reconciliation instead.
This module will be removed in a future release.

Wallet reconciliation module for blockchain sync.

Orchestrates wallet reconciliation strategy, position comparison, trade imports,
and orphan detection. Called by background sync jobs.

Key responsibilities:
- Import historical trades from Polymarket Data API
- Sync current open positions from CLOB API
- Detect orphaned positions (on-chain but missing from DB)
- Close orphaned positions with metadata tracking
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from backend.data.polymarket_clob import PolymarketCLOB
from backend.models.database import Trade
from backend.core.alert_manager import AlertManager
from backend.config import settings

from loguru import logger



from backend.core.wallet._wallet_reconciliation_types import (
    PositionComparison,
    OrphanedPosition,
    SyncResult,
)
from backend.core.wallet._wallet_reconciliation_history import WalletReconcilerHistoryMixin
from backend.core.wallet._wallet_reconciliation_positions import WalletReconcilerPositionsMixin


class WalletReconciler(WalletReconcilerHistoryMixin, WalletReconcilerPositionsMixin):
    """Reconcile blockchain state with local database."""

    def __init__(self, clob_client: PolymarketCLOB, db: Session, mode: str):
        self.clob = clob_client
        self.db = db
        self.mode = mode
        self.alert_manager = AlertManager(db)

        if self.clob.builder_address:
            self.wallet_address = self.clob.builder_address
        elif hasattr(self.clob, "_account") and self.clob._account:
            self.wallet_address = self.clob._account.address
        else:
            raise ValueError(
                "Cannot determine wallet address from CLOB client. "
                "Ensure POLYMARKET_BUILDER_ADDRESS is set or client is initialized with private_key."
            )

        self.logger = logger
        self.logger.info(f"Initialized reconciler for wallet {self.wallet_address}")

    async def full_reconciliation(self) -> SyncResult:

        """
        Complete wallet reconciliation cycle.

        Steps:
        1. Import blockchain history (all trades ever)
        2. Sync current positions (open orders)
        3. Detect orphaned positions (on-chain but missing locally)
        4. Close orphaned positions

        Returns:
            SyncResult with metrics (imported, updated, closed counts)
        """
        result = SyncResult()

        try:
            self.logger.info("Starting full reconciliation cycle")
            imported = await self.import_blockchain_history(max_pages=None)

            # 1b. Import REDEEM records from activity API (captures winning trades
            #     that disappeared from /positions after full redemption)
            activity_imported = await self.import_activity_redeems()
            imported += activity_imported
            result.imported_count = imported

            position_result = await self.sync_current_positions()
            result.updated_count = position_result.updated_count
            result.closed_count = position_result.closed_count
            result.errors.extend(position_result.errors)

            orphans = await self.detect_orphaned_positions()
            for orphan in orphans:
                try:
                    closed = await self.close_orphaned_position(orphan)
                    if closed:
                        result.closed_count += 1
                except Exception as e:
                    error_msg = f"Failed to close orphan {orphan.market_id}: {e}"
                    self.logger.error(error_msg, exc_info=True)
                    result.errors.append(error_msg)

            result.last_sync_at = datetime.now(timezone.utc)
            self.logger.info(
                f"Reconciliation complete: imported={result.imported_count}, "
                f"updated={result.updated_count}, closed={result.closed_count}, "
                f"errors={len(result.errors)}"
            )

        except Exception as e:
            error_msg = f"Reconciliation failed: {e}"
            self.logger.error(error_msg, exc_info=True)
            result.errors.append(error_msg)

        return result

    def _resolve_strategy_for_position(self, market_ticker: str) -> Optional[str]:
        """Try to attribute an orphaned position to a known strategy.

        Checks DecisionLog and existing bot trades for the same market_ticker
        to recover strategy attribution lost during blockchain reconciliation.
        """
        from backend.models.database import DecisionLog

        decision = (
            self.db.query(DecisionLog)
            .filter(DecisionLog.market_ticker == market_ticker)
            .order_by(DecisionLog.created_at.desc())
            .first()
        )
        if decision and decision.strategy:
            return decision.strategy

        bot_trade = (
            self.db.query(Trade)
            .filter(
                Trade.market_ticker == market_ticker,
                Trade.source == "bot",
                Trade.strategy.isnot(None),
            )
            .first()
        )
        if bot_trade and bot_trade.strategy:
            return bot_trade.strategy

        return None

