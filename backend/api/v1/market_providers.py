"""Market provider API router for PolyEdge plugin system."""
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional

from backend.api.auth import require_admin
from backend.markets.provider_registry import market_registry
from backend.core.plugin_errors import (
    MarketProviderNotFound, MarketProviderHasOpenPositions,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Market Providers"])


@router.get("/providers")
async def list_providers(_: Session = Depends(require_admin)):
    """List all market providers."""
    return {
        "providers": [
            {
                "name": m.name,
                "display_name": m.display_name,
                "version": m.version,
                "venue_type": m.venue_type,
                "capabilities": [c.value for c in m.capabilities],
                "supported_currencies": m.supported_currencies,
                "is_live_venue": m.is_live_venue,
                "supports_paper_mode": m.supports_paper_mode,
                "min_order_size_usd": m.min_order_size_usd,
                "maker_fee_bps": m.maker_fee_bps,
                "taker_fee_bps": m.taker_fee_bps,
                "tags": m.tags,
            }
            for m in market_registry.list_available()
        ]
    }


@router.get("/providers/{name}")
async def get_provider(name: str, _: Session = Depends(require_admin)):
    """Get details for a specific market provider."""
    try:
        provider = market_registry.get(name)
        manifest = provider.manifest()
        return {
            "name": manifest.name,
            "display_name": manifest.display_name,
            "version": manifest.version,
            "venue_type": manifest.venue_type,
            "capabilities": [c.value for c in manifest.capabilities],
            "supported_currencies": manifest.supported_currencies,
            "is_live_venue": manifest.is_live_venue,
            "supports_paper_mode": manifest.supports_paper_mode,
            "min_order_size_usd": manifest.min_order_size_usd,
            "maker_fee_bps": manifest.maker_fee_bps,
            "taker_fee_bps": manifest.taker_fee_bps,
            "required_env_vars": manifest.required_env_vars,
            "enabled": market_registry._enabled.get(name, False),
            "healthy": market_registry._health_status.get(name, False),
        }
    except MarketProviderNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/providers/{name}/balance")
async def get_provider_balance(name: str, _: Session = Depends(require_admin)):
    """Get balance for a specific provider."""
    try:
        provider = market_registry.get(name)
        balance = await provider.get_balance()
        return {
            "venue": balance.venue,
            "available_cash": str(balance.available_cash),
            "total_equity": str(balance.total_equity),
            "reserved_margin": str(balance.reserved_margin),
            "currency": balance.currency,
        }
    except MarketProviderNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/providers/{name}/positions")
async def get_provider_positions(
    name: str, market_id: Optional[str] = None, _: Session = Depends(require_admin)
):
    """Get positions for a specific provider."""
    try:
        provider = market_registry.get(name)
        positions = await provider.get_positions(market_id=market_id)
        return {
            "positions": [
                {
                    "market_id": p.market_id,
                    "side": p.side.value,
                    "size": str(p.size),
                    "avg_entry_price": str(p.avg_entry_price),
                    "venue": p.venue,
                    "current_price": str(p.current_price) if p.current_price else None,
                    "unrealized_pnl": str(p.unrealized_pnl) if p.unrealized_pnl else None,
                }
                for p in positions
            ]
        }
    except MarketProviderNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/providers/{name}/enable")
async def enable_provider(name: str, _: Session = Depends(require_admin)):
    """Enable a market provider."""
    try:
        market_registry.set_enabled(name, True)
        return {"status": "enabled", "name": name}
    except MarketProviderNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/providers/{name}/disable")
async def disable_provider(
    name: str, force: bool = False, _: Session = Depends(require_admin)
):
    """Disable a market provider. Use force=True to bypass open position check."""
    try:
        market_registry.set_enabled(name, False, force=force)
        return {"status": "disabled", "name": name}
    except MarketProviderNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except MarketProviderHasOpenPositions as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/providers/{name}/markets")
async def search_markets(
    name: str,
    query: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = Query(50, le=100),
    _: Session = Depends(require_admin),
):
    """Search markets on a specific provider."""
    try:
        provider = market_registry.get(name)
        markets = await provider.search_markets(query=query, category=category, limit=limit)
        return {"markets": markets}
    except MarketProviderNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/order")
async def place_order(
    order: dict,
    _: Session = Depends(require_admin),
):
    """Place an order via the best available provider."""
    try:
        from backend.markets.order_types import NormalizedOrder, OrderSide, OrderType

        normalized = NormalizedOrder(
            market_id=order["market_id"],
            side=OrderSide(order["side"]),
            order_type=OrderType(order.get("order_type", "market")),
            size=order["size"],
            price=order.get("price"),
            client_order_id=order.get("client_order_id"),
            time_in_force_seconds=order.get("time_in_force_seconds"),
            metadata=order.get("metadata", {}),
        )

        # Get first available provider
        providers = market_registry.list_available()
        if not providers:
            raise HTTPException(status_code=503, detail="No market providers available")

        provider = market_registry.get(providers[0].name)
        result = await provider.place_order(normalized)
        return {
            "venue_order_id": result.venue_order_id,
            "client_order_id": result.client_order_id,
            "status": result.status.value,
            "filled_size": str(result.filled_size),
            "filled_avg_price": str(result.filled_avg_price) if result.filled_avg_price else None,
            "remaining_size": str(result.remaining_size),
            "fees_paid": str(result.fees_paid),
        }
    except MarketProviderNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/order/{venue}/{order_id}")
async def cancel_order(venue: str, order_id: str, _: Session = Depends(require_admin)):
    """Cancel an order on a specific venue."""
    try:
        provider = market_registry.get(venue)
        success = await provider.cancel_order(order_id)
        return {"cancelled": success, "venue_order_id": order_id}
    except MarketProviderNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/positions")
async def aggregate_positions(_: Session = Depends(require_admin)):
    """Get aggregate positions across all providers."""
    all_positions = []
    for manifest in market_registry.list_available():
        try:
            provider = market_registry.get(manifest.name)
            positions = await provider.get_positions()
            all_positions.extend(positions)
        except Exception as e:
            logger.warning("Failed to get positions from %s: %s", manifest.name, e)
            continue
    return {
        "positions": [
            {
                "market_id": p.market_id,
                "side": p.side.value,
                "size": str(p.size),
                "avg_entry_price": str(p.avg_entry_price),
                "venue": p.venue,
            }
            for p in all_positions
        ]
    }


@router.get("/balance")
async def aggregate_balance(_: Session = Depends(require_admin)):
    """Get aggregate balance across all providers."""
    balances = []
    for manifest in market_registry.list_available():
        try:
            provider = market_registry.get(manifest.name)
            balance = await provider.get_balance()
            balances.append(balance)
        except Exception as e:
            logger.warning("Failed to get balance from %s: %s", manifest.name, e)
            continue

    total_available = sum(b.available_cash for b in balances)
    total_equity = sum(b.total_equity for b in balances)
    total_reserved = sum(b.reserved_margin for b in balances)

    return {
        "total_available_cash": str(total_available),
        "total_equity": str(total_equity),
        "total_reserved_margin": str(total_reserved),
        "providers": len(balances),
    }
