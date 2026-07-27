"""HFT Signal Generator — real-time signal detection from orderbook/whale/arb data.

Detects trading signals from multiple data sources:
1. Orderbook snapshots — spread compression, bid/ask imbalances, price momentum
2. Whale activity — large wallet movements on-chain
3. Cross-market arbitrage — price divergences between Polymarket/Kalshi
4. Probability arbitrage — mispriced YES/NO pairs

Each detector runs independently and emits typed HFTSignal objects to the
event bus for consumption by HFTExecutor.

Integration:
    signal_gen = HFTSignalGenerator(orderbook_router)
    await signal_gen.start()    # begins all detector loops
    await signal_gen.stop()     # graceful shutdown

    # Subscribe to signals
    from backend.core.event_bus import subscribe_handler
    subscribe_handler("hft_signal", my_handler)
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Optional

from backend.config import settings
from backend.strategies.types_hft import HFTSignal, ArbOpportunity, WhaleActivity
from backend.monitoring.hft_metrics import hft_latency_ms

from loguru import logger


# ── Detector base ────────────────────────────────────────────────────────────

SignalHandler = Callable[[HFTSignal], Coroutine[Any, Any, None]]


@dataclass
class DetectorConfig:
    """Per-detector runtime configuration."""

    enabled: bool = True
    interval_ms: float = 100.0  # how often to scan
    min_edge: float = 0.02  # minimum edge to emit signal
    min_confidence: float = 0.3  # minimum confidence score
    cooldown_sec: float = 2.0  # debounce — same market won't re-fire within this


# ── Core generator ────────────────────────────────────────────────────────────


class HFTSignalGenerator:
    """Orchestrates all signal detectors and routes signals to the event bus.

    Usage:
        gen = HFTSignalGenerator(orderbook_router)
        await gen.start()

    The generator runs detector loops as asyncio tasks. Each detector
    analyzes market data and emits HFTSignal objects via its handler.
    """

    def __init__(
        self,
        orderbook_router: Any = None,
        handler: SignalHandler | None = None,
    ):
        self._router = orderbook_router
        self._handler = handler or self._default_handler
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self._detectors: list[BaseDetector] = []

    async def start(self) -> None:
        """Register all detectors and start their scan loops."""
        if self._running:
            return
        self._running = True

        # Build detector roster
        self._detectors = [
            SpreadCompressionDetector(self._router, self._handler),
            BidAskImbalanceDetector(self._router, self._handler),
            PriceMomentumDetector(self._router, self._handler),
            WhaleDetector(self._handler),
            ArbDetector(self._handler),
        ]

        # Start each detector as an independent async task
        for det in self._detectors:
            if det.cfg.enabled:
                task = asyncio.create_task(
                    det.run(), name=f"hft-detector-{det.__class__.__name__}"
                )
                self._tasks.append(task)
                logger.info(
                    "[hft_signal_gen] Started detector {}", det.__class__.__name__
                )

        logger.info(
            "[hft_signal_gen] Started {} detectors",
            len(self._tasks),
        )

    async def stop(self) -> None:
        """Gracefully stop all detectors."""
        self._running = False
        for det in self._detectors:
            det.stop()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("[hft_signal_gen] All detectors stopped")

    async def _default_handler(self, signal: HFTSignal) -> None:
        """Default handler: emit to event bus for HFTExecutor consumption."""
        from backend.core.event_bus import publish_event

        publish_event("hft_signal", signal.to_dict())
        logger.debug(
            "[hft_signal_gen] Emitted {} signal for market {} (edge={:.4f}, conf={:.2f})",
            signal.signal_type,
            signal.market_id,
            signal.edge,
            signal.confidence,
        )


# ── Base detector ─────────────────────────────────────────────────────────────


class BaseDetector:
    """Base class for all signal detectors.

    Subclasses implement _scan() which runs on a timer. The scan method
    collects data, analyzes it, and calls self._emit(signal) when a
    valid signal is found.
    """

    def __init__(
        self,
        handler: SignalHandler,
        config: DetectorConfig | None = None,
    ):
        self._handler = handler
        self.cfg = config or DetectorConfig()
        self._stopped = False
        self._last_emit: dict[str, float] = {}  # market_id -> timestamp
        self._emit_count = 0

    def stop(self) -> None:
        self._stopped = True

    async def run(self) -> None:
        """Main loop: scan at configured interval."""
        while not self._stopped:
            t0 = time.monotonic()
            try:
                await self._scan()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.opt(exception=True).warning(
                    "[{}] Scan error, continuing", self.__class__.__name__
                )
            elapsed = (time.monotonic() - t0) * 1000
            sleep = max(0.0, self.cfg.interval_ms - elapsed) / 1000.0
            await asyncio.sleep(sleep)

    async def _emit(self, signal: HFTSignal) -> None:
        """Emit signal if it passes cooldown and threshold checks."""
        now = time.monotonic()
        last = self._last_emit.get(signal.market_id, 0.0)
        if now - last < self.cfg.cooldown_sec:
            return
        if signal.edge < self.cfg.min_edge:
            return
        if signal.confidence < self.cfg.min_confidence:
            return

        signal.latency_ms = (time.monotonic() - (now - signal.latency_ms)) * 1000
        self._last_emit[signal.market_id] = now
        self._emit_count += 1
        hft_latency_ms.observe(signal.latency_ms)
        await self._handler(signal)

    async def _scan(self) -> None:
        """Override in subclass — one pass of signal detection."""
        ...


# ── Spread compression detector ────────────────────────────────────────────────


class SpreadCompressionDetector(BaseDetector):
    """Detect spread compression events — narrowing spreads signal liquidity.

    When the bid-ask spread compresses below HFT_SCANNER_MIN_EDGE, it
    indicates improving liquidity or converging consensus. These are
    favorable entry points for edge strategies.
    """

    def __init__(self, router: Any, handler: SignalHandler):
        super().__init__(
            handler,
            DetectorConfig(
                enabled=settings.HFT_ENABLED,
                interval_ms=50.0,
                min_edge=settings.HFT_SCANNER_MIN_EDGE,
                min_confidence=0.4,
                cooldown_sec=1.0,
            ),
        )
        self._router = router
        self._prev_spread: dict[str, float] = {}

    async def _scan(self) -> None:
        if self._router is None:
            return

        # Get all tracked markets from the router
        markets = getattr(self._router, "_snapshots", {})
        if not markets:
            return

        for market_id, snapshot in markets.items():
            try:
                bid = getattr(snapshot, "best_bid_yes", 0.0) or 0.0
                ask = getattr(snapshot, "best_ask_yes", 0.0) or 0.0
                if bid <= 0 or ask <= 0:
                    continue

                spread = (ask - bid) / max(bid, 0.001)
                prev = self._prev_spread.get(market_id, spread)
                compression = (prev - spread) / max(prev, 0.001)

                self._prev_spread[market_id] = spread

                # Detect: spread < min_edge → entry opportunity
                if spread < self.cfg.min_edge and compression > 0.3:
                    signal = HFTSignal(
                        signal_id=str(uuid.uuid4()),
                        market_id=market_id,
                        ticker=market_id,
                        signal_type="edge",
                        edge=max(0.0, self.cfg.min_edge - spread),
                        confidence=min(1.0, 0.5 + compression),
                        latency_ms=0.0,
                        metadata={
                            "detector": "spread_compression",
                            "spread": round(spread, 4),
                            "compression": round(compression, 4),
                            "bid": bid,
                            "ask": ask,
                            "source": "orderbook",
                        },
                    )
                    await self._emit(signal)

            except Exception:
                logger.opt(exception=True).debug(
                    "[spread_compression] Error processing market {}", market_id
                )


# ── Bid/ask imbalance detector ──────────────────────────────────────────────────


class BidAskImbalanceDetector(BaseDetector):
    """Detect significant bid/ask volume imbalances.

    When one side of the orderbook has significantly more volume, it
    signals directional pressure that can be exploited.
    """

    def __init__(self, router: Any, handler: SignalHandler):
        super().__init__(
            handler,
            DetectorConfig(
                enabled=settings.HFT_ENABLED,
                interval_ms=100.0,
                min_edge=0.03,
                min_confidence=0.35,
                cooldown_sec=2.0,
            ),
        )
        self._router = router

    async def _scan(self) -> None:
        if self._router is None:
            return

        markets = getattr(self._router, "_snapshots", {})
        if not markets:
            return

        for market_id, snapshot in markets.items():
            try:
                bid_vol = getattr(snapshot, "bid_volume", 0.0) or 0.0
                ask_vol = getattr(snapshot, "ask_volume", 0.0) or 0.0
                if bid_vol <= 0 or ask_vol <= 0:
                    # Fall back to level-1 depth estimation
                    bids = getattr(snapshot, "bids", None) or getattr(
                        snapshot, "bids_yes", []
                    )
                    asks = getattr(snapshot, "asks", None) or getattr(
                        snapshot, "asks_yes", []
                    )
                    if bids:
                        bid_vol = sum(float(b.get("size", 0)) for b in bids[:5])
                    if asks:
                        ask_vol = sum(float(a.get("size", 0)) for a in asks[:5])

                total = bid_vol + ask_vol
                if total < 100:  # minimum volume threshold
                    continue

                imbalance = (bid_vol - ask_vol) / total

                # Strong buying pressure
                if imbalance > 0.6:
                    signal = HFTSignal(
                        signal_id=str(uuid.uuid4()),
                        market_id=market_id,
                        ticker=market_id,
                        signal_type="edge",
                        edge=imbalance,
                        confidence=min(1.0, 0.3 + abs(imbalance)),
                        latency_ms=0.0,
                        metadata={
                            "detector": "bid_ask_imbalance",
                            "imbalance": round(imbalance, 4),
                            "bid_volume": round(bid_vol, 2),
                            "ask_volume": round(ask_vol, 2),
                            "direction": "buy_pressure",
                            "source": "orderbook",
                        },
                    )
                    await self._emit(signal)

                # Strong selling pressure
                elif imbalance < -0.6:
                    signal = HFTSignal(
                        signal_id=str(uuid.uuid4()),
                        market_id=market_id,
                        ticker=market_id,
                        signal_type="edge",
                        edge=abs(imbalance),
                        confidence=min(1.0, 0.3 + abs(imbalance)),
                        latency_ms=0.0,
                        metadata={
                            "detector": "bid_ask_imbalance",
                            "imbalance": round(imbalance, 4),
                            "bid_volume": round(bid_vol, 2),
                            "ask_volume": round(ask_vol, 2),
                            "direction": "sell_pressure",
                            "source": "orderbook",
                        },
                    )
                    await self._emit(signal)

            except Exception:
                logger.opt(exception=True).debug(
                    "[imbalance] Error processing market {}", market_id
                )


# ── Price momentum detector ─────────────────────────────────────────────────────


class PriceMomentumDetector(BaseDetector):
    """Detect short-term price momentum from orderbook midpoint changes.

    Tracks midpoint price changes over a rolling window. When the rate
    of change exceeds a threshold, emits a momentum signal.
    """

    def __init__(self, router: Any, handler: SignalHandler):
        super().__init__(
            handler,
            DetectorConfig(
                enabled=settings.HFT_ENABLED,
                interval_ms=200.0,
                min_edge=0.01,
                min_confidence=0.3,
                cooldown_sec=3.0,
            ),
        )
        self._router = router
        self._price_history: dict[str, list[tuple[float, float]]] = defaultdict(
            lambda: []
        )
        self._window_size = 5  # number of samples to track momentum

    async def _scan(self) -> None:
        if self._router is None:
            return

        markets = getattr(self._router, "_snapshots", {})
        now = time.time()

        for market_id, snapshot in markets.items():
            try:
                bid = getattr(snapshot, "best_bid_yes", 0.0) or 0.0
                ask = getattr(snapshot, "best_ask_yes", 0.0) or 0.0
                if bid <= 0 or ask <= 0:
                    continue

                mid = (bid + ask) / 2.0
                history = self._price_history[market_id]
                history.append((now, mid))

                # Keep only recent samples within a 5-second window
                cutoff = now - 5.0
                self._price_history[market_id] = [
                    (t, p) for t, p in history if t > cutoff
                ]

                if len(self._price_history[market_id]) < self._window_size:
                    continue

                oldest = self._price_history[market_id][0][1]
                newest = self._price_history[market_id][-1][1]
                change_pct = (newest - oldest) / max(oldest, 0.001)

                # Significant momentum in either direction
                if abs(change_pct) > self.cfg.min_edge:
                    signal = HFTSignal(
                        signal_id=str(uuid.uuid4()),
                        market_id=market_id,
                        ticker=market_id,
                        signal_type="edge",
                        edge=abs(change_pct),
                        confidence=min(1.0, 0.3 + abs(change_pct) * 5),
                        latency_ms=0.0,
                        metadata={
                            "detector": "price_momentum",
                            "change_pct": round(change_pct, 6),
                            "mid_start": round(oldest, 4),
                            "mid_end": round(newest, 4),
                            "direction": "up" if change_pct > 0 else "down",
                            "source": "orderbook",
                        },
                    )
                    await self._emit(signal)

            except Exception:
                logger.opt(exception=True).debug(
                    "[momentum] Error processing market {}", market_id
                )


# ── Whale detector ──────────────────────────────────────────────────────────────


class WhaleDetector(BaseDetector):
    """Detect whale activity from external monitoring sources.

    Monitors the event bus for whale-related events (large trades,
    wallet movements) and converts them to HFTSignal objects.

    NOTE: This detector relies on external whale monitoring data being
    published to the event bus. In the current system, the primary
    whale detection comes from the orderbook imbalance detector above.
    """

    def __init__(self, handler: SignalHandler):
        super().__init__(
            handler,
            DetectorConfig(
                enabled=settings.HFT_ENABLED,
                interval_ms=500.0,
                min_edge=settings.HFT_WHALE_MIN_SIZE_USD / 100000.0,
                min_confidence=settings.HFT_WHALE_MIN_SCORE,
                cooldown_sec=5.0,
            ),
        )

    async def _scan(self) -> None:
        # Scan for whale events dispatched to event bus
        # In production, this would also subscribe to mempool/chain data
        # For now, this is a polling placeholder that checks registered
        # whale activity records if any were submitted via the event bus.
        try:
            from backend.core.event_bus import get_event_history

            events = get_event_history()
            for event in events[-50:]:  # check last 50 events
                if event.get("event_type") == "whale_activity":
                    data = event.get("data", {})
                    activity = WhaleActivity(
                        wallet=data.get("wallet", ""),
                        action=data.get("action", "BUY"),
                        size=float(data.get("size", 0)),
                        market=data.get("market", ""),
                        score=float(data.get("score", 0)),
                        timestamp=float(data.get("timestamp", 0)),
                        tx_hash=data.get("tx_hash"),
                    )

                    if not activity.is_whale(
                        min_size=settings.HFT_WHALE_MIN_SIZE_USD,
                        min_score=settings.HFT_WHALE_MIN_SCORE,
                    ):
                        continue

                    signal = HFTSignal(
                        signal_id=str(uuid.uuid4()),
                        market_id=activity.market,
                        ticker=activity.market,
                        signal_type="whale",
                        edge=activity.score,
                        confidence=activity.score,
                        latency_ms=0.0,
                        metadata={
                            "detector": "whale",
                            "wallet": activity.wallet,
                            "action": activity.action,
                            "size": activity.size,
                            "score": activity.score,
                            "tx_hash": activity.tx_hash,
                            "source": "onchain",
                        },
                    )
                    await self._emit(signal)

        except Exception:
            # get_event_history may not be available; silence
            pass


# ── Arbitrage detector ──────────────────────────────────────────────────────────


class ArbDetector(BaseDetector):
    """Detect cross-market and probability arbitrage opportunities.

    For prediction markets, probability arb exists when YES+NO != 1.0
    across different platforms or orderbooks. This detector watches
    for these deviations and emits arb signals.

    Currently a framework — full cross-exchange arb requires dual
    orderbook subscriptions (Polymarket + Kalshi/etc).
    """

    def __init__(self, handler: SignalHandler):
        super().__init__(
            handler,
            DetectorConfig(
                enabled=settings.HFT_ENABLED,
                interval_ms=500.0,
                min_edge=settings.HFT_ARB_MIN_PROFIT,
                min_confidence=0.5,
                cooldown_sec=3.0,
            ),
        )

    async def _scan(self) -> None:
        # Arb scanning requires dual orderbook data (Polymarket + Kalshi
        # or Polymarket YES/NO on different markets). The current system
        # has single-venue orderbook data.
        #
        # This detector watches for arb opportunities submitted via the
        # event bus by external scanners, or can be extended with
        # cross-exchange price comparison logic.
        try:
            from backend.core.event_bus import get_event_history

            events = get_event_history()
            for event in events[-50:]:
                if event.get("event_type") == "arb_opportunity":
                    data = event.get("data", {})
                    opp = ArbOpportunity(
                        market_id=data.get("market_id", ""),
                        arb_type=data.get("arb_type", "prob_arb"),
                        yes_price=float(data.get("yes_price", 0)),
                        no_price=float(data.get("no_price", 0)),
                        profit=float(data.get("profit", 0)),
                        fees=float(data.get("fees", 0)),
                        net_profit=float(data.get("net_profit", 0)),
                        confidence=float(data.get("confidence", 0)),
                    )

                    if opp.net_profit < self.cfg.min_edge:
                        continue

                    signal = HFTSignal(
                        signal_id=str(uuid.uuid4()),
                        market_id=opp.market_id,
                        ticker=opp.market_id,
                        signal_type="arb",
                        edge=opp.net_profit,
                        confidence=opp.confidence,
                        latency_ms=0.0,
                        metadata={
                            "detector": "arb",
                            "arb_type": opp.arb_type,
                            "yes_price": opp.yes_price,
                            "no_price": opp.no_price,
                            "profit": opp.profit,
                            "net_profit": opp.net_profit,
                            "fees": opp.fees,
                            "source": "cross_market",
                        },
                    )
                    await self._emit(signal)

        except Exception:
            pass


# ── Convenience factory ─────────────────────────────────────────────────────────


_default_generator: HFTSignalGenerator | None = None


async def start_default_generator(orderbook_router: Any = None) -> HFTSignalGenerator:
    """Start the default singleton signal generator."""
    global _default_generator
    if _default_generator is not None:
        return _default_generator
    _default_generator = HFTSignalGenerator(orderbook_router)
    await _default_generator.start()
    return _default_generator


async def stop_default_generator() -> None:
    """Stop the default singleton signal generator."""
    global _default_generator
    if _default_generator is not None:
        await _default_generator.stop()
        _default_generator = None
