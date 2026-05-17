"""Market order management API for PolyEdge plugin system."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from decimal import Decimal
from typing import Optional
import uuid

from backend.api.auth import require_admin
from backend.markets.provider_registry import market_registry
from backend.markets.base_provider import NormalizedOrder
from backend.markets.order_types import OrderSide

router = APIRouter(tags=["Market Orders"])


class PlaceOrderRequest(BaseModel):
    """Request body for placing an order."""
    venue: str
    market_id: str
    side: str  # "YES" or "NO"
    size: float
    price: Optional[float] = None


@router.post("/markets/order")
async def place_order(req: PlaceOrderRequest, _=Depends(require_admin)):
    """Place an order via a market provider."""
    try:
        provider = market_registry.get(req.venue)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Venue '{req.venue}' not found or disabled")

    order = NormalizedOrder(
        client_order_id=str(uuid.uuid4()),
        market_id=req.market_id,
        side=OrderSide[req.side.upper()],
        size=Decimal(str(req.size)),
        price=Decimal(str(req.price)) if req.price is not None else None,
    )
    result = await provider.place_order(order)
    return {
        "venue_order_id": result.venue_order_id,
        "client_order_id": result.client_order_id,
        "status": result.status.value if hasattr(result.status, "value") else str(result.status),
        "filled_size": str(result.filled_size),
        "filled_avg_price": str(result.filled_avg_price),
        "remaining_size": str(result.remaining_size),
        "fees_paid": str(result.fees_paid),
    }


@router.delete("/markets/order/{venue}/{order_id}")
async def cancel_order(venue: str, order_id: str, _=Depends(require_admin)):
    """Cancel an open order."""
    try:
        provider = market_registry.get(venue)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Venue '{venue}' not found or disabled")

    cancelled = await provider.cancel_order(order_id)
    return {"cancelled": cancelled, "venue_order_id": order_id}


@router.get("/markets/order/{venue}/{order_id}")
async def get_order(venue: str, order_id: str, _=Depends(require_admin)):
    """Get status of an order."""
    try:
        provider = market_registry.get(venue)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Venue '{venue}' not found or disabled")

    try:
        result = await provider.get_order(order_id)
    except NotImplementedError:
        raise HTTPException(status_code=501, detail=f"Venue '{venue}' does not support order status")

    return {
        "venue_order_id": result.venue_order_id,
        "status": result.status.value if hasattr(result.status, "value") else str(result.status),
        "filled_size": str(result.filled_size),
        "remaining_size": str(result.remaining_size),
    }
