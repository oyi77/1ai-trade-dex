from __future__ import annotations

import os
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from backend.core.agi_types import MarketRegime, AGIGoal
from backend.models.kg_models import Base, DecisionAuditLog


class AGIStatus:
    def __init__(
        self,
        regime: MarketRegime,
        goal: AGIGoal,
        allocations: dict[str, float] | None = None,
        health: str = "healthy",
        emergency_stop: bool = False,
    ):
        self.regime = regime
        self.goal = goal
        self.allocations = allocations or {}
        self.health = health
        self.emergency_stop = emergency_stop

    def to_dict(self) -> dict[str, Any]:
        return {
            "regime": self.regime.value,
            "goal": self.goal.value,
            "allocations": self.allocations,
            "health": self.health,
            "emergency_stop": self.emergency_stop,
        }


class AGICycleResult:
    def __init__(
        self,
        regime: MarketRegime,
        goal: AGIGoal,
        actions_taken: int = 0,
        errors: list[str] | None = None,
    ):
        self.regime = regime
        self.goal = goal
        self.actions_taken = actions_taken
        self.errors = errors or []

    def to_dict(self) -> dict[str, Any]:
        return {
            "regime": self.regime.value,
            "goal": self.goal.value,
            "actions_taken": self.actions_taken,
            "errors": self.errors,
        }


class AGIOrchestrator:
    def __init__(self, session: Optional[Session] = None, db_url: str = "sqlite:///:memory:"):
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

    def close(self):
        if self._owns_session:
            self._session.close()

    async def run_cycle(self) -> AGICycleResult:
        if self._emergency_stop:
            return AGICycleResult(
                regime=MarketRegime.UNKNOWN,
                goal=AGIGoal.PRESERVE_CAPITAL,
                errors=["Emergency stop active"],
            )

        errors = []
        actions = 0

        try:
            from backend.mesh.health import SourceHealthMonitor
            monitor = SourceHealthMonitor()
            source_mult = monitor.global_risk_multiplier()
            if source_mult < 1.0:
                logger.warning(f"DataMesh health degraded: risk_multiplier={source_mult}")
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
                    market_data["sma_50"] = sum(closes[-50:]) / 50 if len(closes) >= 50 else closes[-1]
                    market_data["sma_200"] = sum(closes[-200:]) / 200 if len(closes) >= 200 else closes[-1]
                    # Estimate volatility (ATR percent) and drawdown
                    max_price = max(closes)
                    market_data["drawdown"] = (max_price - closes[-1]) / max_price if max_price > 0 else 0.0
                    if len(closes) >= 15:
                        trs = [abs(closes[-i] - closes[-i-1]) for i in range(1, 15)]
                        atr = sum(trs) / len(trs)
                        market_data["atr_percentile"] = atr / closes[-1] if closes[-1] > 0 else 0.0
                    else:
                        market_data["atr_percentile"] = 0.0
                    if len(volumes) >= 20:
                        vol_recent = sum(volumes[-10:]) / 10
                        vol_prior = sum(volumes[-20:-10]) / 10
                        market_data["volume_trend"] = (vol_recent - vol_prior) / vol_prior if vol_prior > 0 else 0.0
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
            kg = KnowledgeGraph(session=self._session)
            allocator = RegimeAwareAllocator(kg=kg)
            allocations = allocator.allocate(["btc_momentum", "weather_emos"], regime, capital=10000.0 * source_mult)
            actions += 1
        except Exception as e:
            errors.append(f"Allocation failed: {e}")
            allocations = {}

        # --- Populate Knowledge Graph with this cycle's findings ---
        if kg is not None:
            try:
                _cycle_id = f"cycle_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{id(self)}"
                kg.add_entity("regime", f"regime:{regime.value}", {
                    "value": regime.value,
                    "detected_at": datetime.now(timezone.utc).isoformat(),
                })
                kg.add_entity("goal", f"goal:{goal.value}", {
                    "value": goal.value,
                    "set_at": datetime.now(timezone.utc).isoformat(),
                })
                for strat_name, amount in allocations.items():
                    kg.add_entity("strategy", f"strategy:{strat_name}", {
                        "name": strat_name,
                        "allocated_capital": amount,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    })
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
                    e.properties.get("value") for e in recent_regimes if e.properties.get("value")
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
            composed = composer.compose([block], name=composed_name, kg_context=kg_context)
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
            try:
                self._session.rollback()
            except Exception:
                pass

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
            try:
                self._session.rollback()
            except Exception:
                pass


