"""AGIOrchestrator — per-cycle regime/goal/allocation loop."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from loguru import logger

from backend.core.agi_types import MarketRegime, AGIGoal
from backend.models.kg_models import Base, DecisionAuditLog

from backend.core.agi_orchestrator_status import AGIStatus, AGICycleResult


class AGIOrchestrator:
    def __init__(
        self,
        session: Optional[Session] = None,
        db_url: str = "sqlite:///:memory:",
        cognitive_core: Optional[Any] = None,
    ):
        self._emergency_stop = False
        self._current_regime = None
        self._current_goal = None
        if session is not None:
            self._session = session
            self._owns_session = False
        else:
            self._engine = create_engine(db_url)
            Base.metadata.create_all(self._engine)
            self._session = sessionmaker(bind=self._engine)()
            self._owns_session = True
        if cognitive_core is not None:
            self._core = cognitive_core
        else:
            from backend.core.cognitive_core import DegradedCore

            self._core = DegradedCore()

    def close(self):
        if self._owns_session:
            self._session.close()

    async def _fetch_dune_context(self) -> dict[str, Any]:
        """Fetch Polymarket on-chain analytics from Dune Analytics.

        Returns a dict with volume, top markets, and whale activity data.
        Returns empty dict if Dune is unavailable or unconfigured.
        """
        try:
            from backend.data.dune_analytics import DuneAnalyticsClient

            client = DuneAnalyticsClient()
            if not client.api_key:
                logger.debug("Dune API key not configured, skipping on-chain context")
                return {}

            volume, markets, whales = [], [], []
            try:
                volume = await client.get_total_volume()
            except Exception as e:
                logger.debug("Dune total_volume fetch failed: %s", e)
            try:
                markets = await client.get_top_markets()
            except Exception as e:
                logger.debug("Dune top_markets fetch failed: %s", e)
            try:
                whales = await client.get_whale_activity()
            except Exception as e:
                logger.debug("Dune whale_activity fetch failed: %s", e)

            ctx: dict[str, Any] = {}
            if volume:
                ctx["dune_volume"] = volume
            if markets:
                ctx["dune_top_markets"] = markets
            if whales:
                ctx["dune_whale_activity"] = whales
            if ctx:
                logger.info(
                    "Dune context loaded: %d volume rows, %d markets, %d whale trades",
                    len(volume),
                    len(markets),
                    len(whales),
                )
            return ctx
        except ImportError:
            logger.debug("dune_analytics module not available")
            return {}
        except Exception as e:
            logger.debug("Dune context fetch failed: %s", e)
            return {}

    async def run_cycle(self) -> AGICycleResult:
        if self._emergency_stop:
            return AGICycleResult(
                regime=MarketRegime.UNKNOWN,
                goal=AGIGoal.PRESERVE_CAPITAL,
                errors=["Emergency stop active"],
            )

        errors = []
        actions = 0

        # Fetch Dune Analytics on-chain context (non-blocking, best-effort)
        dune_context: dict[str, Any] = {}
        try:
            dune_context = await self._fetch_dune_context()
            if dune_context:
                actions += 1
        except Exception as e:
            logger.debug("Dune context fetch skipped: %s", e)

        try:
            from backend.mesh.health import SourceHealthMonitor

            monitor = SourceHealthMonitor()
            source_mult = monitor.global_risk_multiplier()
            if source_mult < 1.0:
                logger.warning(
                    f"DataMesh health degraded: risk_multiplier={source_mult}"
                )
        except Exception as e:
            logger.debug(f"DataMesh health check skipped: {e}")
            source_mult = 1.0

        try:
            from backend.core.regime_detector import RegimeDetector
            from backend.data.crypto import fetch_binance_klines

            detector = RegimeDetector()

            # Fetch real BTC prices to feed the RegimeDetector
            market_data = {}
            try:
                # Fetch 250 candles to ensure we have enough for 200 SMA
                candles = await fetch_binance_klines(limit=250)
                if candles and len(candles) >= 200:
                    closes = [float(c[4]) for c in candles]
                    volumes = [float(c[5]) for c in candles]
                    market_data["prices"] = closes
                    market_data["volumes"] = volumes
                    # Calculate simple SMA
                    market_data["sma_50"] = (
                        sum(closes[-50:]) / 50 if len(closes) >= 50 else closes[-1]
                    )
                    market_data["sma_200"] = (
                        sum(closes[-200:]) / 200 if len(closes) >= 200 else closes[-1]
                    )
                    # Estimate volatility (ATR percent) and drawdown
                    max_price = max(closes)
                    market_data["drawdown"] = (
                        (max_price - closes[-1]) / max_price if max_price > 0 else 0.0
                    )
                    if len(closes) >= 15:
                        trs = [abs(closes[-i] - closes[-i - 1]) for i in range(1, 15)]
                        atr = sum(trs) / len(trs)
                        market_data["atr_percentile"] = (
                            atr / closes[-1] if closes[-1] > 0 else 0.0
                        )
                    else:
                        market_data["atr_percentile"] = 0.0
                    if len(volumes) >= 20:
                        vol_recent = sum(volumes[-10:]) / 10
                        vol_prior = sum(volumes[-20:-10]) / 10
                        market_data["volume_trend"] = (
                            (vol_recent - vol_prior) / vol_prior
                            if vol_prior > 0
                            else 0.0
                        )
                    else:
                        market_data["volume_trend"] = 0.0
            except Exception as e:
                errors.append(f"Crypto data fetch failed: {e}")

            regime = detector.detect_regime(market_data=market_data).regime
            self._current_regime = regime
            actions += 1
        except Exception as e:
            errors.append(f"Regime detection failed: {e}")
            regime = MarketRegime.UNKNOWN

        try:
            from backend.core.agi_goal_engine import AGIGoalEngine

            goal_engine = AGIGoalEngine(session=self._session)
            goal = goal_engine.get_current_goal(regime)
            self._current_goal = goal
            actions += 1
        except Exception as e:
            errors.append(f"Goal engine failed: {e}")
            goal = AGIGoal.PRESERVE_CAPITAL

        kg = None
        try:
            from backend.core.strategy_allocator import RegimeAwareAllocator
            from backend.core.knowledge_graph import KnowledgeGraph
            from backend.db.utils import get_db_session
            from backend.models.database import StrategyConfig

            kg = KnowledgeGraph(session=self._session)
            allocator = RegimeAwareAllocator(kg=kg)
            with get_db_session() as db:
                active = [
                    r[0]
                    for r in db.query(StrategyConfig.strategy_name)
                    .filter(StrategyConfig.enabled.is_(True))
                    .all()
                ]
            strategy_names = active if active else ["crypto_oracle", "weather_emos"]
            allocations = allocator.allocate(
                strategy_names, regime, capital=10000.0 * source_mult
            )
            actions += 1
        except Exception as e:
            errors.append(f"Allocation failed: {e}")
            allocations = {}

        # --- Populate Knowledge Graph with this cycle's findings ---
        if kg is not None:
            try:
                _cycle_id = f"cycle_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{id(self)}"
                kg.add_entity(
                    "regime",
                    f"regime:{regime.value}",
                    {
                        "value": regime.value,
                        "detected_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
                kg.add_entity(
                    "goal",
                    f"goal:{goal.value}",
                    {
                        "value": goal.value,
                        "set_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
                for strat_name, amount in allocations.items():
                    kg.add_entity(
                        "strategy",
                        f"strategy:{strat_name}",
                        {
                            "name": strat_name,
                            "allocated_capital": amount,
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                    kg.add_relation(
                        f"regime:{regime.value}",
                        f"strategy:{strat_name}",
                        "allocates_to",
                        weight=amount / 10000.0,
                        confidence=0.8,
                    )
                kg.add_relation(
                    f"regime:{regime.value}",
                    f"goal:{goal.value}",
                    "triggers_goal",
                    weight=1.0,
                    confidence=0.9,
                )
                actions += 1
            except Exception as e:
                errors.append(f"KG population failed: {e}")

        # --- Read KG context before composing strategies ---
        kg_context: dict = {}
        if kg is not None:
            try:
                # Recent regime history (last 10 detected regimes)
                recent_regimes = kg.query_by_type("regime", limit=10)
                kg_context["recent_regimes"] = [
                    e.properties.get("value")
                    for e in recent_regimes
                    if e.properties.get("value")
                ]
                # Best strategies for current regime
                best_strats = kg.query_best_strategies(regime, limit=5)
                kg_context["best_strategies"] = [
                    {"name": e.entity_id, **e.properties} for e in best_strats
                ]
                # Strategy performance entities
                strat_entities = kg.query_by_type("strategy", limit=20)
                kg_context["strategy_performance"] = [
                    e.properties for e in strat_entities if e.properties
                ]
                actions += 1
            except Exception as e:
                errors.append(f"KG read-back failed: {e}")

        # Merge Dune on-chain analytics into KG context
        if dune_context:
            kg_context.update(dune_context)

        # --- Auto-compose strategies for the current regime ---
        try:
            from backend.core.strategy_composer import StrategyComposer
            from backend.core.agi_types import StrategyBlock

            composer = StrategyComposer(session=self._session)
            signal_source = {
                MarketRegime.BULL: "btc_momentum_signal",
                MarketRegime.BEAR: "whale_tracker_signal",
                MarketRegime.SIDEWAYS: "oracle_signal",
                MarketRegime.SIDEWAYS_VOLATILE: "weather_signal",
                MarketRegime.CRISIS: "whale_tracker_signal",
            }.get(regime, "btc_momentum_signal")
            risk_rule = {
                MarketRegime.BULL: "max_2pct",
                MarketRegime.BEAR: "max_1pct",
                MarketRegime.SIDEWAYS: "max_1pct",
                MarketRegime.SIDEWAYS_VOLATILE: "max_1pct",
                MarketRegime.CRISIS: "daily_loss_5pct",
            }.get(regime, "max_1pct")
            sizer = {
                MarketRegime.BULL: "kelly_sizer",
                MarketRegime.BEAR: "half_kelly",
                MarketRegime.SIDEWAYS: "fixed_005",
                MarketRegime.SIDEWAYS_VOLATILE: "fixed_005",
                MarketRegime.CRISIS: "fixed_005",
            }.get(regime, "fixed_005")
            block = StrategyBlock(
                signal_source=signal_source,
                filter="min_edge_005",
                position_sizer=sizer,
                risk_rule=risk_rule,
                exit_rule="take_profit_10pct",
            )
            composed_name = f"auto_{regime.value}_{goal.value}"
            composed = composer.compose(
                [block], name=composed_name, kg_context=kg_context
            )
            composer.register_composed(composed)
            actions += 1
        except Exception as e:
            errors.append(f"Strategy composition failed: {e}")

        self._log_cycle(regime, goal, allocations, errors)

        return AGICycleResult(
            regime=regime,
            goal=goal,
            actions_taken=actions,
            errors=errors,
        )

    def get_status(self) -> AGIStatus:
        regime = self._current_regime or MarketRegime.UNKNOWN
        goal = self._current_goal or AGIGoal.PRESERVE_CAPITAL
        return AGIStatus(
            regime=regime,
            goal=goal,
            health="stopped" if self._emergency_stop else "healthy",
            emergency_stop=self._emergency_stop,
        )

    def emergency_stop(self) -> None:
        self._emergency_stop = True
        try:
            audit = DecisionAuditLog(
                timestamp=datetime.now(timezone.utc),
                agent_name="AGIOrchestrator",
                decision_type="agi_emergency_stop",
                input_data={"action": "emergency_stop"},
                output_data={"status": "stopped"},
                confidence=1.0,
                reasoning="Emergency stop activated",
            )
            self._session.add(audit)
            self._session.commit()
        except Exception:
            logger.exception(
                "AGIOrchestrator.emergency_stop: failed to log audit record"
            )
            try:
                self._session.rollback()
            except Exception:
                logger.exception("AGIOrchestrator.emergency_stop: rollback also failed")

    def _log_cycle(
        self, regime: MarketRegime, goal: AGIGoal, allocations: dict, errors: list[str]
    ):
        try:
            audit = DecisionAuditLog(
                timestamp=datetime.now(timezone.utc),
                agent_name="AGIOrchestrator",
                decision_type="agi_cycle",
                input_data={
                    "regime": regime.value,
                    "goal": goal.value,
                    "allocations": allocations,
                },
                output_data={"errors": errors, "actions": len(allocations)},
                confidence=1.0 if not errors else 0.5,
                reasoning=f"AGI cycle completed: regime={regime.value}, goal={goal.value}",
            )
            self._session.add(audit)
            self._session.commit()
        except Exception:
            logger.exception("AGIOrchestrator._log_cycle: failed to log audit record")
            try:
                self._session.rollback()
            except Exception:
                logger.exception("AGIOrchestrator._log_cycle: rollback also failed")


