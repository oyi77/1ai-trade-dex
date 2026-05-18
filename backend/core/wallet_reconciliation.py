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
        Download ALL historical trades from blockchain via Data API /activity endpoint.

        Fetches from {DATA_API_URL}/activity?user={wallet_address}, paginating
        through all records. Filters to type=TRADE and aggregates by conditionId
        to produce one DB Trade per unique market (slug). This avoids duplicates
        and wrong-sized trades caused by the old /positions-based approach which
        used token_ids as market_ticker (DB uses slugs).

        Args:
            max_pages: Safety cap on pagination (None = fetch all)

        Returns:
            Count of newly imported trades
        """
        if not self.wallet_address:
            self.logger.warning("Wallet address is empty, skipping blockchain history import")
            return 0

        self.logger.info(f"Importing blockchain history for {self.wallet_address}")

        try:
            # Paginate through ALL activity records
            all_trades: list[dict] = []
            offset = 0
            page_limit = 100
            pages_fetched = 0

            async with httpx.AsyncClient(timeout=30.0) as client:
                while True:
                    response = await client.get(
                        settings.DATA_API_URL + "/activity",
                        params={
                            "user": self.wallet_address,
                            "limit": page_limit,
                            "offset": offset,
                        },
                    )
                    response.raise_for_status()
                    batch = response.json()

                    if not batch:
                        break

                    # Filter to TRADE records only
                    trade_records = [r for r in batch if r.get("type") == "TRADE"]
                    all_trades.extend(trade_records)

                    offset += len(batch)
                    pages_fetched += 1

                    if max_pages is not None and pages_fetched >= max_pages:
                        self.logger.info(f"Reached max_pages={max_pages} limit")
                        break

                    # If we got fewer than page_limit, we've reached the end
                    if len(batch) < page_limit:
                        break

            self.logger.info(
                f"Downloaded {len(all_trades)} TRADE records from activity API "
                f"({pages_fetched} pages)"
            )

            if not all_trades:
                return 0

            # Aggregate by conditionId: one position per unique market
            agg: dict[str, dict] = {}
            for rec in all_trades:
                cond_id = rec.get("conditionId", "")
                slug = rec.get("slug", "")
                if not cond_id or not slug:
                    continue

                if cond_id not in agg:
                    agg[cond_id] = {
                        "slug": slug,
                        "conditionId": cond_id,
                        "total_size": 0.0,
                        "weighted_price_sum": 0.0,
                        "outcome": rec.get("outcome", "Yes"),
                        "title": rec.get("title", ""),
                    }

                size = float(rec.get("size", 0))
                price = float(rec.get("price", 0))
                agg[cond_id]["total_size"] += size
                agg[cond_id]["weighted_price_sum"] += size * price

            self.logger.info(f"Aggregated into {len(agg)} unique positions by conditionId")

            imported = 0
            for cond_id, pos_data in agg.items():
                slug = pos_data["slug"]
                total_size = pos_data["total_size"]
                outcome = pos_data["outcome"]

                # Compute weighted average price
                if total_size > 0:
                    avg_price = pos_data["weighted_price_sum"] / total_size
                else:
                    avg_price = 0.0

                # Check if a Trade with this exact slug already exists
                existing = self.db.query(Trade).filter(
                    Trade.market_ticker == slug,
                    Trade.trading_mode == self.mode,
                ).first()

                if existing:
                    size_diff = abs((existing.size or 0.0) - total_size)
                    if size_diff <= 0.01:
                        # Already imported with matching size — skip
                        self.logger.debug(
                            f"Trade {slug} already in DB (id={existing.id}, "
                            f"size={existing.size})"
                        )
                        continue
                    else:
                        # Size differs — update with audit log
                        from backend.models.audit_logger import log_position_updated

                        old_size = existing.size
                        old_entry_price = existing.entry_price
                        self.logger.info(
                            f"Updating position size for {slug}: "
                            f"{old_size} -> {total_size} (conditionId aggregation)"
                        )
                        existing.size = total_size
                        existing.entry_price = avg_price
                        existing.last_sync_at = datetime.now(timezone.utc)
                        existing.blockchain_verified = True
                        log_position_updated(
                            db=self.db,
                            position_id=f"{slug}:{existing.id}",
                            old_state={
                                "size": old_size,
                                "entry_price": old_entry_price,
                            },
                            new_state={
                                "size": total_size,
                                "entry_price": avg_price,
                                "last_sync_at": existing.last_sync_at.isoformat(),
                            },
                            user_id="system:reconciliation",
                        )
                    continue

                # No existing trade — create new one
                new_trade = Trade(
                    market_ticker=slug,
                    platform="polymarket",
                    direction="up" if outcome == "Yes" else "down",
                    entry_price=avg_price,
                    size=total_size,
                    timestamp=datetime.now(timezone.utc),
                    trading_mode=self.mode,
                    settled=False,
                    result=None,
                    source="external",
                    strategy=self._resolve_strategy_for_position(slug) or "wallet_import",
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
                    f"Imported position: {slug} "
                    f"({outcome} @ {avg_price:.4f}, {total_size:.2f} shares, "
                    f"condId={cond_id[:16]}...)"
                )

            self.db.commit()

            from backend.models.audit_logger import log_wallet_reconciled
            log_wallet_reconciled(
                db=self.db,
                wallet_address=self.wallet_address,
                reconciliation_data={
                    "operation": "import_blockchain_history",
                    "imported_count": imported,
                    "total_trade_records": len(all_trades),
                    "unique_positions": len(agg),
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
        """Import REDEEM records from /activity API using exact slug matching.

        REDEEM records capture winning positions that disappeared from /positions
        after full redemption. Uses ONLY exact slug matching — no loose prefix.
        """
        if not self.wallet_address:
            self.logger.warning("Wallet address is empty, skipping REDEEM activity import")
            return 0

        self.logger.info(f"Importing REDEEM activity for {self.wallet_address}")

        try:
            all_redeems: list[dict] = []
            offset = 0
            page_limit = 100

            async with httpx.AsyncClient(timeout=30.0) as client:
                while True:
                    response = await client.get(
                        settings.DATA_API_URL + "/activity",
                        params={
                            "user": self.wallet_address,
                            "limit": page_limit,
                            "offset": offset,
                        },
                    )
                    response.raise_for_status()
                    batch = response.json()

                    if not batch:
                        break

                    all_redeems.extend(r for r in batch if r.get("type") == "REDEEM")
                    offset += len(batch)
                    if len(batch) < page_limit:
                        break

            self.logger.info(
                f"Found {len(all_redeems)} REDEEM records in activity API"
            )

            imported = 0
            for record in all_redeems:
                condition_id = record.get("conditionId", "")
                slug = record.get("slug", "")
                redeem_amount = float(record.get("usdcSize", 0))
                timestamp_unix = record.get("timestamp", 0)

                if not condition_id:
                    continue

                # Step 1: Exact slug match
                existing = None
                if slug:
                    existing = self.db.query(Trade).filter(
                        Trade.market_ticker == slug,
                        Trade.trading_mode == self.mode,
                    ).first()

                # Step 2: If no exact slug match, use fuzzy matching with scoring
                if existing is None and slug:
                    from difflib import SequenceMatcher

                    all_mode_trades = self.db.query(Trade).filter(
                        Trade.trading_mode == self.mode,
                    ).all()

                    matches_with_scores = []

                    for t in all_mode_trades:
                        # Calculate fuzzy match score using SequenceMatcher
                        ratio = SequenceMatcher(None, slug.lower(), t.market_ticker.lower()).ratio()
                        if ratio > 0.6:  # Threshold: >60% similarity
                            matches_with_scores.append((ratio, t))

                    if len(matches_with_scores) == 1:
                        # Single best match above threshold
                        existing = matches_with_scores[0][1]
                    elif len(matches_with_scores) > 1:
                        # Multiple matches: pick highest scoring one
                        matches_with_scores.sort(key=lambda x: x[0], reverse=True)
                        best_score = matches_with_scores[0][0]

                        # Only accept if significantly better than second best
                        if len(matches_with_scores) > 1 and (best_score - matches_with_scores[1][0]) > 0.1:
                            existing = matches_with_scores[0][1]
                        else:
                            # Multiple similar matches - log but don't auto-pick
                            self.logger.warning(
                                f"Multiple ambiguous matches for REDEEM slug={slug}. "
                                f"Scores: {[(t.market_ticker, s) for s, t in matches_with_scores[:3]]}"
                            )

                # Step 3: Fallback to condition_id matching if available
                if existing is None and condition_id:
                    # Try to match by condition_id in DB trades
                    # (assumes condition_id is stored somewhere in Trade model)
                    try:
                        all_mode_trades = self.db.query(Trade).filter(
                            Trade.trading_mode == self.mode,
                        ).all()
                        for t in all_mode_trades:
                            # Check if trade has condition_id metadata
                            if hasattr(t, 'condition_id') and t.condition_id == condition_id:
                                existing = t
                                break
                    except Exception as e:
                        self.logger.debug(f"Condition_id fallback failed: {e}")

                if existing:
                    if existing.settled:
                        continue

                    existing.settled = True
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

                # Orphaned REDEEM — no matching trade in DB
                if redeem_amount > 0:
                    self.logger.warning(
                        f"Orphaned REDEEM: slug={slug}, "
                        f"condId={condition_id[:16]}..., "
                        f"amount={redeem_amount} USD. "
                        f"No fuzzy match found (threshold >0.6). "
                        f"Manual reconciliation may be needed. "
                        f"timestamp={timestamp_unix}"
                    )

            self.db.commit()
            self.logger.info(f"Updated {imported} trades from REDEEM activity records")
            return imported

        except Exception as e:
            self.logger.error(f"Failed to import activity redeems: {e}", exc_info=True)
            self.db.rollback()
            return 0

    async def sync_current_positions(self) -> SyncResult:
        """Fetch current open positions and compare with DB.

        Builds blockchain_map keyed by slug (primary) and asset/token_id (fallback)
        so DB trades with slug market_tickers match correctly.
        """
        self.logger.info("Syncing current positions from blockchain")

        result = SyncResult()

        try:
            blockchain_positions = await self._fetch_open_positions()

            # Primary map keyed by slug; fallback map keyed by asset (token_id)
            blockchain_by_slug: dict[str, dict] = {}
            blockchain_by_asset: dict[str, dict] = {}
            for pos in blockchain_positions:
                slug = pos.get("slug", "")
                asset = pos.get("asset", "")
                if slug:
                    blockchain_by_slug[slug] = pos
                if asset:
                    blockchain_by_asset[asset] = pos

            self.logger.debug(
                f"Blockchain has {len(blockchain_positions)} open positions "
                f"({len(blockchain_by_slug)} by slug, {len(blockchain_by_asset)} by asset)"
            )

            db_open_trades = self.db.query(Trade).filter(
                (Trade.trading_mode == self.mode) &
                (Trade.settlement_time.is_(None)) &
                (~Trade.settled)
            ).all()

            self.logger.debug(f"DB has {len(db_open_trades)} open trades")

            for db_trade in db_open_trades:
                ticker = db_trade.market_ticker or ""

                # Look up position by slug first, then by asset/token_id
                blockchain_pos = blockchain_by_slug.get(ticker) or blockchain_by_asset.get(ticker)

                if blockchain_pos is None:
                    from backend.core.settlement_helpers import (
                        fetch_resolution_for_trade,
                        calculate_pnl,
                    )

                    try:
                        is_resolved, settlement_value = await fetch_resolution_for_trade(db_trade)
                    except Exception as exc:
                        self.logger.warning(
                            f"Resolution lookup failed for trade {db_trade.id} "
                            f"({ticker}): {exc}. Leaving open."
                        )
                        continue

                    if not is_resolved or settlement_value is None:
                        self.logger.warning(
                            f"Position {ticker} (id={db_trade.id}) "
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
                    elif settlement_value is not None and settlement_value >= 1.0:
                        db_trade.result = "win"
                    elif settlement_value is not None and settlement_value <= 0.0:
                        db_trade.result = "loss"
                    else:
                        db_trade.result = "push"
                    self.logger.info(
                        f"Position {ticker} (id={db_trade.id}) "
                        f"closed via reconciliation: settlement={settlement_value} pnl=${pnl:+.2f}"
                    )
                    result.closed_count += 1
                else:
                    blockchain_size = blockchain_pos.get("initialValue", 0.0)
                    db_size = db_trade.size or 0.0

                    self.alert_manager.check_position_discrepancy(
                        position_id=ticker,
                        db_value=db_size,
                        blockchain_value=blockchain_size,
                        mode=self.mode,
                    )

                    db_trade.last_sync_at = datetime.now(timezone.utc)
                    db_trade.blockchain_verified = True
                    result.updated_count += 1
                    self.logger.debug(
                        f"Position {ticker} (id={db_trade.id}) "
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
        """Find positions on blockchain that don't exist in DB.

        Matches by slug (primary) and asset/token_id (fallback).
        """
        self.logger.info("Detecting orphaned positions")

        try:
            blockchain_positions = await self._fetch_open_positions()

            orphans = []
            for pos in blockchain_positions:
                slug = pos.get("slug", "")
                asset = pos.get("asset", "")

                # Check by slug first, then by asset (token_id)
                existing = None
                if slug:
                    existing = self.db.query(Trade).filter(
                        (Trade.market_ticker == slug) &
                        (Trade.trading_mode == self.mode) &
                        (~Trade.settled)
                    ).first()

                if not existing and asset:
                    existing = self.db.query(Trade).filter(
                        (Trade.market_ticker == asset) &
                        (Trade.trading_mode == self.mode) &
                        (~Trade.settled)
                    ).first()

                if existing:
                    continue

                # Use slug as market_id (matches DB convention), fallback to asset
                market_id = slug or asset
                orphan = OrphanedPosition(
                    market_id=market_id,
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
                Trade.market_ticker == orphan.market_id,
                Trade.trading_mode == self.mode,
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
        """Fetch open positions from Data API. Returns raw API dicts with slug, asset, etc."""
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
