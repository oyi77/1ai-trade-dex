"""ModularStrategy — composable strategy with pluggable components.

Instead of implementing everything in one monolithic run_cycle(), a
ModularStrategy composes four independently swappable components:

    SignalGenerator  -> EdgeCalculator -> RiskManager -> OrderExecutor

Each component is an ABC that can be tested and swapped independently.
Strategies are built by selecting components rather than inheriting a
monolithic base.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from loguru import logger

from backend.strategies.base import (
    BaseStrategy,
    CycleResult,
    MarketInfo,
    StrategyContext,
)
from backend.strategies.edge_models.base import EdgeCalculator, EdgeResult
from backend.strategies.signal_generators.base import Signal, SignalGenerator


# ------------------------------------------------------------------
# RiskManager ABC
# ------------------------------------------------------------------


@dataclass
class RiskDecision:
    """Output of a risk management check."""

    approved: bool
    adjusted_size: float
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class RiskManager(ABC):
    """Abstract base for pluggable risk managers.

    Controls position sizing, exposure limits, and stop-loss/take-profit.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description."""

    @abstractmethod
    async def evaluate(
        self,
        edge_result: EdgeResult,
        ctx: StrategyContext,
        params: dict[str, Any] | None = None,
    ) -> RiskDecision:
        """Evaluate whether a trade should be taken and at what size.

        Args:
            edge_result: The edge calculation result.
            ctx: Strategy context (bankroll, db, etc.).
            params: Strategy-level parameters.

        Returns:
            RiskDecision with approval and adjusted size.
        """


# ------------------------------------------------------------------
# OrderExecutor ABC
# ------------------------------------------------------------------


@dataclass
class ExecutionResult:
    """Output of order execution."""

    success: bool
    order_id: str | None = None
    fill_price: float | None = None
    filled_size: float = 0.0
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class OrderExecutor(ABC):
    """Abstract base for pluggable order executors.

    Handles paper/live order placement against the CLOB or paper engine.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description."""

    @abstractmethod
    async def execute(
        self,
        market_ticker: str,
        direction: str,
        size: float,
        price: float,
        ctx: StrategyContext,
        params: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Place an order.

        Args:
            market_ticker: Market to trade.
            direction: "up" or "down".
            size: Position size in USD.
            price: Entry price.
            ctx: Strategy context.
            params: Strategy-level parameters.

        Returns:
            ExecutionResult with success status and order details.
        """


# ------------------------------------------------------------------
# Default Implementations
# ------------------------------------------------------------------


class DefaultRiskManager(RiskManager):
    """Simple risk manager: Kelly sizing, bankroll cap, min edge check."""

    @property
    def name(self) -> str:
        return "default"

    @property
    def description(self) -> str:
        return "Default risk manager: quarter-Kelly sizing with bankroll cap."

    async def evaluate(
        self,
        edge_result: EdgeResult,
        ctx: StrategyContext,
        params: dict[str, Any] | None = None,
    ) -> RiskDecision:
        params = params or {}
        bankroll = ctx.bankroll or 100.0
        min_edge = params.get("min_edge", 0.02)
        max_position = params.get("max_position_usd", bankroll * 0.15)
        kelly_fraction = params.get("kelly_fraction", 0.25)

        if edge_result.edge < min_edge:
            return RiskDecision(
                approved=False,
                adjusted_size=0.0,
                reason=f"Edge {edge_result.edge:.4f} below min {min_edge}",
            )

        # Quarter-Kelly sizing
        win_prob = edge_result.model_probability
        if edge_result.direction == "down":
            win_prob = 1.0 - win_prob

        # Kelly: f = (bp - q) / b where b = odds, p = win_prob, q = 1-p
        odds = 1.0 / max(0.01, edge_result.model_probability) - 1.0
        kelly = (odds * win_prob - (1.0 - win_prob)) / odds if odds > 0 else 0.0
        kelly = max(0.0, kelly) * kelly_fraction

        size = min(bankroll * kelly, max_position)
        size = max(size, 0.0)

        if size < 1.0:
            return RiskDecision(
                approved=False,
                adjusted_size=0.0,
                reason=f"Kelly size {size:.2f} below minimum",
            )

        return RiskDecision(
            approved=True,
            adjusted_size=size,
            reason=f"Quarter-Kelly {kelly:.3f}, size=${size:.2f}",
            metadata={"kelly": kelly, "bankroll": bankroll},
        )


