"""
Wallet reconciliation module for blockchain sync.

Orchestrates wallet reconciliation strategy, position comparison, trade imports,
and orphan detection. Called by background sync jobs.

Key responsibilities:
- Import historical trades from Polymarket Data API
- Sync current open positions from CLOB API
- Detect orphaned positions (on-chain but missing from DB)
- Close orphaned positions with metadata tracking
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from backend.data.polymarket_clob import PolymarketCLOB
from backend.models.database import Trade
from backend.core.alert_manager import AlertManager
from backend.config import settings

logger = logging.getLogger("wallet_reconciler")


@dataclass
class PositionComparison:
    """Result of comparing blockchain vs DB position."""
    market_id: str
    db_status: str  # "open" | "closed" | "missing"
    blockchain_status: str
    db_size: float
    blockchain_size: float
    discrepancy: bool


@dataclass
class OrphanedPosition:
    """Position on blockchain but missing from DB."""
    market_id: str
    blockchain_size: float
    blockchain_entry_price: float
    clob_order_id: Optional[str] = None
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class SyncResult:
    """Reconciliation cycle result."""
    imported_count: int = 0
    updated_count: int = 0
    closed_count: int = 0
    errors: list[str] = field(default_factory=list)
    last_sync_at: Optional[datetime] = None


class WalletReconciler:
    """Reconcile blockchain state with local database."""

    def __init__(self, clob_client: PolymarketCLOB, db: Session, mode: str):
        """
        Initialize wallet reconciler.

        Args:
            clob_client: PolymarketCLOB instance for API calls
            db: SQLAlchemy session
            mode: Trading mode ("live" | "testnet")
        """
        self.clob = clob_client
        self.db = db
        self.mode = mode
        self.alert_manager = AlertManager(db)

        # Determine wallet address from CLOB client
        if self.clob.builder_address:
            self.wallet_address = self.clob.builder_address
        elif hasattr(self.clob, '_account') and self.clob._account:
            self.wallet_address = self.clob._account.address
        else:
            raise ValueError(
                "Cannot determine wallet address from CLOB client. "
                "Ensure POLYMARKET_BUILDER_ADDRESS is set or client is initialized with private_key."
            )

        self.logger = logging.getLogger(f"wallet_reconciler[{mode}]")
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
            # 1. Import historical trades from blockchain
            self.logger.info("Starting full reconciliation cycle")
            imported = await self.import_blockchain_history(max_pages=None)

            # 1b. Import REDEEM records from activity API (captures winning trades
            #     that disappeared from /positions after full redemption)
            activity_imported = await self.import_activity_redeems()
            imported += activity_imported
            result.imported_count = imported

            # 2. Sync current open positions
            position_result = await self.sync_current_positions()
            result.updated_count = position_result.updated_count
            result.closed_count = position_result.closed_count
            result.errors.extend(position_result.errors)

            # 3. Check for orphaned positions
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

            # 4. Update timestamps
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

    async def import_blockchain_history(self, max_pages: Optional[int] = None) -> int:
        """
        Download ALL historical trades from blockchain via Data API.

        Fetches from https://data-api.polymarket.com/positions?user={wallet_address}.
        Imports trades with source='external' if they don't exist locally.
        Deduplicates by market_ticker and timestamp.

        Args:
            max_pages: Unused (Data API returns all positions in one call)

        Returns:
            Count of newly imported trades
        """
        if not self.wallet_address:
            self.logger.warning("Wallet address is empty, skipping blockchain history import")
            return 0

        self.logger.info(f"Importing blockchain history for {self.wallet_address}")

        try:
            # Fetch positions from Data API
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    settings.DATA_API_URL + "/positions",
                    params={"user": self.wallet_address}
                )
                response.raise_for_status()
                positions = response.json()

            self.logger.info(f"Downloaded {len(positions)} positions from Data API")

            imported = 0
            for pos in positions:
                # Import both open and redeemable (settled) positions
                _is_redeemable = pos.get("redeemable", False)

                # Use asset (token_id) as market_ticker (enables CLOB API midpoint lookup)
                market_slug = pos["asset"]
                size = pos["initialValue"]
                avg_price = pos["avgPrice"]
                outcome = pos["outcome"]

                existing = self.db.query(Trade).filter(
                    Trade.market_ticker == market_slug
                ).first()

                if existing:
                    if abs(existing.size - size) > 0.01:
                        from backend.models.audit_logger import log_position_updated
                        old_size = existing.size
                        self.logger.info(
                            f"Updating position size for {market_slug}: "
                            f"{existing.size} -> {size}"
                        )
                        existing.size = size
                        existing.last_sync_at = datetime.now(timezone.utc)
                        log_position_updated(
                            db=self.db,
                            position_id=f"{market_slug}:{existing.id}",
                            old_state={"size": old_size, "last_sync_at": None},
                            new_state={"size": size, "last_sync_at": existing.last_sync_at.isoformat()},
                            user_id="system:reconciliation",
                        )
                    else:
                        self.logger.debug(f"Trade {market_slug} already in DB (id={existing.id})")
                    continue

                new_trade = Trade(
                    market_ticker=market_slug,
                    platform="polymarket",
                    direction="up" if outcome == "Yes" else "down",
                    entry_price=avg_price,
                    size=size,
                    timestamp=datetime.now(timezone.utc),
                    trading_mode=self.mode,
                    settled=False,
                    result=None,
                    source="external",
                    strategy=self._resolve_strategy_for_position(market_slug) or "wallet_import",
                    blockchain_verified=True,
                    settlement_source=None,
                    external_import_at=datetime.now(timezone.utc),
                    model_probability=0.5,
                    market_price_at_entry=avg_price,
                    edge_at_entry=0.0,
                )

                self.db.add(new_trade)
                imported += 1
                self.logger.info(
                    f"Imported orphaned position: {market_slug} "
                    f"({outcome} @ {avg_price}, {size} shares)"
                )

            self.db.commit()

            from backend.models.audit_logger import log_wallet_reconciled
            log_wallet_reconciled(
                db=self.db,
                wallet_address=self.wallet_address,
                reconciliation_data={
                    "operation": "import_blockchain_history",
                    "imported_count": imported,
                    "total_positions": len(positions),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
                user_id="system:reconciliation",
            )
            self.db.commit()

            self.logger.info(f"Imported {imported} new trades from blockchain")

            return imported

        except Exception as e:
            self.logger.error(f"Failed to import blockchain history: {e}", exc_info=True)
            self.db.rollback()
            raise

    async def import_activity_redeems(self) -> int:
        """
        Import REDEEM records from the activity API.

        The /positions endpoint only returns current/recent positions. Once a
        winning position is fully redeemed, it disappears from /positions. The
        /activity endpoint's REDEEM records are the only way to recover these
        trades and ensure accurate P&L.
        """
        if not self.wallet_address:
            self.logger.warning("Wallet address is empty, skipping REDEEM activity import")
            return 0

        self.logger.info(f"Importing REDEEM activity for {self.wallet_address}")

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    settings.DATA_API_URL + "/activity",
                    params={"user": self.wallet_address, "limit": 200},
                )
                response.raise_for_status()
                activities = response.json()

            redeem_records = [a for a in activities if a.get("type") == "REDEEM"]
            self.logger.info(
                f"Found {len(redeem_records)} REDEEM records in activity API"
            )

            imported = 0
            for record in redeem_records:
                condition_id = record.get("conditionId", "")
                title = record.get("title", "")
                redeem_amount = float(record.get("usdcSize", 0))
                _tx_hash = record.get("transactionHash", "")
                timestamp_unix = record.get("timestamp", 0)

                if not condition_id:
                    continue

                slug = record.get("slug", "")
                _event_slug = record.get("eventSlug", "")

                existing = None
                if slug:
                    slug_prefix = slug[:min(len(slug), 40)]
                    matching_trades = self.db.query(Trade).filter(
                        (Trade.market_ticker.contains(slug_prefix)) &
                        (Trade.trading_mode == self.mode)
                    ).all()
                    if len(matching_trades) == 1:
                        existing = matching_trades[0]
                    elif len(matching_trades) > 1 and condition_id:
                        for mt in matching_trades:
                            market_ticker = mt.market_ticker or ""
                            if slug in market_ticker or market_ticker in slug:
                                existing = mt
                                break

                if existing is None and title:
                    title_prefix = title[:min(len(title), 30)]
                    matching_trades = self.db.query(Trade).filter(
                        (Trade.market_ticker.contains(title_prefix)) &
                        (Trade.trading_mode == self.mode)
                    ).all()
                    if len(matching_trades) == 1:
                        existing = matching_trades[0]
                    elif len(matching_trades) > 1 and condition_id:
                        for mt in matching_trades:
                            market_ticker = mt.market_ticker or ""
                            if title in market_ticker or market_ticker in title:
                                existing = mt
                                break

                if existing is None and condition_id:
                    token_id_trades = self.db.query(Trade).filter(
                        (Trade.market_ticker.contains(condition_id[:32])) &
                        (Trade.trading_mode == self.mode)
                    ).all()
                    if len(token_id_trades) == 1:
                        existing = token_id_trades[0]

                if existing:
                    if not existing.settled:
                        existing.settled = True
                        # We will set result below after PnL is calculated
                        existing.settlement_source = "activity_api_redeem"
                        existing.blockchain_verified = True
                        if existing.size and existing.size > 0 and existing.entry_price:
                            dollar_cost = existing.size * existing.entry_price
                            existing.pnl = redeem_amount - dollar_cost
                            if existing.pnl > 0:
                                existing.result = "win"
                            elif existing.pnl < 0:
                                existing.result = "loss"
                            else:
                                existing.result = "push"
                        else:
                            existing.result = "closed"
                        existing.settlement_time = (
                            datetime.fromtimestamp(timestamp_unix, tz=timezone.utc)
                            if timestamp_unix else datetime.now(timezone.utc)
                        )
                        imported += 1
                        self.logger.info(
                            f"Marked as redeemed from activity: {existing.market_ticker} "
                            f"(amount={redeem_amount})"
                        )
                    continue

                if redeem_amount > 0:
                    self.logger.debug(
                        f"REDEEM for unmatched position: {title} "
                        f"(conditionId={condition_id[:16]}..., amount={redeem_amount})"
                    )

            self.db.commit()
            self.logger.info(f"Updated {imported} trades from REDEEM activity records")
            return imported

        except Exception as e:
            self.logger.error(f"Failed to import activity redeems: {e}", exc_info=True)
            self.db.rollback()
            return 0

    async def sync_current_positions(self) -> SyncResult:
        """
        Fetch current open positions from blockchain.

        Compares with DB. Marks positions as closed if blockchain says they're gone.
        Updates last_sync_at timestamps for positions still open.

        Returns:
            SyncResult with updated/closed counts
        """
        self.logger.info("Syncing current positions from blockchain")

        result = SyncResult()

        try:
            # Fetch open positions from Data API
            blockchain_positions = await self._fetch_open_positions()

            # Build map of blockchain positions by asset (token_id)
            blockchain_map = {
                pos["asset"]: pos
                for pos in blockchain_positions
            }

            self.logger.debug(f"Blockchain has {len(blockchain_map)} open positions")

            # Query DB for open trades
            db_open_trades = self.db.query(Trade).filter(
                (Trade.trading_mode == self.mode) &
                (Trade.settlement_time.is_(None)) &  # Still open
                (~Trade.settled)
            ).all()

            self.logger.debug(f"DB has {len(db_open_trades)} open trades")

            # Compare
            for db_trade in db_open_trades:
                if db_trade.market_ticker not in blockchain_map:
                    from backend.core.settlement_helpers import (
                        fetch_resolution_for_trade,
                        calculate_pnl,
                    )

                    try:
                        is_resolved, settlement_value = await fetch_resolution_for_trade(db_trade)
                    except Exception as exc:
                        self.logger.warning(
                            f"Resolution lookup failed for trade {db_trade.id} "
                            f"({db_trade.market_ticker}): {exc}. Leaving open."
                        )
                        continue

                    if not is_resolved or settlement_value is None:
                        self.logger.warning(
                            f"Position {db_trade.market_ticker} (id={db_trade.id}) "
                            f"closed on-chain but resolution unknown. Leaving open for retry."
                        )
                        continue

                    pnl = calculate_pnl(db_trade, settlement_value)
                    now = datetime.now(timezone.utc)
                    db_trade.settled = True
                    db_trade.settlement_value = settlement_value
                    db_trade.pnl = pnl
                    db_trade.settlement_time = now
                    db_trade.settled_at = now
                    db_trade.settlement_source = "data_api"
                    db_trade.blockchain_verified = True
                    if pnl is not None and pnl > 0:
                        db_trade.result = "win"
                    elif pnl is not None and pnl < 0:
                        db_trade.result = "loss"
                    else:
                        db_trade.result = "push"
                    self.logger.info(
                        f"Position {db_trade.market_ticker} (id={db_trade.id}) "
                        f"closed via reconciliation: settlement={settlement_value} pnl=${pnl:+.2f}"
                    )
                    result.closed_count += 1
                else:
                    # Position still open - check for discrepancies
                    blockchain_pos = blockchain_map[db_trade.market_ticker]
                    blockchain_size = blockchain_pos.get("initialValue", 0.0)
                    db_size = db_trade.size or 0.0

                    self.alert_manager.check_position_discrepancy(
                        position_id=db_trade.market_ticker,
                        db_value=db_size,
                        blockchain_value=blockchain_size,
                        mode=self.mode,
                    )

                    db_trade.last_sync_at = datetime.now(timezone.utc)
                    db_trade.blockchain_verified = True
                    result.updated_count += 1
                    self.logger.debug(
                        f"Position {db_trade.market_ticker} (id={db_trade.id}) "
                        f"still open, updated sync timestamp"
                    )

            self.db.commit()

            from backend.models.audit_logger import log_wallet_reconciled
            log_wallet_reconciled(
                db=self.db,
                wallet_address=self.wallet_address,
                reconciliation_data={
                    "operation": "sync_current_positions",
                    "updated_count": result.updated_count,
                    "closed_count": result.closed_count,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
                user_id="system:reconciliation",
            )
            self.db.commit()

            self.logger.info(
                f"Position sync: {result.updated_count} updated, {result.closed_count} closed"
            )

        except Exception as e:
            error_msg = f"Failed to sync current positions: {e}"
            self.logger.error(error_msg, exc_info=True)
            result.errors.append(error_msg)
            self.db.rollback()

        return result

    async def detect_orphaned_positions(self) -> list[OrphanedPosition]:
        """
        Find positions on blockchain that don't exist in DB.

        These are trades placed by bot but DB record was lost (or external trades).

        Returns:
            List of OrphanedPosition objects
        """
        self.logger.info("Detecting orphaned positions")

        try:
            blockchain_positions = await self._fetch_open_positions()

            orphans = []
            for pos in blockchain_positions:
                # Check if trade exists in DB
                existing = self.db.query(Trade).filter(
                    (Trade.market_ticker == pos["asset"]) &
                    (~Trade.settled)
                ).first()

                if existing:
                    continue  # Found in DB

                # Orphaned!
                orphan = OrphanedPosition(
                    market_id=pos["asset"],
                    blockchain_size=pos["initialValue"],
                    blockchain_entry_price=pos["avgPrice"],
                    detected_at=datetime.now(timezone.utc)
                )
                orphans.append(orphan)
                self.logger.warning(
                    f"Orphaned position detected: {orphan.market_id} "
                    f"({orphan.blockchain_size} shares @ {orphan.blockchain_entry_price})"
                )

            self.logger.info(f"Found {len(orphans)} orphaned positions")
            return orphans

        except Exception as e:
            self.logger.error(f"Failed to detect orphaned positions: {e}", exc_info=True)
            return []

    async def close_orphaned_position(self, orphan: OrphanedPosition) -> bool:
        """
        Create a Trade record for orphaned position so it's tracked.

        Sets source='orphaned' and blockchain_verified=True.

        Args:
            orphan: OrphanedPosition to create DB record for

        Returns:
            True if successfully created, False if already exists
        """
        self.logger.info(f"Creating DB record for orphaned position: {orphan.market_id}")

        try:
            # Check again if it exists (race condition)
            existing = self.db.query(Trade).filter(
                Trade.market_ticker == orphan.market_id
            ).first()

            if existing:
                self.logger.debug(f"Orphan {orphan.market_id} already has DB record (id={existing.id})")
                return False

            # Create trade record
            trade = Trade(
                market_ticker=orphan.market_id,
                platform="polymarket",
                direction="up",  # Default to "up" - we don't know actual direction from position alone
                entry_price=orphan.blockchain_entry_price,
                size=orphan.blockchain_size,
                timestamp=orphan.detected_at,
                trading_mode=self.mode,

                # Reconciliation fields (Task 1)
                source="orphaned",                    # Position found on-chain, reconstructed
                strategy="wallet_import",
                clob_order_id=orphan.clob_order_id,
                blockchain_verified=True,
                settlement_source="clob_api",
                external_import_at=orphan.detected_at,

                # Default values for required fields
                model_probability=0.5,  # Unknown for orphaned positions
                market_price_at_entry=orphan.blockchain_entry_price,
                edge_at_entry=0.0,  # Unknown for orphaned positions
            )

            self.db.add(trade)
            self.db.commit()

            self.logger.info(f"Created orphaned position record: id={trade.id}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to close orphaned position: {e}", exc_info=True)
            self.db.rollback()
            return False

    async def _fetch_open_positions(self) -> list[dict]:
        """
        Fetch trader's current open positions from Data API.

        Called by sync_current_positions() and detect_orphaned_positions().

        Returns:
            List of position dicts with structure:
            [
                {
                    "slug": "btc-up-5m",
                    "size": 100.5,
                    "avgPrice": 0.42,
                    "outcome": "YES",
                    "initialValue": 42.21,
                },
                ...
            ]
        """
        if not self.wallet_address:
            self.logger.warning("Wallet address is empty, skipping open positions fetch")
            return []

        self.logger.info(f"Fetching open positions for {self.wallet_address}")

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    settings.DATA_API_URL + "/positions",
                    params={"user": self.wallet_address}
                )
                response.raise_for_status()
                positions = response.json()

            # Filter to only open positions (not redeemable)
            open_positions = [
                pos for pos in positions
                if not pos.get("redeemable", False)
            ]

            self.logger.debug(f"Found {len(open_positions)} open positions")
            return open_positions

        except Exception as e:
            self.logger.error(f"Failed to fetch open positions: {e}", exc_info=True)
            # Return empty list on error (graceful degradation)
            # Caller will handle empty list as "no positions"
            return []