class ErrorType(Enum):
    BENIGN = "BENIGN"
    TRANSIENT = "TRANSIENT"
    PERMANENT = "PERMANENT"


TRANSIENT_EXCEPTIONS: tuple[type[BaseException], ...] = (
    TimeoutError,
    ConnectionError,
    OSError,
)
# Lazy-import httpx exceptions only when needed (avoids hard dependency).
_httpx_transient: tuple[type[BaseException], ...] = ()
_httpx_checked: bool = False


def _get_httpx_transient() -> tuple[type[BaseException], ...]:
    """Return httpx transient exception types, importing lazily."""
    global _httpx_transient, _httpx_checked
    if not _httpx_checked:
        try:
            import httpx
            _httpx_transient = (httpx.TimeoutException, httpx.HTTPStatusError)
        except ImportError:
            _httpx_transient = ()
        _httpx_checked = True
    return _httpx_transient


PERMANENT_EXCEPTIONS: tuple[type[BaseException], ...] = (
    TypeError,
    ValueError,
    ImportError,
    AttributeError,
    KeyError,
)


def classify_exception(exc: BaseException) -> ErrorType:
    """Classify an exception as TRANSIENT, PERMANENT, or BENIGN.

    TRANSIENT — network timeouts, rate limits, service unavailable (retry-safe).
    PERMANENT — programming errors, bad data, missing config (must raise).
    BENIGN    — anything that doesn't match the above (log and continue).
    """
    if isinstance(exc, TRANSIENT_EXCEPTIONS + _get_httpx_transient()):
        return ErrorType.TRANSIENT
    if isinstance(exc, PERMANENT_EXCEPTIONS):
        return ErrorType.PERMANENT
    return ErrorType.BENIGN


logger = __import__("logging").getLogger("trading_bot.agi_orchestrator")


# Module-level circuit breaker state for TRANSIENT-failure tracking across cycles.
_consecutive_failures: int = 0
_circuit_open: bool = False
_TRANSIENT_FAILURE_THRESHOLD: int = 3
_STATS_REPORT_CRITICAL_ERRORS: bool = os.getenv("STATS_REPORT_CRITICAL_ERRORS", "false").lower() in ("true", "1", "yes")


def _open_circuit() -> None:
    """Halt the AGI improvement cycle after repeated TRANSIENT failures."""
    global _circuit_open
    _circuit_open = True
    logger.critical(
        "[agi_improvement_cycle] CIRCUIT OPEN: %d consecutive TRANSIENT failures — halting cycle",
        _consecutive_failures,
    )


def _alert_permanent_failure(stage: str, exc: BaseException) -> None:
    """Send a ProductionMonitor alert for a PERMANENT stage failure."""
    try:
        from backend.core.monitoring import ProductionMonitor
        ProductionMonitor().send_alert(
            severity="critical",
            message=f"AGI cycle PERMANENT failure in stage '{stage}': {exc}",
            details={"stage": stage, "error_type": "PERMANENT", "exception": str(exc)},
        )
    except Exception as alert_err:
        logger.warning("[agi_improvement_cycle] ProductionMonitor alert failed: %s", alert_err)


