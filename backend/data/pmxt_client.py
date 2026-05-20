"""
PMXT unified client wrapper for PolyEdge.

Wraps the pmxt library (CCXT for prediction markets) to provide a consistent
interface for Polymarket, Kalshi, Limitless, and Hyperliquid.

PMXT runs a local sidecar server (Node.js) that handles exchange-specific
protocol details. The Python SDK communicates with it via HTTP.

Usage:
    client = PmxtClient()
    markets = await client.fetch_markets("polymarket", query="Trump")
    book = await client.fetch_order_book("polymarket", outcome_id)
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger

from backend.core.circuit_breaker import CircuitBreaker

# Supported exchanges
SUPPORTED_EXCHANGES = ("polymarket", "kalshi", "limitless", "hyperliquid")


@dataclass
class PmxtMarket:
    """Normalized market from PMXT, suitable for PolyEdge consumption."""

    market_id: str
    title: str
    platform: str
    yes_price: Optional[float] = None
    no_price: Optional[float] = None
    volume_24h: float = 0.0
    liquidity: float = 0.0
    url: str = ""
    slug: Optional[str] = None
    category: Optional[str] = None
    resolution_date: Optional[str] = None
    status: Optional[str] = None
    outcome_ids: Dict[str, str] = field(default_factory=dict)
    raw: Any = None


@dataclass
class PmxtOrderBook:
    """Normalized order book from PMXT."""

    outcome_id: str
    bids: List[Dict[str, float]] = field(default_factory=list)
    asks: List[Dict[str, float]] = field(default_factory=list)
    best_bid: Optional[float] = None
    best_ask: Optional[float] = None
    mid_price: float = 0.5

    @property
    def spread(self) -> float:
        if self.best_ask and self.best_bid:
            return self.best_ask - self.best_bid
        return 1.0


@dataclass
class PmxtOrderResult:
    """Result of placing an order via PMXT."""

    success: bool
    order_id: Optional[str] = None
    status: Optional[str] = None
    filled: float = 0.0
    remaining: float = 0.0
    price: Optional[float] = None
    error: Optional[str] = None


@dataclass
class PmxtBalance:
    """Account balance from PMXT."""

    currency: str
    total: float
    available: float
    locked: float


@dataclass
class PmxtPosition:
    """Position from PMXT."""

    market_id: str
    outcome_id: str
    outcome_label: str
    size: float
    entry_price: float
    current_price: float
    unrealized_pnl: float


_breakers: Dict[str, CircuitBreaker] = {}


def _get_breaker(exchange: str) -> CircuitBreaker:
    if exchange not in _breakers:
        _breakers[exchange] = CircuitBreaker(
            f"pmxt_{exchange}", failure_threshold=5, recovery_timeout=60.0
        )
    return _breakers[exchange]


class PmxtClient:
    """
    Unified PMXT client wrapper.

    Manages exchange client instances and provides async wrappers around
    the synchronous pmxt library calls using asyncio.to_thread.
    """

    def __init__(self) -> None:
        self._exchanges: Dict[str, Any] = {}

    def _get_exchange(self, exchange: str) -> Any:
        """Get or create a pmxt exchange client instance."""
        exchange = exchange.lower()
        if exchange not in SUPPORTED_EXCHANGES:
            raise ValueError(
                f"Unsupported exchange '{exchange}'. "
                f"Supported: {SUPPORTED_EXCHANGES}"
            )
        if exchange not in self._exchanges:
            import pmxt

            exchange_cls = {
                "polymarket": pmxt.Polymarket,
                "kalshi": pmxt.Kalshi,
                "limitless": pmxt.Limitless,
                "hyperliquid": pmxt.Hyperliquid,
            }[exchange]
            self._exchanges[exchange] = exchange_cls()
            logger.info(f"[pmxt_client] Initialized {exchange} exchange client")
        return self._exchanges[exchange]

    async def fetch_markets(
        self, exchange: str, query: Optional[str] = None, limit: int = 100
    ) -> List[PmxtMarket]:
        """Fetch markets from a given exchange via PMXT."""
        client = self._get_exchange(exchange)
        breaker = _get_breaker(exchange)

        params: Dict[str, Any] = {"limit": limit}
        if query:
            params["query"] = query

        def _fetch():
            return client.fetch_markets(params)

        try:
            raw_markets = await breaker.call(lambda: asyncio.to_thread(_fetch))
        except Exception as exc:
            logger.warning(f"[pmxt_client] fetch_markets({exchange}) failed: {exc}")
            return []

        results: List[PmxtMarket] = []
        for m in raw_markets:
            yes_outcome = m.yes if hasattr(m, "yes") and m.yes else None
            no_outcome = m.no if hasattr(m, "no") and m.no else None

            outcome_ids: Dict[str, str] = {}
            if m.outcomes:
                for o in m.outcomes:
                    outcome_ids[o.label.lower()] = o.outcome_id

            results.append(
                PmxtMarket(
                    market_id=m.market_id,
                    title=m.title,
                    platform=exchange,
                    yes_price=yes_outcome.price if yes_outcome else None,
                    no_price=no_outcome.price if no_outcome else None,
                    volume_24h=m.volume_24h or 0.0,
                    liquidity=m.liquidity or 0.0,
                    url=m.url or "",
                    slug=m.slug,
                    category=m.category,
                    status=m.status,
                    outcome_ids=outcome_ids,
                    raw=m,
                )
            )
        return results

    async def fetch_order_book(self, exchange: str, outcome_id: str) -> PmxtOrderBook:
        """Fetch order book for an outcome via PMXT."""
        client = self._get_exchange(exchange)
        breaker = _get_breaker(exchange)

        def _fetch():
            return client.fetch_order_book(outcome_id=outcome_id)

        try:
            book = await breaker.call(lambda: asyncio.to_thread(_fetch))
        except Exception as exc:
            logger.warning(
                f"[pmxt_client] fetch_order_book({exchange}, {outcome_id}) failed: {exc}"
            )
            return PmxtOrderBook(outcome_id=outcome_id)

        bids = [{"price": lvl.price, "size": lvl.size} for lvl in book.bids]
        asks = [{"price": lvl.price, "size": lvl.size} for lvl in book.asks]
        best_bid = bids[0]["price"] if bids else None
        best_ask = asks[0]["price"] if asks else None
        mid = 0.5
        if best_bid and best_ask:
            mid = (best_bid + best_ask) / 2
        elif best_bid:
            mid = best_bid
        elif best_ask:
            mid = best_ask

        return PmxtOrderBook(
            outcome_id=outcome_id,
            bids=bids,
            asks=asks,
            best_bid=best_bid,
            best_ask=best_ask,
            mid_price=mid,
        )

    async def place_order(
        self,
        exchange: str,
        market_id: str,
        outcome_id: str,
        side: str,
        amount: float,
        price: Optional[float] = None,
        order_type: str = "limit",
    ) -> PmxtOrderResult:
        """Place an order via PMXT. Requires credentials configured on the sidecar."""
        client = self._get_exchange(exchange)
        breaker = _get_breaker(exchange)

        def _place():
            built = client.build_order(
                market_id=market_id,
                outcome_id=outcome_id,
                side=side,
                type=order_type,
                amount=amount,
                price=price,
            )
            return client.submit_order(built)

        try:
            order = await breaker.call(lambda: asyncio.to_thread(_place))
            return PmxtOrderResult(
                success=True,
                order_id=order.id,
                status=order.status,
                filled=order.filled,
                remaining=order.remaining,
                price=order.price,
            )
        except Exception as exc:
            logger.error(f"[pmxt_client] place_order({exchange}) failed: {exc}")
            return PmxtOrderResult(success=False, error=str(exc))

    async def cancel_order(self, exchange: str, order_id: str) -> bool:
        """Cancel an order via PMXT."""
        client = self._get_exchange(exchange)
        breaker = _get_breaker(exchange)

        def _cancel():
            return client.cancel_order(order_id)

        try:
            await breaker.call(lambda: asyncio.to_thread(_cancel))
            return True
        except Exception as exc:
            logger.error(f"[pmxt_client] cancel_order({exchange}) failed: {exc}")
            return False

    async def fetch_balance(
        self, exchange: str, address: Optional[str] = None
    ) -> List[PmxtBalance]:
        """Fetch account balances via PMXT."""
        client = self._get_exchange(exchange)
        breaker = _get_breaker(exchange)

        def _fetch():
            return client.fetch_balance(address=address)

        try:
            raw_balances = await breaker.call(lambda: asyncio.to_thread(_fetch))
            return [
                PmxtBalance(
                    currency=b.currency,
                    total=b.total,
                    available=b.available,
                    locked=b.locked,
                )
                for b in raw_balances
            ]
        except Exception as exc:
            logger.warning(f"[pmxt_client] fetch_balance({exchange}) failed: {exc}")
            return []

    async def fetch_positions(
        self, exchange: str, address: Optional[str] = None
    ) -> List[PmxtPosition]:
        """Fetch open positions via PMXT."""
        client = self._get_exchange(exchange)
        breaker = _get_breaker(exchange)

        def _fetch():
            return client.fetch_positions(address=address)

        try:
            raw_positions = await breaker.call(lambda: asyncio.to_thread(_fetch))
            return [
                PmxtPosition(
                    market_id=p.market_id,
                    outcome_id=p.outcome_id,
                    outcome_label=p.outcome_label,
                    size=p.size,
                    entry_price=p.entry_price,
                    current_price=p.current_price,
                    unrealized_pnl=p.unrealized_pnl,
                )
                for p in raw_positions
            ]
        except Exception as exc:
            logger.warning(f"[pmxt_client] fetch_positions({exchange}) failed: {exc}")
            return []

    async def fetch_multi_platform_markets(
        self,
        exchanges: Optional[List[str]] = None,
        query: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, List[PmxtMarket]]:
        """Fetch markets from multiple platforms concurrently."""
        targets = exchanges or list(SUPPORTED_EXCHANGES)
        tasks = {ex: self.fetch_markets(ex, query=query, limit=limit) for ex in targets}
        results: Dict[str, List[PmxtMarket]] = {}
        done = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for ex, result in zip(tasks.keys(), done):
            if isinstance(result, Exception):
                logger.warning(
                    f"[pmxt_client] fetch_multi_platform({ex}) failed: {result}"
                )
                results[ex] = []
            else:
                results[ex] = result
        return results

    async def health_check(self, exchange: str) -> bool:
        """Check if a PMXT exchange client is reachable."""
        try:
            client = self._get_exchange(exchange)
            await asyncio.to_thread(lambda: client.fetch_markets({"limit": 1}))
            return True
        except Exception:
            return False
