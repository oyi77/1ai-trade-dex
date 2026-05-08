"""Arbitrage detection routes."""
from fastapi import APIRouter, Depends
from typing import Dict
import time as _time
import logging

from backend.api.auth import require_admin
from backend.core.arbitrage_detector import ArbitrageDetector
from backend.core.market_scanner import fetch_all_active_markets

logger = logging.getLogger("trading_bot")
router = APIRouter(prefix="/arbitrage", tags=["arbitrage"])

# In-memory cache for arbitrage scans (60s TTL)
_arb_cache: Dict = {"timestamp": 0.0, "data": []}


@router.get("/opportunities")
async def get_arbitrage_opportunities():
    """Live arbitrage scan over recent Polymarket Gamma markets, cached 60s."""
    now = _time.time()
    if now - _arb_cache["timestamp"] < 60 and _arb_cache["data"]:
        return {"opportunities": _arb_cache["data"], "cached": True}

    try:
        markets = await fetch_all_active_markets(limit=200)
        detector = ArbitrageDetector()
        market_dicts = [
            {
                "market_id": m.ticker or m.slug,
                "yes_price": m.yes_price,
                "no_price": m.no_price,
                "question": m.question,
            }
            for m in markets
        ]
        ops = detector.scan_all(market_dicts)[:25]
        data = [op.__dict__ for op in ops]
        _arb_cache["timestamp"] = now
        _arb_cache["data"] = data
        return {"opportunities": data, "cached": False, "scanned": len(market_dicts)}
    except Exception as e:
        logger.warning(f"arbitrage scan failed: {e}")
        return {"opportunities": [], "error": str(e)}
