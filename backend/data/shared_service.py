"""Shared Data Service — internal API for MiroFish. Mounted at /api/v1/data via main.py."""

from fastapi import APIRouter, Header, HTTPException, Query, Path
from typing import Optional
import time

from loguru import logger

router = APIRouter(prefix="/data", tags=["shared"])

REQUEST_COUNTER: dict[str, float] = {}
RATE_LIMIT = 100
RATE_WINDOW = 1.0


def _check_rate_limit(client_id: str) -> bool:
    now = time.time()
    REQUEST_COUNTER[client_id] = now
    # Prune stale entries to prevent unbounded growth
    if len(REQUEST_COUNTER) > RATE_LIMIT * 2:
        stale = [k for k, v in REQUEST_COUNTER.items() if now - v >= RATE_WINDOW]
        for k in stale:
            del REQUEST_COUNTER[k]
    recent = sum(1 for v in REQUEST_COUNTER.values() if now - v < RATE_WINDOW)
    return recent <= RATE_LIMIT


async def _get_markets_polymarket(limit: int = 100) -> list[dict]:
    try:
        from backend.data.gamma import fetch_markets
        return await fetch_markets(limit=limit)
    except Exception as exc:
        logger.exception("shared_service polymarket markets fetch failed")
        raise HTTPException(status_code=500, detail=f"Gamma API error: {exc}")


async def _get_market_price(condition_id: str) -> dict:
    try:
        markets = await _get_markets_polymarket(limit=100)
        for m in markets:
            if m.get("conditionId") == condition_id:
                prices = m.get("outcomePrices", [])
                return {
                    "condition_id": condition_id,
                    "yes_price": float(prices[0]) if len(prices) > 0 else 0.5,
                    "no_price": float(prices[1]) if len(prices) > 1 else 0.5,
                    "volume": float(m.get("volume", 0) or 0),
                    "liquidity": float(m.get("liquidity", 0) or 0),
                    "question": m.get("question", ""),
                }
        raise HTTPException(status_code=404, detail=f"Market {condition_id} not found")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("shared_service market price lookup failed for condition_id=%s", condition_id)
        raise HTTPException(status_code=500, detail=str(exc))


async def _get_orderbook(condition_id: str) -> dict:
    try:
        from backend.data.orderbook_ws import OrderbookWS
        ob = OrderbookWS(condition_id)
        await ob.connect()
        snapshot = ob.get_snapshot()
        await ob.disconnect()
        return snapshot
    except Exception:
        logger.exception("shared_service orderbook fetch failed for condition_id=%s", condition_id)
        return {"condition_id": condition_id, "bids": [], "asks": [], "spread": 0.0}


async def _get_markets_kalshi(limit: int = 100) -> list[dict]:
    try:
        from backend.data.kalshi_client import KalshiClient
        client = KalshiClient()
        return await client.get_markets(params={"limit": limit})
    except Exception as exc:
        logger.exception("shared_service kalshi markets fetch failed")
        raise HTTPException(status_code=500, detail=f"Kalshi API error: {exc}")


@router.get("/polymarket/markets")
async def get_polymarket_markets(
    limit: int = Query(default=100, ge=1, le=1000),
    active: bool = Query(default=True),
    x_api_key: Optional[str] = Header(None),
):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key")
    if not _check_rate_limit(x_api_key):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    return await _get_markets_polymarket(limit=limit)


@router.get("/polymarket/price/{condition_id}")
async def get_market_price(
    condition_id: str = Path(...),
    x_api_key: Optional[str] = Header(None),
):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key")
    if not _check_rate_limit(x_api_key):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    return await _get_market_price(condition_id)


@router.get("/polymarket/orderbook/{condition_id}")
async def get_orderbook(
    condition_id: str = Path(...),
    x_api_key: Optional[str] = Header(None),
):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key")
    if not _check_rate_limit(x_api_key):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    return await _get_orderbook(condition_id)


@router.get("/kalshi/markets")
async def get_kalshi_markets(
    limit: int = Query(default=100, ge=1, le=1000),
    x_api_key: Optional[str] = Header(None),
):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key")
    if not _check_rate_limit(x_api_key):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    return await _get_markets_kalshi(limit=limit)
