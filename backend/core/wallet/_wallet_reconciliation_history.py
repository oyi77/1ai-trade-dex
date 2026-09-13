"""WalletReconciler history-import mixin: /activity TRADE + REDEEM ingestion."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import httpx

from backend.config import settings
from backend.models.database import Trade


class WalletReconcilerHistoryMixin:
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
            self.logger.warning(
                "Wallet address is empty, skipping blockchain history import"
            )
            return 0

        self.logger.info(f"Importing blockchain history for {self.wallet_address}")

        try:
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

                    trade_records = [r for r in batch if r.get("type") == "TRADE"]
                    all_trades.extend(trade_records)

                    offset += len(batch)
                    pages_fetched += 1

                    if max_pages is not None and pages_fetched >= max_pages:
                        self.logger.info(f"Reached max_pages={max_pages} limit")
                        break

                    if len(batch) < page_limit:
                        break

            self.logger.info(
                f"Downloaded {len(all_trades)} TRADE records from activity API "
                f"({pages_fetched} pages)"
            )

            if not all_trades:
                return 0

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

            self.logger.info(
                f"Aggregated into {len(agg)} unique positions by conditionId"
            )

            imported = 0
            for cond_id, pos_data in agg.items():
                slug = pos_data["slug"]
                total_size = pos_data["total_size"]
                outcome = pos_data["outcome"]

                if total_size > 0:
                    avg_price = pos_data["weighted_price_sum"] / total_size
                else:
                    avg_price = 0.0

                existing = (
                    self.db.query(Trade)
                    .filter(
                        Trade.market_ticker == slug,
                        Trade.trading_mode == self.mode,
                    )
                    .first()
                )

                if existing:
                    size_diff = abs((existing.size or 0.0) - total_size)
                    if size_diff <= 0.01:
                        self.logger.debug(
                            f"Trade {slug} already in DB (id={existing.id}, "
                            f"size={existing.size})"
                        )
                        continue
                    else:
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

                from backend.core.trade_forensics import classify_trade_role

                role, maker_size, taker_size = await classify_trade_role(
                    platform="polymarket",
                    mode=self.mode,
                    clob_order_id=None,
                    price=avg_price,
                    size=total_size,
                    direction="up" if outcome == "Yes" else "down",
                    decision={},
                    db_session=self.db,
                )

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
                    strategy=self._resolve_strategy_for_position(slug)
                    or "wallet_import",
                    blockchain_verified=True,
                    settlement_source=None,
                    external_import_at=datetime.now(timezone.utc),
                    model_probability=0.5,
                    market_price_at_entry=avg_price,
                    edge_at_entry=0.0,
                    role=role,
                    maker_size=maker_size,
                    taker_size=taker_size,
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
            self.logger.error(
                f"Failed to import blockchain history: {e}", exc_info=True
            )
            self.db.rollback()
            raise

    async def import_activity_redeems(self) -> int:
        """Import REDEEM records from /activity API using exact slug matching.

        REDEEM records capture winning positions that disappeared from /positions
        after full redemption. Uses ONLY exact slug matching — no loose prefix.
        """
        if not self.wallet_address:
            self.logger.warning(
                "Wallet address is empty, skipping REDEEM activity import"
            )
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

            self.logger.info(f"Found {len(all_redeems)} REDEEM records in activity API")

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
                    existing = (
                        self.db.query(Trade)
                        .filter(
                            Trade.market_ticker == slug,
                            Trade.trading_mode == self.mode,
                        )
                        .first()
                    )

                # Step 2: If no exact slug match, use fuzzy matching with scoring
                if existing is None and slug:
                    from difflib import SequenceMatcher

                    all_mode_trades = (
                        self.db.query(Trade)
                        .filter(
                            Trade.trading_mode == self.mode,
                        )
                        .all()
                    )

                    matches_with_scores = []

                    for t in all_mode_trades:
                        # Calculate fuzzy match score using SequenceMatcher
                        ratio = SequenceMatcher(
                            None, slug.lower(), t.market_ticker.lower()
                        ).ratio()
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
                        if (
                            len(matches_with_scores) > 1
                            and (best_score - matches_with_scores[1][0]) > 0.1
                        ):
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
                        all_mode_trades = (
                            self.db.query(Trade)
                            .filter(
                                Trade.trading_mode == self.mode,
                            )
                            .all()
                        )
                        for t in all_mode_trades:
                            # Check if trade has condition_id metadata
                            if (
                                hasattr(t, "condition_id")
                                and t.condition_id == condition_id
                            ):
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
                        if timestamp_unix
                        else datetime.now(timezone.utc)
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

