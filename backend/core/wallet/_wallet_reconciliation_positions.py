"""WalletReconciler position-sync mixin: open-position sync, orphans, verify, fetch."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import httpx

from backend.config import settings
from backend.models.database import Trade
from backend.core.wallet._wallet_reconciliation_types import OrphanedPosition, SyncResult


class WalletReconcilerPositionsMixin:
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

            db_open_trades = (
                self.db.query(Trade)
                .filter(
                    (Trade.trading_mode == self.mode)
                    & (Trade.settlement_time.is_(None))
                    & (~Trade.settled)
                )
                .all()
            )

            self.logger.debug(f"DB has {len(db_open_trades)} open trades")

            for db_trade in db_open_trades:
                ticker = db_trade.market_ticker or ""

                # Look up position by slug first, then by asset/token_id
                blockchain_pos = blockchain_by_slug.get(
                    ticker
                ) or blockchain_by_asset.get(ticker)

                if blockchain_pos is None:
                    from backend.core.settlement.settlement_helpers import (
                        fetch_resolution_for_trade,
                        calculate_pnl,
                    )

                    try:
                        is_resolved, settlement_value = (
                            await fetch_resolution_for_trade(db_trade)
                        )
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

            # Verify trades with blockchain_verified=false against CLOB API
            verified, failed = await self._verify_unverified_trades()
            result.updated_count += verified
            if failed:
                result.errors.extend(failed)

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
                    existing = (
                        self.db.query(Trade)
                        .filter(
                            (Trade.market_ticker == slug)
                            & (Trade.trading_mode == self.mode)
                            & (~Trade.settled)
                        )
                        .first()
                    )

                if not existing and asset:
                    existing = (
                        self.db.query(Trade)
                        .filter(
                            (Trade.market_ticker == asset)
                            & (Trade.trading_mode == self.mode)
                            & (~Trade.settled)
                        )
                        .first()
                    )

                if existing:
                    continue

                # Use slug as market_id (matches DB convention), fallback to asset
                market_id = slug or asset
                orphan = OrphanedPosition(
                    market_id=market_id,
                    blockchain_size=pos["initialValue"],
                    blockchain_entry_price=pos["avgPrice"],
                    detected_at=datetime.now(timezone.utc),
                )
                orphans.append(orphan)
                self.logger.warning(
                    f"Orphaned position detected: {orphan.market_id} "
                    f"({orphan.blockchain_size} shares @ {orphan.blockchain_entry_price})"
                )

            self.logger.info(f"Found {len(orphans)} orphaned positions")
            return orphans

        except Exception as e:
            self.logger.error(
                f"Failed to detect orphaned positions: {e}", exc_info=True
            )
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
        self.logger.info(
            f"Creating DB record for orphaned position: {orphan.market_id}"
        )

        try:
            # Check again if it exists (race condition)
            existing = (
                self.db.query(Trade)
                .filter(
                    Trade.market_ticker == orphan.market_id,
                    Trade.trading_mode == self.mode,
                )
                .first()
            )

            if existing:
                self.logger.debug(
                    f"Orphan {orphan.market_id} already has DB record (id={existing.id})"
                )
                return False

            # Create trade record
            from backend.core.trade_forensics import classify_trade_role

            role, maker_size, taker_size = await classify_trade_role(
                platform="polymarket",
                mode=self.mode,
                clob_order_id=orphan.clob_order_id,
                price=orphan.blockchain_entry_price,
                size=orphan.blockchain_size,
                direction="up",
                decision={},
                db_session=self.db,
            )

            trade = Trade(
                market_ticker=orphan.market_id,
                platform="polymarket",
                direction="up",  # Default to "up" - we don't know actual direction from position alone
                entry_price=orphan.blockchain_entry_price,
                size=orphan.blockchain_size,
                timestamp=orphan.detected_at,
                trading_mode=self.mode,
                # Reconciliation fields (Task 1)
                source="orphaned",  # Position found on-chain, reconstructed
                strategy="wallet_import",
                clob_order_id=orphan.clob_order_id,
                blockchain_verified=True,
                settlement_source="clob_api",
                external_import_at=orphan.detected_at,
                # Default values for required fields
                model_probability=0.5,  # Unknown for orphaned positions
                market_price_at_entry=orphan.blockchain_entry_price,
                edge_at_entry=0.0,  # Unknown for orphaned positions
                role=role,
                maker_size=maker_size,
                taker_size=taker_size,
            )

            self.db.add(trade)
            self.db.commit()

            self.logger.info(f"Created orphaned position record: id={trade.id}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to close orphaned position: {e}", exc_info=True)
            self.db.rollback()
            return False

    async def _verify_unverified_trades(self) -> tuple[int, list[str]]:
        """Verify trades with blockchain_verified=false against CLOB order API.

        For each unverified trade that has a clob_order_id, queries the Polymarket
        CLOB get_order() API to confirm the order exists and update verification status.

        Returns:
            Tuple of (verified_count, error_messages).
        """
        verified = 0
        errors: list[str] = []

        unverified = (
            self.db.query(Trade)
            .filter(
                Trade.trading_mode == self.mode,
                Trade.blockchain_verified.is_(False),
                Trade.clob_order_id.isnot(None),
            )
            .all()
        )

        if not unverified:
            return verified, errors

        self.logger.info(
            f"Verifying {len(unverified)} trades with blockchain_verified=false"
        )

        for trade in unverified:
            try:
                order = await self.clob.get_order(trade.clob_order_id)
                if order is not None:
                    trade.blockchain_verified = True
                    trade.last_sync_at = datetime.now(timezone.utc)
                    # Update size from CLOB if available
                    clob_size = float(
                        order.get("original_size", 0) or order.get("size", 0)
                    )
                    if (
                        clob_size > 0
                        and trade.size
                        and abs(trade.size - clob_size) > 0.01
                    ):
                        self.logger.info(
                            f"CLOB order {trade.clob_order_id} size mismatch: "
                            f"DB={trade.size}, CLOB={clob_size}. Updating."
                        )
                        trade.size = clob_size
                    verified += 1
                    self.logger.debug(
                        f"Verified trade {trade.id} ({trade.market_ticker}) "
                        f"via CLOB order {trade.clob_order_id}"
                    )
                else:
                    self.logger.warning(
                        f"CLOB order {trade.clob_order_id} not found for trade "
                        f"{trade.id} ({trade.market_ticker})"
                    )
            except Exception as e:
                msg = f"Failed to verify trade {trade.id} order {trade.clob_order_id}: {e}"
                self.logger.warning(msg)
                errors.append(msg)

        if verified:
            self.logger.info(
                f"Verified {verified}/{len(unverified)} trades via CLOB API"
            )

        return verified, errors

    async def _fetch_open_positions(self) -> list[dict]:
        """Fetch open positions from Data API. Returns raw API dicts with slug, asset, etc."""
        if not self.wallet_address:
            self.logger.warning(
                "Wallet address is empty, skipping open positions fetch"
            )
            return []

        self.logger.info(f"Fetching open positions for {self.wallet_address}")

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    settings.DATA_API_URL + "/positions",
                    params={"user": self.wallet_address},
                )
                response.raise_for_status()
                positions = response.json()

            # Filter to only open positions (not redeemable)
            open_positions = [
                pos for pos in positions if not pos.get("redeemable", False)
            ]

            self.logger.debug(f"Found {len(open_positions)} open positions")
            return open_positions

        except Exception as e:
            self.logger.error(f"Failed to fetch open positions: {e}", exc_info=True)
            # Return empty list on error (graceful degradation)
            # Caller will handle empty list as "no positions"
            return []