def _record_transient_failure(stage: str, exc: BaseException) -> None:
    """Increment the consecutive-failure counter and open the circuit at threshold."""
    global _consecutive_failures
    _consecutive_failures += 1
    logger.error(
        "[agi_improvement_cycle] TRANSIENT failure in stage '%s' (%d/%d): %s",
        stage,
        _consecutive_failures,
        _TRANSIENT_FAILURE_THRESHOLD,
        exc,
        exc_info=True,
    )
    if _consecutive_failures >= _TRANSIENT_FAILURE_THRESHOLD:
        _open_circuit()


def _reset_circuit() -> None:
    """Reset failure counter after a fully successful cycle."""
    global _consecutive_failures, _circuit_open
    if _consecutive_failures or _circuit_open:
        logger.info(
            "[agi_improvement_cycle] resetting TRANSIENT failure counter (was %d)",
            _consecutive_failures,
        )
    _consecutive_failures = 0
    _circuit_open = False


async def agi_improvement_cycle_job() -> None:
    """Scheduled job: runs the full closed-loop AGI improvement cycle.

    Errors are classified via :func:`classify_exception`:
      * BENIGN    — log a warning and continue running remaining stages.
      * TRANSIENT — log a warning, track consecutive failures, and re-raise
                    so the scheduler notes the failure; trips the circuit
                    breaker after :data:`_TRANSIENT_FAILURE_THRESHOLD`
                    consecutive failures.
      * PERMANENT — log at CRITICAL and re-raise immediately so the cycle
                    fails visibly (programming errors, missing modules, etc.).
    """
    global _consecutive_failures

    if _circuit_open:
        logger.warning(
            "[agi_improvement_cycle] circuit OPEN — skipping cycle until manually reset",
        )
        return

    stats = {
        "feedback_measured": 0,
        "meta_learned": 0,
        "evolution_variants": 0,
        "proposals_promoted": 0,
        "strategies_composed": 0,
        "strategies_replaced": 0,
        "counterfactual_scored": 0,
        "counterfactual_insights": 0,
        "errors": [],
        # Per-stage result tracking for observability (AGI-6)
        "stage_results": {
            "feedback": None,
            "meta_learning": None,
            "evolution": None,
            "promotion": None,
            "replacement": None,
            "composition": None,
            "counterfactual": None,
        },
    }

    try:
        from backend.ai.feedback_tracker import measure_recent_changes
        result = measure_recent_changes()
        stats["feedback_measured"] = result.get("measured", 0)
        stats["stage_results"]["feedback"] = "ok"
    except Exception as e:
        etype = classify_exception(e)
        stats["stage_results"]["feedback"] = f"error:{etype.value}"
        if etype == ErrorType.PERMANENT:
            logger.critical(
                "[agi_improvement_cycle] feedback stage PERMANENT failure: %s", e, exc_info=True,
            )
            _alert_permanent_failure("feedback", e)
            stats["errors"].append(f"feedback: {e}")
            raise
        elif etype == ErrorType.TRANSIENT:
            _record_transient_failure("feedback", e)
            stats["errors"].append(f"feedback: {e}")
            raise
        logger.warning(
            "[agi_improvement_cycle] feedback stage failed (BENIGN): %s", e, exc_info=True,
        )
        stats["errors"].append(f"feedback: {e}")

    try:
        from backend.ai.meta_learner import MetaLearner
        stats["meta_learned"] = MetaLearner().update_from_feedback()
        stats["stage_results"]["meta_learning"] = "ok"
    except Exception as e:
        etype = classify_exception(e)
        stats["stage_results"]["meta_learning"] = f"error:{etype.value}"
        if etype == ErrorType.PERMANENT:
            logger.critical(
                "[agi_improvement_cycle] meta_learn stage PERMANENT failure: %s", e, exc_info=True,
            )
            _alert_permanent_failure("meta_learning", e)
            stats["errors"].append(f"meta_learn: {e}")
            raise
        elif etype == ErrorType.TRANSIENT:
            _record_transient_failure("meta_learn", e)
            stats["errors"].append(f"meta_learn: {e}")
            raise
        logger.warning(
            "[agi_improvement_cycle] meta_learn stage failed (BENIGN): %s", e, exc_info=True,
        )
        stats["errors"].append(f"meta_learn: {e}")

    try:
        from backend.agents.autoresearch.evolver import StrategyEvolver
        stats["evolution_variants"] = len(StrategyEvolver().run_evolution_cycle())
        stats["stage_results"]["evolution"] = "ok"
    except Exception as e:
        etype = classify_exception(e)
        stats["stage_results"]["evolution"] = f"error:{etype.value}"
        if etype == ErrorType.PERMANENT:
            logger.critical(
                "[agi_improvement_cycle] evolution stage PERMANENT failure: %s", e, exc_info=True,
            )
            _alert_permanent_failure("evolution", e)
            stats["errors"].append(f"evolution: {e}")
            raise
        elif etype == ErrorType.TRANSIENT:
            _record_transient_failure("evolution", e)
            stats["errors"].append(f"evolution: {e}")
            raise
        logger.warning(
            "[agi_improvement_cycle] evolution stage failed (BENIGN): %s", e, exc_info=True,
        )
        stats["errors"].append(f"evolution: {e}")

    try:
        from backend.ai.proposal_generator import auto_promote_eligible_proposals
        auto_promote_eligible_proposals()
        from backend.models.database import StrategyProposal
        from backend.db.utils import get_db_session
        with get_db_session() as db:
            stats["proposals_promoted"] = db.query(StrategyProposal).filter(
                StrategyProposal.admin_decision == "auto_approved"
            ).count()
        stats["stage_results"]["promotion"] = "ok"
    except Exception as e:
        etype = classify_exception(e)
        stats["stage_results"]["promotion"] = f"error:{etype.value}"
        if etype == ErrorType.PERMANENT:
            logger.critical(
                "[agi_improvement_cycle] proposals stage PERMANENT failure: %s", e, exc_info=True,
            )
            _alert_permanent_failure("promotion", e)
            stats["errors"].append(f"proposals: {e}")
            raise
        _record_transient_failure("proposals", e)
        stats["errors"].append(f"proposals: {e}")
        raise

    try:
        from backend.models.database import StrategyConfig
        from backend.models.outcome_tables import StrategyHealthRecord
        from backend.db.utils import get_db_session
        with get_db_session() as db:
            killed = db.query(StrategyHealthRecord).filter(
                StrategyHealthRecord.status == "killed",
            ).all()
            for hr in killed:
                config = db.query(StrategyConfig).filter(
                    StrategyConfig.strategy_name == hr.strategy
                ).first()
                if config and config.enabled:
                    config.enabled = False
                    stats["strategies_replaced"] += 1
            if killed:
                db.commit()
        stats["stage_results"]["replacement"] = "ok"
    except Exception as e:
        etype = classify_exception(e)
        stats["stage_results"]["replacement"] = f"error:{etype.value}"
        if etype == ErrorType.PERMANENT:
            logger.critical(
                "[agi_improvement_cycle] replacement stage PERMANENT failure: %s", e, exc_info=True,
            )
            _alert_permanent_failure("replacement", e)
            stats["errors"].append(f"replacement: {e}")
            raise
        _record_transient_failure("replacement", e)
        stats["errors"].append(f"replacement: {e}")
        raise

    try:
        from backend.core.strategy_synthesizer import StrategySynthesizer
        from backend.core.agi_types import MarketRegime as _MR
        from backend.core.knowledge_graph import KnowledgeGraph

        # Build KG context for the synthesizer prompt
        _kg_ctx: dict = {}
        try:
            _kg = KnowledgeGraph(session=db)
            _kg_ctx = {
                "recent_regimes": [
                    e.properties.get("value")
                    for e in _kg.query_by_type("regime", limit=5)
                    if e.properties.get("value")
                ],
                "best_strategies": [
                    e.properties for e in _kg.query_by_type("strategy", limit=5)
                ],
            }
        except Exception as _kg_err:
            logger.debug("[agi_improvement_cycle] KG context fetch failed (non-fatal): %s", _kg_err)

        synthesizer = StrategySynthesizer(session=db)
        generated = await synthesizer.generate_strategy(
            description="New strategy for current market regime",
            regime=_MR.UNKNOWN,
            kg_context=_kg_ctx,
        )
        if generated.validation_passed:
            exp_id = synthesizer.register_generated(generated)
            stats["strategies_composed"] = 1
            stats["stage_results"]["composition"] = "ok"
            logger.info(
                "[agi_improvement_cycle] Synthesized strategy '%s' passed all gates → SHADOW (exp_id=%s)",
                generated.name, exp_id,
            )
        else:
            stats["strategies_composed"] = 0
            failed_gates = [k for k, v in generated.gate_results.items() if not v.get("passed", True)]
            stats["stage_results"]["composition"] = f"gate_failed:{failed_gates}"
            logger.warning(
                "[agi_improvement_cycle] Synthesized strategy '%s' failed gates: %s",
                generated.name, failed_gates,
            )
    except Exception as e:
        etype = classify_exception(e)
        stats["stage_results"]["composition"] = f"error:{etype.value}"
        if etype == ErrorType.PERMANENT:
            logger.critical(
                "[agi_improvement_cycle] composition stage PERMANENT failure: %s", e, exc_info=True,
            )
            _alert_permanent_failure("composition", e)
            stats["errors"].append(f"composition: {e}")
            raise
        _record_transient_failure("composition", e)
        stats["errors"].append(f"composition: {e}")
        raise

    try:
        from backend.ai.counterfactual_scorer import run_counterfactual_cycle
        cf_result = await run_counterfactual_cycle()
        stats["counterfactual_scored"] = cf_result.get("scoring", {}).get("scored", 0)
        stats["counterfactual_insights"] = cf_result.get("insights", {}).get("insights", 0)
        stats["stage_results"]["counterfactual"] = "ok"
    except Exception as e:
        etype = classify_exception(e)
        stats["stage_results"]["counterfactual"] = f"error:{etype.value}"
        if etype == ErrorType.PERMANENT:
            logger.critical(
                "[agi_improvement_cycle] counterfactual stage PERMANENT failure: %s", e, exc_info=True,
            )
            _alert_permanent_failure("counterfactual", e)
            stats["errors"].append(f"counterfactual: {e}")
            raise
        elif etype == ErrorType.TRANSIENT:
            _record_transient_failure("counterfactual", e)
            stats["errors"].append(f"counterfactual: {e}")
            raise
        logger.warning(
            "[agi_improvement_cycle] counterfactual stage failed (BENIGN): %s", e, exc_info=True,
        )
        stats["errors"].append(f"counterfactual: {e}")

    if not stats["errors"]:
        _reset_circuit()
    else:
        logger.warning(
            "[agi_improvement_cycle] cycle completed with %d error(s)", len(stats["errors"]),
        )

    if len(stats["errors"]) >= 4:
        logger.critical(
            "[agi_improvement_cycle] %d/7 stages failed — AGI cycle may be non-functional",
            len(stats["errors"]),
        )
        if _STATS_REPORT_CRITICAL_ERRORS:
            try:
                from backend.core.monitoring import ProductionMonitor
                from backend.db.utils import get_db_session
                with get_db_session() as db:
                    ProductionMonitor(db).send_alert(
                        severity="critical",
                        message=f"AGI cycle critical: {len(stats['errors'])}/7 stages failed",
                        details={"errors": stats["errors"]},
                    )
            except Exception:
                pass

    logger.info(
        "[agi_improvement_cycle] feedback=%d meta=%d evolved=%d promoted=%d composed=%d replaced=%d cf_scored=%d errors=%d",
        stats["feedback_measured"],
        stats["meta_learned"],
        stats["evolution_variants"],
        stats["proposals_promoted"],
        stats["strategies_composed"],
        stats["strategies_replaced"],
        stats.get("counterfactual_scored", 0),
        len(stats["errors"]),
    )
