"""Copy trading routes - leaderboard, signals, positions."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.models.database import get_db, Signal, CopyTraderEntry
from backend.config import settings
from loguru import logger
router = APIRouter(prefix="/copy", tags=["copy_trading"])


class ScoredTraderResponse(BaseModel):
    wallet: str
    pseudonym: str
    profit_30d: float
    win_rate: float
    total_trades: int
    unique_markets: int
    estimated_bankroll: float
    score: float
    market_diversity: float


class CopySignalResponse(BaseModel):
    source_wallet: str
    our_side: str
    our_outcome: str
    our_size: float
    market_price: float
    trader_score: float
    reasoning: str
    condition_id: str
    title: str
    timestamp: str


@router.get("/leaderboard", response_model=List[ScoredTraderResponse])
async def get_copy_leaderboard(limit: int = 100):
    """Return top traders from Polymarket Data API leaderboard."""
    limit = min(limit, 500)
    import httpx

    DATA_API = settings.DATA_API_URL
    all_traders = []

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Fetch in pages of 50 (API max)
            for offset in range(0, limit, 50):
                page_limit = min(50, limit - offset)
                resp = await client.get(
                    f"{DATA_API}/{settings.DATA_API_VERSION}/leaderboard",
                    params={
                        "timePeriod": "all",
                        "orderBy": "PNL",
                        "category": "OVERALL",
                        "limit": page_limit,
                        "offset": offset,
                    },
                )
                resp.raise_for_status()
                page = resp.json()
                if not page:
                    break
                all_traders.extend(page)
                if len(page) < page_limit:
                    break

        result = []
        for t in all_traders:
            wallet = t.get("proxyWallet", t.get("address", t.get("wallet", "")))
            profit = float(t.get("pnl", t.get("profit", 0)))
            volume = float(t.get("vol", t.get("volume", 0)))
            markets = int(t.get("numMarkets", t.get("markets_traded", 0)))
            trades = int(t.get("numTrades", t.get("total_trades", 0)))

            win_rate = 0.0
            if trades > 0:
                wins = int(t.get("numWins", 0))
                win_rate = wins / trades if trades > 0 else 0.0

            # Score: weighted composite of profit, win rate, market diversity
            score = 0.0
            if profit > 0:
                score += min(profit / 10000, 1.0) * 0.4
            score += win_rate * 0.3
            score += min(markets / 100, 1.0) * 0.3

            pseudonym = t.get("username", t.get("pseudonym", ""))
            if not pseudonym:
                pseudonym = (
                    f"{wallet[:6]}...{wallet[-4:]}" if len(wallet) > 10 else wallet
                )

            result.append(
                ScoredTraderResponse(
                    wallet=wallet,
                    pseudonym=pseudonym,
                    profit_30d=round(profit, 2),
                    win_rate=round(win_rate, 3),
                    total_trades=trades,
                    unique_markets=markets,
                    estimated_bankroll=round(volume * 0.1, 2),
                    score=round(score, 3),
                    market_diversity=round(min(markets / 100, 1.0), 3),
                )
            )

        logger.info(f"Returning {len(result)} traders from Polymarket Data API")
        return result

    except Exception as e:
        logger.error(f"Leaderboard fetch failed, trying scraper fallback: {e}")
        # Fallback to scraper
        try:
            from backend.data.polymarket_scraper import fetch_real_leaderboard

            traders = await fetch_real_leaderboard(limit=limit)
            if traders:
                return [
                    ScoredTraderResponse(
                        wallet=t["wallet"],
                        pseudonym=t.get("pseudonym", ""),
                        profit_30d=round(t.get("profit_30d", 0), 2),
                        win_rate=round(t.get("win_rate", 0), 3),
                        total_trades=t.get("total_trades", 0),
                        unique_markets=t.get("unique_markets", 0),
                        estimated_bankroll=round(t.get("estimated_bankroll", 0), 2),
                        score=round(t.get("score", 0), 3),
                        market_diversity=round(t.get("market_diversity", 0), 3),
                    )
                    for t in traders
                ]
        except Exception as e:
            logger.warning(f"Leaderboard scraper fallback failed: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch leaderboard: {str(e)}"
        )


@router.get("/signals", response_model=List[CopySignalResponse])
async def get_copy_signals(limit: int = 20):
    """Return recent copy trade signals from the DB."""
    limit = min(limit, 500)
    from backend.db.utils import get_db_session
    try:
        with get_db_session() as db:
            signals = (
                db.query(Signal)
                .filter(Signal.market_type == "copy")
                .order_by(Signal.timestamp.desc())
                .limit(limit)
                .all()
            )
            return [
                CopySignalResponse(
                    source_wallet=s.sources[0] if s.sources else "",
                    our_side=s.direction,
                    our_outcome="YES",
                    our_size=s.suggested_size,
                    market_price=s.market_price,
                    trader_score=s.confidence * 100,
                    reasoning=s.reasoning,
                    condition_id=s.market_ticker,
                    title=s.market_ticker,
                    timestamp=s.timestamp.isoformat(),
                )
                for s in signals
            ]
    except Exception as e:
        logger.warning(f"Copy signals fetch failed: {e}")
        return []


@router.get("/positions")
async def get_copy_trader_positions(
    db: Session = Depends(get_db),
):
    """Return recent copy trader position entries from DB."""
    entries = (
        db.query(CopyTraderEntry)
        .order_by(CopyTraderEntry.opened_at.desc())
        .limit(100)
        .all()
    )
    return [
        {
            "wallet": e.wallet,
            "condition_id": e.condition_id,
            "side": e.side,
            "size": e.size,
            "opened_at": e.opened_at.isoformat() if e.opened_at else None,
        }
        for e in entries
    ]


@router.get("/status")
async def get_copy_trader_status(
    db: Session = Depends(get_db),
):
    """Return copy trader status including tracked wallets and recent signals."""
    try:
        wallet_entries = (
            db.query(
                CopyTraderEntry.wallet,
                func.count(CopyTraderEntry.id).label("trades"),
                func.sum(CopyTraderEntry.pnl).label("pnl"),
            )
            .group_by(CopyTraderEntry.wallet)
            .all()
        )

        # Batch fetch all copy signals (single query)
        all_copy_signals = (
            db.query(Signal)
            .filter(Signal.market_type == "copy")
            .order_by(Signal.timestamp.desc())
            .all()
        )

        # Build lookup: addr -> first matching signal
        signal_by_addr = {}
        for s in all_copy_signals:
            if s.sources:
                for src in s.sources:
                    if isinstance(src, str) and src not in signal_by_addr:
                        signal_by_addr[src] = s

        wallet_details = []
        for addr, trades, pnl in wallet_entries:
            pseudonym = addr[:8] + "..."
            signal = signal_by_addr.get(addr)
            if signal and signal.sources and len(signal.sources) > 1:
                pseudonym = signal.sources[1] if len(signal.sources) > 1 else pseudonym

            score = min(100, (trades * 2) + (pnl if pnl > 0 else 0))
            wallet_details.append(
                {
                    "address": addr,
                    "pseudonym": pseudonym,
                    "score": score,
                    "profit_30d": pnl or 0.0,
                }
            )

        recent_signals = (
            db.query(Signal)
            .filter(Signal.market_type == "copy")
            .order_by(Signal.timestamp.desc())
            .limit(10)
            .all()
        )

        signals_data = [
            {
                "market_ticker": s.market_ticker,
                "direction": s.direction,
                "edge": s.edge,
                "confidence": s.confidence,
                "timestamp": s.timestamp.isoformat() if s.timestamp else None,
            }
            for s in recent_signals
        ]

        return {
            "enabled": len(wallet_details) > 0,
            "tracked_wallets": len(wallet_details),
            "wallet_details": wallet_details,
            "recent_signals": signals_data,
            "status": "active" if len(wallet_details) > 0 else "idle",
            "errors": [],
        }
    except Exception as e:
        logger.error(f"Error getting copy trader status: {e}")
        return {
            "enabled": False,
            "tracked_wallets": 0,
            "wallet_details": [],
            "recent_signals": [],
            "status": "error",
            "errors": [{"source": "database", "message": str(e)}],
        }
