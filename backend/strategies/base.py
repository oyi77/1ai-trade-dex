"""
BaseStrategy abstract contract for PolyEdge strategy plugin system.

All strategies must subclass BaseStrategy and implement:
  - name, description, category (abstract properties)
  - market_filter(markets) -> filtered markets
  - run_cycle(ctx) -> CycleResult

Subclasses are auto-registered in the strategy registry on class creation.
"""

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass
class StrategyContext:
    """Carries everything a strategy needs per cycle."""

    db: "Session"
    clob: object  # polymarket_clob.PolymarketCLOB | None for paper
    settings: object  # backend.config.Settings
    logger: logging.Logger
    params: dict  # StrategyConfig.params from DB
    mode: str  # "paper" | "testnet" | "live"

    # Providers dict mapping provider name to DataProvider instance
    if TYPE_CHECKING:
        from backend.data.provider import DataProvider
    providers: dict[str, "DataProvider"] = field(default_factory=dict)

    @property
    def primary_provider(self):
        return self.providers.get("polymarket")


@dataclass
class MarketInfo:
    """Represents a scannable market from Gamma API."""

    ticker: str
    slug: str
    category: str
    end_date: str | None
    volume: float
    liquidity: float
    yes_price: float = 0.5
    no_price: float = 0.5
    question: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class CycleResult:
    """Returned by run_cycle to report cycle outcomes."""

    decisions_recorded: int
    trades_attempted: int
    trades_placed: int
    errors: list[str] = field(default_factory=list)
    decisions: list = field(default_factory=list)
    cycle_duration_ms: float = 0.0


class BaseStrategy(ABC):
    """Abstract base class for all PolyEdge trading strategies."""

    default_params: dict = {}

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique machine-readable strategy name."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of what the strategy does."""

    @property
    @abstractmethod
    def category(self) -> str:
        """Strategy category (e.g. 'btc', 'weather', 'copy', 'ai')."""

    async def market_filter(self, markets: list[MarketInfo]) -> list[MarketInfo]:
        """
        Default implementation: filter markets using MarketWatch DB config.

        - If no MarketWatch rows exist for this strategy, returns all markets (pass-through).
        - If rows exist with source=self.name, restricts to those tickers only.

        Strategies can override for custom logic.
        """
        try:
            from backend.models.database import SessionLocal, MarketWatch

            db = SessionLocal()
            try:
                watch_rows = (
                    db.query(MarketWatch)
                    .filter(
                        MarketWatch.enabled.is_(True),
                        MarketWatch.source == self.name,
                    )
                    .all()
                )

                if not watch_rows:
                    return markets  # no config = pass-through

                watched_tickers = {row.ticker for row in watch_rows}
                return [
                    m
                    for m in markets
                    if m.ticker in watched_tickers or m.slug in watched_tickers
                ]
            finally:
                db.close()
        except Exception as e:
            # If DB fails, don't crash the strategy — return all markets
            logging.getLogger("trading_bot").warning(
                f"market_filter DB lookup failed: {e}"
            )
            return markets

    @abstractmethod
    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        """Execute one trading cycle. Must be implemented by subclasses."""

    # ------------------------------------------------------------------
    # Concrete wrapper
    # ------------------------------------------------------------------

    async def run(self, ctx: StrategyContext) -> CycleResult:
        """
        Wraps run_cycle with timing and exception handling.

        - Records wall-clock duration in CycleResult.cycle_duration_ms
        - Catches unexpected exceptions so the scheduler loop stays alive
        """
        start = time.monotonic()
        try:
            from backend.models.database import StrategyConfig
            config = ctx.db.query(StrategyConfig).filter(
                StrategyConfig.strategy_name == self.name
            ).first()
            if config is not None and not config.enabled:
                return CycleResult(
                    decisions_recorded=0,
                    trades_attempted=0,
                    trades_placed=0,
                    errors=[],
                    cycle_duration_ms=0.0,
                )
        except Exception:
            pass

        try:
            result = await self.run_cycle(ctx)
        except Exception as exc:
            duration_ms = (time.monotonic() - start) * 1000
            ctx.logger.exception(f"[{self.name}] Unhandled error in run_cycle: {exc}")
            result = CycleResult(
                decisions_recorded=0,
                trades_attempted=0,
                trades_placed=0,
                errors=[str(exc)],
                cycle_duration_ms=duration_ms,
            )
        else:
            result.cycle_duration_ms = (time.monotonic() - start) * 1000

        # Heartbeat: update strategy last-seen timestamp in DB (best effort)
        try:
            from backend.core.heartbeat import update_heartbeat

            update_heartbeat(self.name)
        except Exception:
            pass

        return result

    # ------------------------------------------------------------------
    # Auto-registration hook
    # ------------------------------------------------------------------

    def __init_subclass__(cls, abstract: bool = False, **kwargs):
        super().__init_subclass__(**kwargs)
        if not abstract:
            # lazy import to avoid circular
            try:
                from backend.strategies.registry import _auto_register

                _auto_register(cls)
            except ImportError:
                pass
