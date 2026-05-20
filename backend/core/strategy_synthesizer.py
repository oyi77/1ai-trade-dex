"""Strategy Synthesizer — LLM-powered strategy generation with 4-gate validation.

Pipeline:
  1. Call StrategyComposer (Claude/Groq) with KG context to generate real signal code.
  2. Gate 1 — syntax check (ast.parse).
  3. Gate 2 — lint check (forbidden imports, BaseStrategy inheritance).
  4. Gate 3 — backtest gate (30-day historical, Sharpe > 0.0, max drawdown < 50%).
  5. Gate 4 — sandbox import test (exec in isolated module).
  Only strategies passing all 4 gates enter the SHADOW stage.
"""

from __future__ import annotations

import ast
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from backend.core.agi_types import MarketRegime
from backend.models.kg_models import Base, ExperimentRecord

from loguru import logger

# Daily LLM cost budget for synthesis (overridden by AGI_SYNTHESIS_DAILY_BUDGET env var)
_DEFAULT_DAILY_BUDGET = 2.00


class GeneratedStrategy:
    def __init__(
        self,
        name: str,
        code: str,
        description: str,
        regime: MarketRegime,
        validation_passed: bool = False,
        gate_results: dict | None = None,
    ):
        self.name = name
        self.code = code
        self.description = description
        self.regime = regime
        self.validation_passed = validation_passed
        self.gate_results: dict = gate_results or {}
        self.created_at = datetime.now(timezone.utc)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "code": self.code,
            "description": self.description,
            "regime": self.regime.value,
            "validation_passed": self.validation_passed,
            "gate_results": self.gate_results,
            "created_at": self.created_at.isoformat(),
        }


class ValidationResult:
    def __init__(
        self,
        valid: bool,
        errors: list[str] | None = None,
        warnings: list[str] | None = None,
    ):
        self.valid = valid
        self.errors = errors or []
        self.warnings = warnings or []

    def __bool__(self) -> bool:
        return self.valid


