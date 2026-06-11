"""APEX Strategy — structural edge detection and execution engine.

Orchestrates the full APEX pipeline: scan markets → detect edges → evaluate
signals → create decisions → execute through existing risk/executor stack.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from loguru import logger

from backend.config import _cfg
from backend.core.edge.edge_model import ExitSignal
from backend.core.edge.registry import EdgeRegistry
from backend.core.edge.scanners.resolution_timing import ResolutionTimingScanner
from backend.core.edge.scanners.order_book_stale import OrderBookStaleScanner
from backend.core.edge.scanners.liquidity_gap import LiquidityGapScanner
from backend.core.edge.signal_pipeline import SignalPipeline
from backend.core.edge.exit_manager import ExitManager
from backend.core.edge.calibration_tracker import CalibrationTracker
from backend.strategies.base import BaseStrategy, CycleResult, StrategyContext


class APEXStrategy(BaseStrategy):
    """Structural edge detection and execution engine."""

    name = "apex"
    description = (
        "Structural edge detection — resolution timing, liquidity gaps, "
        "stale odds, time decay. Calibrated probability models with "
        "quality-weighted Kelly sizing and unified exit management."
    )
    category = "value"

    default_params = {
        "min_edge_pp": 2.0,
        "min_confidence": 0.5,
        "max_concurrent": 10,
        "bankroll_pct": 0.08,
        "kelly_fraction": 0.25,
        "profit_target_pct": 0.025,
        "stop_loss_pct": 0.04,
        "max_hold_seconds": 7200,
        "scan_interval": 120,
    }

    def __init__(self) -> None:
        super().__init__()
        self._registry = EdgeRegistry()
        self._calibration = CalibrationTracker()
        self._pipeline: Optional[SignalPipeline] = None
        self._exit_manager: Optional[ExitManager] = None
        self._initialized = False

    def _ensure_initialized(self) -> None:
        """Lazy initialization."""
        if self._initialized:
            return
        self._registry.register(ResolutionTimingScanner())
        self._registry.register(OrderBookStaleScanner())
        self._registry.register(LiquidityGapScanner())
        self._pipeline = SignalPipeline()
        self._exit_manager = ExitManager()
        self._initialized = True
        logger.info(f"[apex] Initialized with {len(self._registry.list_enabled())} scanners")

    async def market_filter(self, markets: List) -> List:
        return markets

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        self._ensure_initialized()

        result = CycleResult(
            decisions_recorded=0, trades_attempted=0, trades_placed=0,
            errors=[], decisions=[],
        )

        # Phase 0: Load calibration
        try:
            await self._calibration.refresh_from_db(ctx.db)
        except Exception as e:
            logger.warning(f"[apex] Calibration refresh failed: {e}")

        # Phase 1: Check existing positions for exits
        try:
            exits = await self._check_exits(ctx)
            for sig in exits:
                result.decisions.append({
                    "market_ticker": sig.market_id,
                    "direction": "SELL", "decision": "SELL",
                    "exit_reason": sig.reason.value, "urgency": sig.urgency,
                })
                result.decisions_recorded += 1
        except Exception as e:
            result.errors.append(f"exit_check: {e}")

        # Phase 2: Scan for edges
        try:
            edges = await self._registry.run_all([], ctx)
        except Exception as e:
            logger.warning(f"[apex] Edge scan failed: {e}")
            result.errors.append(f"edge_scan: {e}")
            return result

        if not edges:
            return result

        # Phase 3: Evaluate through signal pipeline
        try:
            signals = await self._pipeline.evaluate(edges, ctx)
        except Exception as e:
            logger.warning(f"[apex] Signal pipeline failed: {e}")
            result.errors.append(f"pipeline: {e}")
            return result

        # Phase 4: Convert signals to decisions
        for signal in signals:
            try:
                decision = self._signal_to_decision(signal, ctx)
                if decision:
                    result.decisions.append(decision)
                    result.decisions_recorded += 1
                    result.trades_attempted += 1
            except Exception as e:
                result.errors.append(f"decision: {e}")

        # Phase 5: Log decisions
        for d in result.decisions:
            if d.get("decision") == "BUY":
                self._log_decision(d, ctx)

        return result

    async def _check_exits(self, ctx: StrategyContext) -> List[ExitSignal]:
        try:
            from backend.models.database import Trade
            open_trades = (
                ctx.db.query(Trade)
                .filter(Trade.settled.is_(False), Trade.strategy == self.name,
                        Trade.trading_mode == ctx.mode)
                .all()
            )
            if not open_trades:
                return []
            price_lookup: Dict[str, float] = {}
            for t in open_trades:
                p = await self._get_current_price(t, ctx)
                if p and t.market_ticker:
                    price_lookup[t.market_ticker] = p
            return self._exit_manager.check_all_positions(open_trades, price_lookup)
        except Exception as e:
            logger.warning(f"[apex] Exit check error: {e}")
            return []

    def _get_bankroll(self, ctx: StrategyContext) -> float:
        try:
            from backend.models.database import BotState, for_update
            state = for_update(ctx.db, ctx.db.query(BotState)).filter(
                BotState.mode == ctx.mode
            ).first()
            if state:
                if ctx.mode == "paper":
                    value = state.paper_bankroll
                elif ctx.mode == "testnet":
                    value = state.testnet_bankroll
                else:
                    value = state.bankroll
                if value is not None:
                    return max(0.0, float(value))
        except Exception:
            pass
        return float(_cfg("INITIAL_BANKROLL", 20.0))

    def _get_existing_positions(self, ctx: StrategyContext) -> List[str]:
        try:
            from backend.models.database import Trade
            trades = (
                ctx.db.query(Trade)
                .filter(Trade.settled.is_(False), Trade.trading_mode == ctx.mode)
                .all()
            )
            return [t.market_ticker for t in trades if t.market_ticker]
        except Exception:
            return []

    async def _get_current_price(self, trade, ctx: StrategyContext) -> Optional[float]:
        if ctx.clob and trade.token_id:
            try:
                price = await ctx.clob.get_mid_price(trade.token_id)
                if price and price > 0:
                    return float(price)
            except Exception as e:
                logger.debug(f"[apex] mid-price fetch failed for {trade.token_id}: {e}")
        return getattr(trade, "entry_price", None)

    def _signal_to_decision(self, signal, ctx: StrategyContext) -> Optional[Dict[str, Any]]:
        if not signal.token_id:
            return None
        bankroll = self._get_bankroll(ctx)
        params = {**self.default_params, **(ctx.params or {})}

        # Confidence check
        if signal.confidence < params["min_confidence"]:
            return None
        # Edge check
        if signal.edge_pp < params["min_edge_pp"]:
            return None

        size = signal.size_usd
        if size <= 0:
            size = min(bankroll * params["bankroll_pct"], 5.0)
        size = max(1.0, size)

        return {
            "market_ticker": signal.market_id,
            "token_id": signal.token_id,
            "direction": signal.direction,
            "decision": "BUY",
            "entry_price": signal.entry_price,
            "size": size,
            "suggested_size": size,
            "edge": signal.edge_pp / 100.0,
            "confidence": signal.confidence,
            "model_probability": signal.fair_price,
            "market_probability": signal.entry_price,
            "platform": getattr(ctx.settings, "DEFAULT_VENUE", "polymarket") if ctx.settings else "polymarket",
            "strategy_name": self.name,
            "edge_type": signal.edge_type.value,
            "profit_target_pct": signal.profit_target_pct,
            "stop_loss_pct": signal.stop_loss_pct,
            "max_hold_seconds": signal.max_hold_seconds,
        }

    def _log_decision(self, decision: Dict[str, Any], ctx: StrategyContext) -> None:
        try:
            from backend.models.database import DecisionLog
            log_row = DecisionLog(
                strategy=self.name,
                market_ticker=str(decision.get("market_ticker", ""))[:64],
                decision="BUY",
                confidence=decision.get("confidence", 0.5),
                signal_data=json.dumps(decision, default=str),
                reason=(
                    f"APEX: {decision.get('edge_type', 'unknown')} | "
                    f"edge={decision.get('edge', 0):.2%} | "
                    f"conf={decision.get('confidence', 0):.2f}"
                ),
            )
            ctx.db.add(log_row)
            ctx.db.commit()
        except Exception as e:
            logger.debug(f"[apex] DecisionLog write failed: {e}")