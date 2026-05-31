"""
Wallet History — Fetch positions and PnL from Polymarket Data API.

Endpoints:
- GET /closed-positions?user={proxy_wallet}&limit=50&offset=0
- GET /positions?user={proxy_wallet}
- GET /activity?user={proxy_wallet}&limit=500
- GET /value?user={proxy_wallet}
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from backend.config import settings
from backend.data.shared_client import get_shared_client

logger = logging.getLogger(__name__)

CACHE_DIR = Path("data/wallet_cache")
CACHE_TTL = 300  # 5 minutes


@dataclass
class PnLHistory:
    peak: float = 0.0
    peak_trade: Optional[dict] = None
    min: float = 0.0
    min_trade: Optional[dict] = None
    current: float = 0.0
    total_positions: int = 0
    pnl_history: list = field(default_factory=list)
    recovery_count: int = 0
    max_drawdown: float = 0.0


@dataclass
class ActivitySummary:
    total_trades: int = 0
    total_volume: float = 0.0
    recent_trades: list = field(default_factory=list)
    avg_trade_size: float = 0.0
    avg_daily_trades: float = 0.0
    most_active_day: str = ""
    last_active: Optional[float] = None


async def get_all_closed_positions(
    proxy_wallet: str,
    force_refresh: bool = False,
) -> list[dict]:
    """
    Fetch ALL closed positions with pagination.
    Offset pagination: 0, 50, 100... until empty response.
    100ms delay between pages.
    Cache: data/wallet_cache/{proxy[2:14]}_positions.json, 5min TTL.
    """
    if not force_refresh:
        cached = _check_cache(proxy_wallet, "positions")
        if cached is not None:
            return cached

    all_positions: list[dict] = []
    offset = 0
    limit = 50

    client = get_shared_client()
    while True:
        try:
            resp = await client.get(
                f"{settings.DATA_API_URL}/closed-positions",
                params={"user": proxy_wallet, "limit": limit, "offset": offset},
            )
            if resp.status_code != 200:
                logger.warning(
                    "Data API returned %d for %s", resp.status_code, proxy_wallet
                )
                break

            data = resp.json()
            if not data:
                break

            all_positions.extend(data)
            offset += limit

            await asyncio.sleep(0.1)

        except Exception as e:
            logger.error("Error fetching positions for %s: %s", proxy_wallet, e)
            break

    _save_cache(proxy_wallet, "positions", all_positions)
    return all_positions


async def get_open_positions(proxy_wallet: str) -> list[dict]:
    """Fetch current open positions."""
    try:
        client = get_shared_client()
        resp = await client.get(
            f"{settings.DATA_API_URL}/positions",
            params={"user": proxy_wallet},
        )
        if resp.status_code == 200:
            return resp.json()
        return []
    except Exception as e:
        logger.error("Error fetching open positions: %s", e)
        return []


async def get_pnl_history(proxy_wallet: str) -> PnLHistory:
    """
    Calculate cumulative PnL from closed positions.
    Algorithm: sort by timestamp, running total, find peak/min/drawdown.
    """
    positions = await get_all_closed_positions(proxy_wallet)
    if not positions:
        return PnLHistory()

    sorted_pos = sorted(positions, key=lambda p: p.get("timestamp", 0))

    history = PnLHistory(total_positions=len(sorted_pos))
    running_total = 0.0
    peak = 0.0
    min_val = 0.0

    for pos in sorted_pos:
        pnl = float(pos.get("realizedPnl", 0))
        running_total += pnl

        entry = {
            "timestamp": pos.get("timestamp"),
            "cumulative_pnl": running_total,
            "title": pos.get("title", ""),
            "trade_pnl": pnl,
        }
        history.pnl_history.append(entry)

        if running_total > peak:
            peak = running_total
            history.peak = peak
            history.peak_trade = {
                "title": pos.get("title"),
                "pnl": pnl,
                "timestamp": pos.get("timestamp"),
            }

        if running_total < min_val:
            min_val = running_total
            history.min = min_val
            history.min_trade = {
                "title": pos.get("title"),
                "pnl": pnl,
                "timestamp": pos.get("timestamp"),
            }

    history.current = running_total
    history.max_drawdown = peak - min_val

    # Count recoveries (from > $200 loss back to profit)
    in_drawdown = False
    for entry in history.pnl_history:
        if entry["cumulative_pnl"] < -200:
            in_drawdown = True
        elif in_drawdown and entry["cumulative_pnl"] > 0:
            history.recovery_count += 1
            in_drawdown = False

    return history


async def get_user_activity_summary(proxy_wallet: str) -> ActivitySummary:
    """Get activity summary from positions data."""
    positions = await get_all_closed_positions(proxy_wallet)
    if not positions:
        return ActivitySummary()

    summary = ActivitySummary(
        total_trades=len(positions),
        total_volume=sum(float(p.get("totalBought", 0)) for p in positions),
    )

    if summary.total_trades > 0:
        summary.avg_trade_size = summary.total_volume / summary.total_trades

    timestamps = [p.get("timestamp", 0) for p in positions if p.get("timestamp")]
    if timestamps:
        summary.last_active = max(timestamps)

    return summary


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


def _cache_path(proxy_wallet: str, key: str) -> Path:
    return CACHE_DIR / f"{proxy_wallet[2:14].lower()}_{key}.json"


def _check_cache(proxy_wallet: str, key: str) -> Optional[list]:
    path = _cache_path(proxy_wallet, key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        if time.time() - data.get("timestamp", 0) < CACHE_TTL:
            return data.get("data")
        return None
    except Exception as exc:
        logger.debug("Cache read failed: %s", exc)
        return None


def _save_cache(proxy_wallet: str, key: str, data: Any) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(proxy_wallet, key)
    path.write_text(json.dumps({"data": data, "timestamp": time.time()}))
