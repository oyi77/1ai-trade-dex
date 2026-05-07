"""
Auto-discover profitable Polymarket wallets from leaderboard.

Scans leaderboard, ranks by P&L, and suggests wallets to copy.
"""

import logging
from typing import List, Dict, Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


async def scan_leaderboard_for_profitable_wallets(
    min_trades: int = 50,
    min_win_rate: float = 0.55,
    min_pnl: float = 1000,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    Scan Polymarket leaderboard for profitable wallets using REAL data.

    Args:
        min_trades: Minimum number of trades required
        min_win_rate: Minimum win rate (0.55 = 55%)
        min_pnl: Minimum total P&L in USD
        limit: Maximum number of wallets to return

    Returns:
        List of profitable wallets with stats from Polymarket leaderboard
    """
    from backend.data.polymarket_scraper import fetch_real_leaderboard

    # Fetch REAL leaderboard data from Polymarket
    traders = await fetch_real_leaderboard(limit=limit)

    # Transform to expected format
    profitable_wallets = []
    for trader in traders:
        # Apply filters
        if trader.get("total_trades", 0) < min_trades:
            continue
        if trader.get("score", 0) < min_win_rate:
            continue
        if trader.get("profit_30d", 0) < min_pnl:
            continue

        profitable_wallets.append(
            {
                "address": trader.get("wallet", ""),
                "pnl": trader.get("profit_30d", 0),
                "win_rate": trader.get("score", 0),  # Using score as proxy for win rate
                "total_trades": trader.get("total_trades", 0),
                "last_active": datetime.now(timezone.utc),  # Leaderboard is current
                "markets": ["BTC", "Politics", "Sports"],  # Default tags
            }
        )

    return profitable_wallets


async def auto_suggest_wallets_to_copy(
    db,
    current_wallets: List[str],
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """
    Suggest new wallets to copy based on profitability.

    Filters out already configured wallets and ranks by edge.
    """
    profitable_wallets = await scan_leaderboard_for_profitable_wallets(limit=limit * 2)

    # Filter out already configured wallets
    new_wallets = [w for w in profitable_wallets if w["address"] not in current_wallets]

    # Rank by combined score (P&L * win_rate)
    ranked = sorted(
        new_wallets,
        key=lambda w: w["pnl"] * w["win_rate"],
        reverse=True,
    )

    return ranked[:limit]


def calculate_wallet_edge_score(wallet: Dict[str, Any]) -> float:
    """
    Calculate a composite edge score for a wallet.

    Higher score = better copy candidate.
    """
    pnl_weight = 0.4
    win_rate_weight = 0.3
    trade_count_weight = 0.2
    recency_weight = 0.1

    # Normalize P&L (log scale)
    import math

    pnl_score = math.log(max(wallet["pnl"], 1)) / 10

    # Win rate (0-1)
    win_rate_score = wallet["win_rate"]

    # Trade count (diminishing returns after 100)
    trade_score = min(wallet["total_trades"] / 100, 1.0)

    # Recency (more recent activity = better)
    days_since_active = (datetime.now(timezone.utc) - wallet["last_active"]).days
    recency_score = max(0, 1 - days_since_active / 30)

    edge_score = (
        pnl_score * pnl_weight
        + win_rate_score * win_rate_weight
        + trade_score * trade_count_weight
        + recency_score * recency_weight
    )

    return edge_score


async def auto_add_profitable_wallets(
    db,
    max_wallets: int = 20,
    auto_enable: bool = False,
) -> Dict[str, Any]:
    """
    Automatically discover and add profitable wallets.

    Args:
        db: Database session
        max_wallets: Maximum number of wallets to auto-add
        auto_enable: Whether to auto-enable the wallets for copying

    Returns:
        Summary of added wallets
    """
    from backend.models.database import WalletConfig

    # Get currently configured wallets
    current = db.query(WalletConfig).filter(WalletConfig.enabled.is_(True)).all()
    current_addresses = [w.address for w in current]

    # Get suggestions
    suggested = await auto_suggest_wallets_to_copy(
        db,
        current_addresses,
        limit=max_wallets,
    )

    # Add to database
    added = []
    for wallet in suggested:
        existing = (
            db.query(WalletConfig)
            .filter(WalletConfig.address == wallet["address"])
            .first()
        )

        if not existing:
            new_wallet = WalletConfig(
                address=wallet["address"],
                pseudonym=f"Auto-{wallet['address'][:6]}",
                enabled=auto_enable,
                tags=["auto-discovered"],
                notes=f"Auto-added: P&L ${wallet['pnl']:,.0f}, Win Rate {wallet['win_rate']:.1%}",
            )
            db.add(new_wallet)
            added.append(wallet)

    db.commit()

    return {
        "added_count": len(added),
        "wallets": added,
        "total_pnl": sum(w["pnl"] for w in added),
        "avg_win_rate": sum(w["win_rate"] for w in added) / len(added) if added else 0,
    }