class PaperOrderExecutor(OrderExecutor):
    """Paper trading executor: records trade in DB without CLOB interaction."""

    @property
    def name(self) -> str:
        return "paper"

    @property
    def description(self) -> str:
        return "Paper executor: records trades in DB, no real orders."

    async def execute(
        self,
        market_ticker: str,
        direction: str,
        size: float,
        price: float,
        ctx: StrategyContext,
        params: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        try:
            from backend.models.database import Trade

            trade = Trade(
                market_ticker=market_ticker,
                strategy=ctx.params.get("_strategy_name", "modular"),
                trading_mode="paper",
                direction=direction,
                entry_price=price,
                size=size,
                source="bot",
            )
            ctx.db.add(trade)
            ctx.db.commit()
            ctx.db.refresh(trade)

            return ExecutionResult(
                success=True,
                order_id=str(trade.id),
                fill_price=price,
                filled_size=size,
                metadata={"trade_id": trade.id, "mode": "paper"},
            )
        except Exception as exc:
            logger.exception(f"Paper executor failed: {exc}")
            return ExecutionResult(success=False, error=str(exc))


# ------------------------------------------------------------------
# ModularStrategy
# ------------------------------------------------------------------


class ModularStrategy(BaseStrategy, abstract=True):
    """Composable strategy that delegates to pluggable components.

    Subclasses provide (or override defaults for) four components:
        - signal_generator: SignalGenerator
        - edge_calculator: EdgeCalculator
        - risk_manager: RiskManager
        - order_executor: OrderExecutor

    The default run_cycle() orchestrates them in order:
        1. SignalGenerator.generate() -> list[Signal]
        2. For each signal: EdgeCalculator.calculate() -> EdgeResult
        3. RiskManager.evaluate() -> RiskDecision
        4. OrderExecutor.execute() -> ExecutionResult
    """

    # Component instances (set by subclass or constructor)
    _signal_generator: SignalGenerator | None = None
    _edge_calculator: EdgeCalculator | None = None
    _risk_manager: RiskManager | None = None
    _order_executor: OrderExecutor | None = None

    def __init__(
        self,
        signal_generator: SignalGenerator | None = None,
        edge_calculator: EdgeCalculator | None = None,
        risk_manager: RiskManager | None = None,
        order_executor: OrderExecutor | None = None,
    ):
        if signal_generator is not None:
            self._signal_generator = signal_generator
        if edge_calculator is not None:
            self._edge_calculator = edge_calculator
        if risk_manager is not None:
            self._risk_manager = risk_manager
        if order_executor is not None:
            self._order_executor = order_executor

    # ------------------------------------------------------------------
    # Accessors with defaults
    # ------------------------------------------------------------------

    @property
    def signal_generator(self) -> SignalGenerator:
        if self._signal_generator is None:
            raise NotImplementedError(
                f"Strategy '{self.name}' has no SignalGenerator. "
                "Pass one to the constructor or set _signal_generator."
            )
        return self._signal_generator

    @property
    def edge_calculator(self) -> EdgeCalculator:
        if self._edge_calculator is None:
            raise NotImplementedError(
                f"Strategy '{self.name}' has no EdgeCalculator. "
                "Pass one to the constructor or set _edge_calculator."
            )
        return self._edge_calculator

    @property
    def risk_manager(self) -> RiskManager:
        if self._risk_manager is None:
            self._risk_manager = DefaultRiskManager()
        return self._risk_manager

    @property
    def order_executor(self) -> OrderExecutor:
        if self._order_executor is None:
            self._order_executor = PaperOrderExecutor()
        return self._order_executor

    # ------------------------------------------------------------------
    # Swap components at runtime
    # ------------------------------------------------------------------

    def set_signal_generator(self, gen: SignalGenerator) -> None:
        self._signal_generator = gen

    def set_edge_calculator(self, calc: EdgeCalculator) -> None:
        self._edge_calculator = calc

    def set_risk_manager(self, rm: RiskManager) -> None:
        self._risk_manager = rm

    def set_order_executor(self, ex: OrderExecutor) -> None:
        self._order_executor = ex

    # ------------------------------------------------------------------
    # Core cycle: orchestrate components
    # ------------------------------------------------------------------

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        """Execute one modular trading cycle.

        Pipeline: markets -> signals -> edges -> risk -> execute
        """
        params = dict(ctx.params or {})
        params["_strategy_name"] = self.name

        # 1. Discover markets
        markets = await self._discover_markets(ctx)
        if not markets:
            return CycleResult(decisions_recorded=0, trades_attempted=0, trades_placed=0)

        # 2. Generate signals
        market_dicts = [
            {
                "ticker": m.ticker,
                "yes_price": m.yes_price,
                "no_price": m.no_price,
                **m.metadata,
            }
            for m in markets
        ]
        signals = await self.signal_generator.generate(market_dicts, params)
        if not signals:
            return CycleResult(
                decisions_recorded=0,
                trades_attempted=0,
                trades_placed=0,
                markets_scanned=len(markets),
            )

        # 3-4. For each signal: calculate edge, check risk, execute
        trades_attempted = 0
        trades_placed = 0
        errors: list[str] = []

        for signal in signals:
            try:
                # Calculate edge
                market_price = self._get_market_price(signal, markets)
                market_data = dict(signal.data)
                edge_result = await self.edge_calculator.calculate(
                    market_price, market_data, params
                )
                if edge_result is None:
                    continue

                # Risk check
                risk_decision = await self.risk_manager.evaluate(edge_result, ctx, params)
                if not risk_decision.approved:
                    continue

                trades_attempted += 1

                # Execute
                exec_result = await self.order_executor.execute(
                    market_ticker=signal.market_ticker,
                    direction=edge_result.direction,
                    size=risk_decision.adjusted_size,
                    price=market_price,
                    ctx=ctx,
                    params=params,
                )
                if exec_result.success:
                    trades_placed += 1

            except Exception as exc:
                errors.append(str(exc))
                logger.exception(f"ModularStrategy '{self.name}' signal processing failed: {exc}")

        return CycleResult(
            decisions_recorded=len(signals),
            trades_attempted=trades_attempted,
            trades_placed=trades_placed,
            errors=errors,
            markets_scanned=len(markets),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _discover_markets(self, ctx: StrategyContext) -> list[MarketInfo]:
        """Discover markets using the default market_filter.

        Subclasses can override for custom market discovery.
        """
        provider = ctx.primary_provider
        if provider is None:
            return []
        try:
            raw_markets = await provider.search_markets()
            markets = [
                MarketInfo(
                    ticker=m.get("ticker", ""),
                    slug=m.get("slug", ""),
                    category=m.get("category", ""),
                    end_date=m.get("end_date"),
                    volume=m.get("volume", 0.0),
                    liquidity=m.get("liquidity", 0.0),
                    yes_price=m.get("yes_price", 0.5),
                    no_price=m.get("no_price", 0.5),
                    question=m.get("question", ""),
                    metadata=m,
                )
                for m in (raw_markets or [])
            ]
            return await self.market_filter(markets)
        except Exception as exc:
            logger.warning(f"ModularStrategy market discovery failed: {exc}")
            return []

    @staticmethod
    def _get_market_price(signal: Signal, markets: list[MarketInfo]) -> float:
        """Get the current market price for a signal's ticker."""
        for m in markets:
            if m.ticker == signal.market_ticker:
                return m.yes_price
        # Fallback: try signal data
        return signal.data.get("yes_price", 0.5)
