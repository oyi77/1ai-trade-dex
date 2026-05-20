"""Wallet synchronization module for CopyTrader.

Handles DB operations for tracking wallet positions and polling for new trades.
"""

from typing import Tuple

import httpx

from backend.models.database import SessionLocal, CopyTraderEntry
from backend.config import settings

from loguru import logger

DATA_HOST = settings.DATA_API_URL


class WalletTrade:
    """Represents a trade from a watched wallet."""

    def __init__(
        self,
        user: str,
        wallet: str,
        condition_id: str,
        outcome: str,  # "YES" or "NO"
        side: str,  # "BUY" or "SELL"
        price: float,
        size: float,  # USDC
        timestamp: str,
        tx_hash: str = "",
        title: str = "",
    ):
        self.user = user
        self.wallet = wallet
        self.condition_id = condition_id
        self.outcome = outcome
        self.side = side
        self.price = price
        self.size = size
        self.timestamp = timestamp
        self.tx_hash = tx_hash
        self.title = title


class WalletWatcher:
    """Polls a wallet's trade history for new trades."""

    def __init__(self, http: httpx.AsyncClient):
        self._http = http
        # wallet -> set of seen tx_hashes
        self._seen: dict[str, set[str]] = {}
        # wallet -> {pos_key -> cumulative_sell_size} (in-memory only; resets on restart)
        self._sell_sizes: dict[str, dict[str, float]] = {}

    def _get_entry_size(self, wallet: str, pos_key: str) -> float:
        try:
            db = SessionLocal()
            try:
                condition_id, side = pos_key.split(":", 1)
                entry = (
                    db.query(CopyTraderEntry)
                    .filter_by(wallet=wallet, condition_id=condition_id, side=side)
                    .first()
                )
                return entry.size if entry else 0.0
            finally:
                db.close()
        except Exception as e:
            logger.warning(
                f"DB read error for entry size ({wallet[:10]}, {pos_key}): {e}"
            )
            return 0.0

    def _upsert_entry_size(self, wallet: str, pos_key: str, delta: float) -> float:
        db = SessionLocal()
        try:
            condition_id, side = pos_key.split(":", 1)
            entry = (
                db.query(CopyTraderEntry)
                .filter_by(wallet=wallet, condition_id=condition_id, side=side)
                .first()
            )
            if entry:
                entry.size += delta
            else:
                entry = CopyTraderEntry(
                    wallet=wallet,
                    condition_id=condition_id,
                    side=side,
                    size=delta,
                )
                db.add(entry)
            db.commit()
            db.refresh(entry)
            return entry.size
        except Exception as e:
            db.rollback()
            logger.warning(
                f"DB upsert error for entry size ({wallet[:10]}, {pos_key}): {e}"
            )
            return 0.0
        finally:
            db.close()

    async def _fetch_all_trades(
        self, wallet: str, page_size: int = 100, max_pages: int = 5
    ) -> list[dict]:
        """Fetch trades for a wallet, paginating up to max_pages."""
        all_trades: list[dict] = []
        offset = 0
        pages_fetched = 0
        while pages_fetched < max_pages:
            try:
                resp = await self._http.get(
                    f"{DATA_HOST}/trades",
                    params={
                        "user": wallet,
                        "limit": page_size,
                        "offset": offset,
                        "takerOnly": "true",
                    },
                )
                resp.raise_for_status()
                page = resp.json()
            except Exception as e:
                logger.warning(
                    f"Poll page (offset={offset}) failed for {wallet[:10]}...: {e}"
                )
                break
            if not page:
                break
            all_trades.extend(page)
            pages_fetched += 1
            if len(page) < page_size:
                # Last page
                break
            offset += page_size
        return all_trades

    async def poll(
        self, wallet: str, limit: int = 100
    ) -> Tuple[list[WalletTrade], list[WalletTrade]]:
        """
        Poll wallet trades. Returns (new_buys, new_exits).
        new_exits: trades where cumulative SELL >= 50% of original entry.

        First call for a wallet: fetches ALL history to seed the seen set.
        Subsequent calls: fetches only 2 pages (200 trades) for speed.
        """
        is_first_poll = wallet not in self._seen

        if is_first_poll:
            # Seed: fetch all history so we don't mirror old trades
            trades_raw = await self._fetch_all_trades(wallet, page_size=limit)
        else:
            # Incremental: only fetch 2 recent pages (200 trades max, 2 API calls)
            trades_raw = await self._fetch_all_trades(
                wallet, page_size=limit, max_pages=2
            )

        if not trades_raw and is_first_poll:
            return [], []

        if is_first_poll:
            self._seen[wallet] = set()
            self._sell_sizes[wallet] = {}
            # Seed AND return signals from initial fetch
            new_buys: list[WalletTrade] = []
            new_exits: list[WalletTrade] = []
            for t in trades_raw:
                key = t.get("transactionHash", "") or t.get("id", "")
                self._seen[wallet].add(key)
                # Also create WalletTrade objects for initial signals
                outcome_idx = t.get("outcomeIndex", 0)
                outcome = "YES" if outcome_idx == 0 else "NO"
                side = t.get("side", "BUY").upper()
                size = float(t.get("size", 0))
                price = float(t.get("price", 0))
                condition_id = t.get("conditionId", "")
                trade = WalletTrade(
                    user=wallet,
                    wallet=t.get("proxyWallet", ""),
                    condition_id=condition_id,
                    outcome=outcome,
                    side=side,
                    price=price,
                    size=size,
                    timestamp=t.get("timestamp", ""),
                    tx_hash=key,
                    title=t.get("title", ""),
                )
                if side == "BUY":
                    new_buys.append(trade)
                else:
                    new_exits.append(trade)
            return new_buys, new_exits

        seen = self._seen[wallet]
        new_buys: list[WalletTrade] = []
        new_exits: list[WalletTrade] = []

        for t in trades_raw:
            tx = t.get("transactionHash", "") or t.get("id", "")
            if tx in seen:
                continue
            seen.add(tx)

            outcome_idx = t.get("outcomeIndex", 0)
            outcome = "YES" if outcome_idx == 0 else "NO"
            side = t.get("side", "BUY").upper()
            size = float(t.get("size", 0))
            price = float(t.get("price", 0))
            condition_id = t.get("conditionId", "")

            trade = WalletTrade(
                user=t.get("user", wallet),
                wallet=wallet,
                condition_id=condition_id,
                outcome=outcome,
                side=side,
                price=price,
                size=size,
                timestamp=t.get("timestamp", ""),
                tx_hash=tx,
                title=t.get("title", ""),
            )

            pos_key = f"{condition_id}:{outcome}"
            if side == "BUY":
                new_total = self._upsert_entry_size(wallet, pos_key, size)
                new_buys.append(trade)
                logger.info(
                    f"New trade from {wallet[:10]}...: BUY {outcome} "
                    f"@ {price:.3f} size={size:.2f} total={new_total:.2f} | {trade.title[:40]}"
                )
            else:  # SELL
                self._sell_sizes[wallet][pos_key] = (
                    self._sell_sizes[wallet].get(pos_key, 0) + size
                )
                orig_entry = self._get_entry_size(wallet, pos_key)
                cumulative_sell = self._sell_sizes[wallet][pos_key]

                if (
                    orig_entry > 0
                    and cumulative_sell
                    >= settings.WALLET_SYNC_EXIT_THRESHOLD * orig_entry
                ):
                    new_exits.append(trade)
                    logger.info(
                        f"Exit signal from {wallet[:10]}...: SELL {outcome} "
                        f"cumulative={cumulative_sell:.2f}/{orig_entry:.2f} "
                        f"({cumulative_sell / orig_entry:.0%}) | {trade.title[:40]}"
                    )

        return new_buys, new_exits
