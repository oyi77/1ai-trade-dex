"""
Wallet Scanner — Discover profitable Polymarket traders.

Discovery methods:
A) Gamma API market participants
B) Blockscout whale tracking (large PUSD transfers)
C) Polymarket leaderboard
D) Known profitable wallets (seeded)
"""

import json
import time
import logging
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

BLOCKSCOUT_API = "https://polygon.blockscout.com/api/v2"
PUSD = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
CACHE_DIR = Path("data/scanner_cache")
SCAN_CACHE_TTL = 3600  # 1 hour


@dataclass
class TraderScore:
    wallet: str
    proxy: Optional[str] = None
    pnl: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    volume: float = 0.0
    sharpe: float = 0.0
    source_method: str = ""


async def find_profitable_traders(
    min_volume: float = 1000.0,
    min_trades: int = 50,
    max_results: int = 50,
    sort_by: str = "pnl",
) -> List[TraderScore]:
    """
    Discover profitable wallets via multiple methods.
    Pipeline: collect -> deduplicate -> rapid analysis -> rank.
    """
    # Check cache
    cached = _load_scan_cache()
    if cached:
        return _filter_and_sort(cached, min_volume, min_trades, max_results, sort_by)

    candidates = set()

    # Method A: Gamma API top markets -> orderbook participants
    gamma_wallets = await _discover_from_gamma()
    candidates.update(gamma_wallets)

    # Method B: Blockscout whale tracking
    whale_wallets = await _discover_whales()
    candidates.update(whale_wallets)

    # Deduplicate
    candidates = {w.lower() for w in candidates if w}

    # Score each candidate (rapid analysis)
    scored = []
    for wallet in list(candidates)[:200]:  # Cap to avoid too many API calls
        try:
            from backend.data.wallet_history import get_all_closed_positions

            positions = await get_all_closed_positions(wallet)
            if not positions:
                continue

            total_volume = sum(float(p.get("totalBought", 0)) for p in positions)
            total_pnl = sum(float(p.get("realizedPnl", 0)) for p in positions)
            wins = sum(1 for p in positions if float(p.get("realizedPnl", 0)) > 0)
            win_rate = wins / len(positions) if positions else 0

            if total_volume < min_volume or len(positions) < min_trades:
                continue

            scored.append(
                TraderScore(
                    wallet=wallet,
                    pnl=total_pnl,
                    win_rate=win_rate,
                    total_trades=len(positions),
                    volume=total_volume,
                    source_method="scan",
                )
            )
        except Exception as e:
            logger.debug("Failed to score %s: %s", wallet, e)
            continue

    # Cache results
    _save_scan_cache(scored)

    return _filter_and_sort(scored, min_volume, min_trades, max_results, sort_by)


async def _discover_from_gamma() -> set:
    """Get wallets from Gamma API top markets."""
    wallets = set()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{settings.GAMMA_API_URL}/markets",
                params={"limit": 20, "active": True},
            )
            if resp.status_code == 200:
                markets = resp.json()
                for market in markets[:10]:
                    cid = market.get("conditionId", "")
                    if cid:
                        try:
                            tokens = market.get("tokens", [{}])
                            token_id = tokens[0].get("token_id", "") if tokens else ""
                            if not token_id:
                                continue
                            book_resp = await client.get(
                                f"{settings.CLOB_API_URL}/book",
                                params={"token_id": token_id},
                            )
                            if book_resp.status_code == 200:
                                book = book_resp.json()
                                for order in (
                                    book.get("bids", []) + book.get("asks", [])
                                )[:5]:
                                    addr = order.get("owner", "")
                                    if addr:
                                        wallets.add(addr)
                        except Exception as e:
                            logger.debug(
                                "Gamma orderbook parse failed for %s: %s", cid, e
                            )
    except Exception as e:
        logger.warning("Gamma discovery failed: %s", e)
    return wallets


async def _discover_whales(min_usd: float = 10000) -> set:
    """Get wallets from Blockscout large PUSD transfers."""
    wallets = set()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{BLOCKSCOUT_API}/tokens/{PUSD}/transfers",
                params={"limit": 50},
            )
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("items", []):
                    value = int(item.get("total", {}).get("value", 0)) / 1e6
                    if value >= min_usd:
                        from_addr = item.get("from", {}).get("address", "")
                        to_addr = item.get("to", {}).get("address", "")
                        if from_addr:
                            wallets.add(from_addr)
                        if to_addr:
                            wallets.add(to_addr)
    except Exception as e:
        logger.warning("Whale discovery failed: %s", e)
    return wallets


def _filter_and_sort(traders, min_vol, min_trades, max_results, sort_by):
    filtered = [
        t for t in traders if t.volume >= min_vol and t.total_trades >= min_trades
    ]
    reverse = True
    if sort_by == "pnl":
        filtered.sort(key=lambda t: t.pnl, reverse=reverse)
    elif sort_by == "win_rate":
        filtered.sort(key=lambda t: t.win_rate, reverse=reverse)
    elif sort_by == "volume":
        filtered.sort(key=lambda t: t.volume, reverse=reverse)
    elif sort_by == "sharpe":
        filtered.sort(key=lambda t: t.sharpe, reverse=reverse)
    return filtered[:max_results]


def _load_scan_cache():
    cache_file = CACHE_DIR / "scan_results.json"
    if not cache_file.exists():
        return None
    try:
        data = json.loads(cache_file.read_text())
        if time.time() - data.get("timestamp", 0) < SCAN_CACHE_TTL:
            return [TraderScore(**t) for t in data.get("traders", [])]
        return None
    except Exception as exc:
        logger.debug("Scan cache read failed: %s", exc)
        return None


def _save_scan_cache(traders):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / "scan_results.json"
    cache_file.write_text(
        json.dumps(
            {
                "timestamp": time.time(),
                "traders": [
                    {
                        "wallet": t.wallet,
                        "proxy": t.proxy,
                        "pnl": t.pnl,
                        "win_rate": t.win_rate,
                        "total_trades": t.total_trades,
                        "volume": t.volume,
                        "sharpe": t.sharpe,
                        "source_method": t.source_method,
                    }
                    for t in traders
                ],
            }
        )
    )
