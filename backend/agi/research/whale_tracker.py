"""Whale Wallet Auto-Tracking — discovers and monitors top Polymarket wallets.

Auto-discovers top wallets from Polymarket leaderboard, tracks positions/trades/PnL,
and generates copy-trading signals for top performers. Feeds data to whale_frontrun.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List

import httpx
from loguru import logger

POLYMARKET_LEADERBOARD_URL = "https://polymarket.com/api/leaderboard"
POLYMARKET_DATA_API = "https://data-api.polymarket.com"


@dataclass
class WhaleProfile:
    """A tracked whale wallet profile."""

    address: str
    username: str
    pnl_30d: float
    volume_30d: float
    win_rate: float
    num_trades: int
    rank: int
    positions: List[dict] = field(default_factory=list)
    last_checked: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    copy_signal_score: float = 0.0


@dataclass
class CopySignal:
    """A copy-trading signal from a top whale."""

    whale_address: str
    whale_username: str
    market_id: str
    direction: str  # "yes" or "no"
    size: float
    confidence: float
    reasoning: str
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def _compute_copy_signal_score(whale: dict) -> float:
    """Compute a copy-signal score (0-1) from whale metrics."""
    pnl = whale.get("pnl_30d", 0) or 0
    wr = whale.get("win_rate", 0) or 0
    volume = whale.get("volume_30d", 0) or 0
    trades = whale.get("num_trades", 0) or 0

    if pnl <= 0 or wr < 0.45 or trades < 10:
        return 0.0

    score = 0.0
    score += min(0.3, pnl / 10000 * 0.3)  # PnL component
    score += (wr - 0.45) * 2  # Win rate component (0.45-0.95 -> 0-1)
    score += min(0.2, volume / 100000 * 0.2)  # Volume component
    score += min(0.1, trades / 500 * 0.1)  # Activity component

    return max(0.0, min(1.0, score))


class WhaleTracker:
    """Discovers and monitors top Polymarket wallets."""

    def __init__(
        self,
        min_pnl_30d: float = 1000.0,
        min_win_rate: float = 0.50,
        min_trades: int = 20,
        top_n: int = 20,
    ):
        self.min_pnl_30d = min_pnl_30d
        self.min_win_rate = min_win_rate
        self.min_trades = min_trades
        self.top_n = top_n
        self._whales: List[WhaleProfile] = []

    async def discover_whales(self) -> List[WhaleProfile]:
        """Discover top-performing wallets from Polymarket leaderboard."""
        whales: List[WhaleProfile] = []

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                # Try Polymarket leaderboard API
                resp = await client.get(
                    POLYMARKET_LEADERBOARD_URL,
                    params={"limit": 50, "period": "30d"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    entries = data if isinstance(data, list) else data.get("data", data.get("entries", []))
                    rank = 0
                    for entry in entries:
                        rank += 1
                        pnl = float(entry.get("pnl", entry.get("profit", 0)) or 0)
                        wr = float(entry.get("winRate", entry.get("win_rate", 0)) or 0)
                        volume = float(entry.get("volume", entry.get("volume_30d", 0)) or 0)
                        trades = int(entry.get("numTrades", entry.get("num_trades", 0)) or 0)
                        addr = entry.get("address", entry.get("wallet", entry.get("user", "")))

                        if not addr:
                            continue
                        if pnl < self.min_pnl_30d:
                            continue
                        if wr < self.min_win_rate:
                            continue
                        if trades < self.min_trades:
                            continue

                        score = _compute_copy_signal_score({
                            "pnl_30d": pnl,
                            "win_rate": wr,
                            "volume_30d": volume,
                            "num_trades": trades,
                        })

                        whales.append(
                            WhaleProfile(
                                address=addr,
                                username=entry.get("username", entry.get("name", addr[:10])),
                                pnl_30d=pnl,
                                volume_30d=volume,
                                win_rate=wr,
                                num_trades=trades,
                                rank=rank,
                                copy_signal_score=score,
                            )
                        )

                        if len(whales) >= self.top_n:
                            break
                else:
                    logger.warning(
                        "Leaderboard API returned %d", resp.status_code
                    )
        except Exception as exc:
            logger.warning("Whale discovery failed: %s", exc)

        # Sort by copy signal score
        whales.sort(key=lambda w: w.copy_signal_score, reverse=True)
        self._whales = whales[:self.top_n]

        logger.info(
            "Whale tracker: discovered %d qualifying whales (top score: %.2f)",
            len(self._whales),
            self._whales[0].copy_signal_score if self._whales else 0,
        )
        return self._whales

    async def fetch_whale_positions(
        self, whale: WhaleProfile
    ) -> List[dict]:
        """Fetch current positions for a whale wallet."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{POLYMARKET_DATA_API}/positions",
                    params={"user": whale.address, "limit": 50},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    positions = data if isinstance(data, list) else data.get("data", [])
                    whale.positions = positions
                    return positions
        except Exception as exc:
            logger.debug(
                "Position fetch failed for %s: %s", whale.address[:10], exc
            )
        return []

    async def generate_copy_signals(
        self, min_score: float = 0.5
    ) -> List[CopySignal]:
        """Generate copy-trading signals from top whale positions."""
        if not self._whales:
            await self.discover_whales()

        signals: List[CopySignal] = []
        for whale in self._whales:
            if whale.copy_signal_score < min_score:
                continue

            positions = await self.fetch_whale_positions(whale)
            for pos in positions:
                size = float(pos.get("size", pos.get("initialValue", 0)) or 0)
                if size < 100:
                    continue

                side = pos.get("side", pos.get("outcome", "BUY"))
                direction = "yes" if str(side).upper() in ("BUY", "BID", "YES") else "no"
                market = pos.get("condition_id", pos.get("asset", pos.get("market", "")))

                signals.append(
                    CopySignal(
                        whale_address=whale.address,
                        whale_username=whale.username,
                        market_id=str(market),
                        direction=direction,
                        size=size,
                        confidence=whale.copy_signal_score,
                        reasoning=f"Top whale #{whale.rank} ({whale.username}) "
                        f"WR={whale.win_rate:.0%} PnL=${whale.pnl_30d:.0f}",
                    )
                )

            # Rate limiting
            import asyncio
            await asyncio.sleep(0.5)

        signals.sort(key=lambda s: s.confidence, reverse=True)
        logger.info(
            "Whale tracker: generated %d copy signals from %d whales",
            len(signals),
            len(self._whales),
        )
        return signals


async def whale_tracking_job() -> None:
    """Scheduler entry point for whale wallet tracking."""
    logger.info("Starting whale tracking job")
    try:
        tracker = WhaleTracker()
        whales = await tracker.discover_whales()
        signals = await tracker.generate_copy_signals()
        logger.info(
            "Whale tracking complete: %d whales, %d signals",
            len(whales),
            len(signals),
        )
    except Exception:
        logger.exception("Whale tracking job failed")