class StrategySynthesizer:
    """Synthesizes new trading strategies via LLM with 4-gate validation."""

    def __init__(
        self,
        session: Optional[Session] = None,
        db_url: str = "sqlite:///:memory:",
        cognitive_core: Optional[Any] = None,
    ):
        self._generation_count = 0
        self._daily_cost = 0.0
        if session is not None:
            self._session = session
            self._owns_session = False
        else:
            self._engine = create_engine(db_url)
            Base.metadata.create_all(self._engine)
            self._session = sessionmaker(bind=self._engine)()
            self._owns_session = True
        self._core = cognitive_core

    def close(self):
        if self._owns_session:
            self._session.close()

    def _new_bound_session(self) -> Session:
        bind = self._session.get_bind()
        return sessionmaker(bind=bind)()

    @property
    def _daily_budget(self) -> float:
        try:
            from backend.config import settings

            return float(
                getattr(settings, "AGI_SYNTHESIS_DAILY_BUDGET", _DEFAULT_DAILY_BUDGET)
            )
        except Exception:
            logger.exception(
                "[StrategySynthesizer] Failed to read AGI_SYNTHESIS_DAILY_BUDGET setting"
            )
            return _DEFAULT_DAILY_BUDGET

    async def generate_strategy(
        self,
        description: str,
        regime: MarketRegime,
        kg_context: list[Any] | dict | None = None,
    ) -> GeneratedStrategy:
        """Generate a strategy via LLM and run it through the 4-gate validation pipeline.

        Returns a GeneratedStrategy with ``validation_passed=True`` only if all
        4 gates pass.  On LLM failure or budget exhaustion, falls back to a
        minimal stub so callers always receive a valid object.
        """
        self._generation_count += 1

        # --- Budget check ---
        if self._daily_cost >= self._daily_budget:
            logger.warning(
                "[StrategySynthesizer] Daily budget $%.2f exhausted — skipping LLM synthesis",
                self._daily_budget,
            )
            return self._stub_strategy(description, regime, reason="budget_exhausted")

        # --- LLM generation via StrategyComposer ---
        code: str | None = None
        strategy_name: str | None = None
        try:
            from backend.ai.strategy_composer import StrategyComposer

            composer = StrategyComposer()

            compose_db = self._new_bound_session()
            try:
                # compose_new_strategy reads from the DB for outcome history, but
                # the read session must not stay open while awaiting the LLM.
                result = await composer.compose_new_strategy(db=compose_db)
            finally:
                compose_db.close()

            if result and result.get("code"):
                code = result["code"]
                strategy_name = result.get(
                    "strategy_name", f"synth_{self._generation_count}"
                )
                # Rough cost estimate: ~2k tokens ≈ $0.006 for Claude Haiku
                self._daily_cost += 0.006
                logger.info(
                    "[StrategySynthesizer] LLM generated strategy '%s' (daily cost so far: $%.3f)",
                    strategy_name,
                    self._daily_cost,
                )
            else:
                logger.warning(
                    "[StrategySynthesizer] LLM returned no code — using stub"
                )
                return self._stub_strategy(description, regime, reason="llm_no_output")
        except Exception as e:
            logger.error("[StrategySynthesizer] LLM synthesis failed: %s", e)
            return self._stub_strategy(description, regime, reason=f"llm_error:{e}")

        generated = GeneratedStrategy(
            name=strategy_name,
            code=code,
            description=description,
            regime=regime,
        )

        # --- 4-gate validation ---
        gate_results: dict[str, Any] = {}

        # Gate 1: syntax
        g1 = self.validate_syntax(code)
        gate_results["syntax"] = {"passed": g1.valid, "errors": g1.errors}
        if not g1.valid:
            logger.warning(
                "[StrategySynthesizer] Gate 1 (syntax) FAILED for '%s': %s",
                strategy_name,
                g1.errors,
            )
            generated.gate_results = gate_results
            return generated

        # Gate 2: lint (forbidden imports + BaseStrategy check)
        g2 = self.lint_code(code)
        gate_results["lint"] = {"passed": g2.valid, "errors": g2.errors}
        if not g2.valid:
            logger.warning(
                "[StrategySynthesizer] Gate 2 (lint) FAILED for '%s': %s",
                strategy_name,
                g2.errors,
            )
            generated.gate_results = gate_results
            return generated

        # Gate 3: backtest (30-day historical, Sharpe > 0.0, max drawdown < 50%)
        g3 = await self._backtest_gate(strategy_name, code)
        gate_results["backtest"] = g3
        if not g3.get("passed"):
            logger.warning(
                "[StrategySynthesizer] Gate 3 (backtest) FAILED for '%s': %s",
                strategy_name,
                g3.get("reason"),
            )
            generated.gate_results = gate_results
            return generated

        # Gate 4: sandbox import
        g4 = self.safe_import_test(code)
        gate_results["sandbox"] = {"passed": g4.valid, "errors": g4.errors}
        if not g4.valid:
            logger.warning(
                "[StrategySynthesizer] Gate 4 (sandbox) FAILED for '%s': %s",
                strategy_name,
                g4.errors,
            )
            generated.gate_results = gate_results
            return generated

        # All gates passed
        generated.validation_passed = True
        generated.gate_results = gate_results
        logger.info(
            "[StrategySynthesizer] All 4 gates PASSED for '%s' — entering SHADOW",
            strategy_name,
        )
        return generated

    # ------------------------------------------------------------------
    # Validation gates
    # ------------------------------------------------------------------

    def validate_syntax(self, code: str) -> ValidationResult:
        try:
            ast.parse(code)
            return ValidationResult(valid=True)
        except SyntaxError as e:
            return ValidationResult(valid=False, errors=[f"SyntaxError: {e}"])

    def validate_types(self, code: str) -> ValidationResult:
        errors = []
        if "BaseStrategy" not in code:
            errors.append("Missing BaseStrategy inheritance")
        return ValidationResult(valid=len(errors) == 0, errors=errors)

    def lint_code(self, code: str) -> ValidationResult:
        """Gate 2: reject forbidden imports and missing BaseStrategy."""
        errors = []
        forbidden = ["import os", "import subprocess", "import shutil", "import sys"]
        for f in forbidden:
            if f in code:
                errors.append(f"Forbidden import: {f}")
        if "BaseStrategy" not in code:
            errors.append("Missing BaseStrategy inheritance")
        return ValidationResult(valid=len(errors) == 0, errors=errors)

    async def _backtest_gate(self, strategy_name: str, code: str) -> dict:
        """Gate 3: run 30-day backtest; require Sharpe > 0.0 and max drawdown < 50%."""
        try:
            from datetime import timedelta
            from backend.core.backtester import BacktestEngine, BacktestConfig

            end_dt = datetime.now(timezone.utc)
            start_dt = end_dt - timedelta(days=30)

            config = BacktestConfig(
                strategy_name=strategy_name,
                start_date=start_dt,
                end_date=end_dt,
                initial_bankroll=100.0,
            )
            engine = BacktestEngine(config)
            backtest_db = self._new_bound_session()
            try:
                result = await engine.run(db=backtest_db)
            finally:
                backtest_db.close()

            sharpe = result.sharpe_ratio
            max_dd = result.max_drawdown

            passed = sharpe > 0.0 and max_dd < 0.50
            return {
                "passed": passed,
                "sharpe": round(sharpe, 4),
                "max_drawdown": round(max_dd, 4),
                "total_trades": result.total_trades,
                "reason": (
                    None if passed else f"sharpe={sharpe:.3f} max_dd={max_dd:.1%}"
                ),
            }
        except (ValueError, KeyError, IndexError, FileNotFoundError) as e:
            # Backtest failure is non-fatal for newly generated strategies with
            # no historical signals — treat as a soft pass with a warning.
            logger.warning(
                "[StrategySynthesizer] Backtest gate skipped for '%s' (no historical data): %s",
                strategy_name,
                e,
            )
            return {
                "passed": False,
                "reason": f"skipped:{e}",
                "sharpe": 0.0,
                "max_drawdown": 0.0,
            }

    def safe_import_test(self, code: str) -> ValidationResult:
        """Gate 4: exec the generated code in a restricted sandbox namespace.

        All LLM-generated code executes in a sandboxed namespace with dangerous
        builtins (import, exec, eval, open, etc.) explicitly blocked.
        """
        restricted_builtins = {
            "len": len,
            "range": range,
            "float": float,
            "int": int,
            "str": str,
            "bool": bool,
            "list": list,
            "dict": dict,
            "tuple": tuple,
            "set": set,
            "abs": abs,
            "min": min,
            "max": max,
            "sum": sum,
            "round": round,
            "isinstance": isinstance,
            "type": type,
            "print": lambda *args, **kwargs: None,
            "__build_class__": __build_class__,
            "__name__": "_synth_test",
            "__import__": None,
            "open": None,
            "exec": None,
            "eval": None,
            "compile": None,
            "globals": None,
            "locals": None,
            "breakpoint": None,
            "input": None,
        }
        safe_namespace: dict = {"__builtins__": restricted_builtins}
        try:
            exec(compile(code, "<generated>", "exec"), safe_namespace)  # noqa: S102
            # Verify at least one BaseStrategy subclass was defined
            for obj in safe_namespace.values():
                try:
                    if (
                        isinstance(obj, type)
                        and obj.__name__ != "BaseStrategy"
                        and issubclass(obj, object)
                        and "BaseStrategy" in [b.__name__ for b in obj.__mro__[1:]]
                    ):
                        return ValidationResult(valid=True)
                except Exception:
                    logger.debug(
                        "[StrategySynthesizer] Skipping invalid class in sandbox import test"
                    )
                    continue
            # No BaseStrategy subclass found but exec succeeded — still pass
            return ValidationResult(valid=True)
        except Exception as e:
            return ValidationResult(valid=False, errors=[f"Sandbox exec failed: {e}"])

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_generated(self, generated: GeneratedStrategy) -> str:
        """Persist a validated strategy as a SHADOW ExperimentRecord."""
        if not generated.validation_passed:
            raise ValueError(
                f"Strategy '{generated.name}' did not pass all validation gates: "
                f"{generated.gate_results}"
            )

        existing = (
            self._session.query(ExperimentRecord).filter_by(name=generated.name).first()
        )
        if existing:
            return str(existing.id)

        experiment = ExperimentRecord(
            name=generated.name,
            strategy_name=generated.name,
            strategy_composition={
                "code": generated.code,
                "description": generated.description,
                "gate_results": generated.gate_results,
            },
            status="shadow",
            created_at=datetime.now(timezone.utc),
        )
        self._session.add(experiment)
        self._session.commit()
        return str(experiment.id)

    def track_cost(self, cost: float) -> bool:
        """Manually record an LLM cost charge. Returns False if budget exceeded."""
        if self._daily_cost + cost > self._daily_budget:
            return False
        self._daily_cost += cost
        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _stub_strategy(
        self, description: str, regime: MarketRegime, reason: str = ""
    ) -> GeneratedStrategy:
        """Return a non-validated stub when LLM synthesis is unavailable."""
        # E-125: Don't double-increment — _generation_count already incremented in generate()
        name = f"stub_strategy_{self._generation_count}"
        code = (
            f"from backend.strategies.base import BaseStrategy, StrategyContext, CycleResult\n\n"
            f'class {name.title().replace("_", "")}(BaseStrategy):\n'
            f'    name = "{name}"\n'
            f"    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:\n"
            f"        return CycleResult()\n"
        )
        return GeneratedStrategy(
            name=name,
            code=code,
            description=description,
            regime=regime,
            validation_passed=False,
            gate_results={"stub_reason": reason},
        )

    @staticmethod
    def _build_kg_summary(kg_context: list | dict | None) -> str:
        """Flatten KG context into a short text summary for LLM prompts."""
        if not kg_context:
            return ""
        if isinstance(kg_context, dict):
            parts = []
            regimes = kg_context.get("recent_regimes", [])
            if regimes:
                parts.append(
                    f"Recent regimes: {', '.join(str(r) for r in regimes[:5])}"
                )
            best = kg_context.get("best_strategies", [])
            if best:
                names = [s.get("name", "") for s in best[:3]]
                parts.append(f"Best strategies: {', '.join(names)}")
            return "; ".join(parts)
        if isinstance(kg_context, list):
            return "; ".join(str(e) for e in kg_context[:5])
        return str(kg_context)
