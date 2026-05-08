from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from backend.core.agi_types import MarketRegime
from backend.models.kg_models import Base, ExperimentRecord


class GeneratedStrategy:
    def __init__(
        self,
        name: str,
        code: str,
        description: str,
        regime: MarketRegime,
        validation_passed: bool = False,
    ):
        self.name = name
        self.code = code
        self.description = description
        self.regime = regime
        self.validation_passed = validation_passed
        self.created_at = datetime.now(timezone.utc)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "code": self.code,
            "description": self.description,
            "regime": self.regime.value,
            "validation_passed": self.validation_passed,
            "created_at": self.created_at.isoformat(),
        }


class ValidationResult:
    def __init__(self, valid: bool, errors: list[str] | None = None, warnings: list[str] | None = None):
        self.valid = valid
        self.errors = errors or []
        self.warnings = warnings or []

    def __bool__(self) -> bool:
        return self.valid


class StrategySynthesizer:
    MAX_COST_PER_GENERATION = 0.50
    MAX_RETRIES_PER_DAY = 3

    def __init__(self, session: Optional[Session] = None, db_url: str = "sqlite:///:memory:"):
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

    def close(self):
        if self._owns_session:
            self._session.close()

    def generate_strategy(
        self, description: str, regime: MarketRegime, kg_context: list[Any] | None = None
    ) -> GeneratedStrategy:
        self._generation_count += 1
        strategy_name = f"generated_strategy_{self._generation_count}"

        code = f'''from backend.strategies.base import BaseStrategy, StrategyContext, TradingSignal
from backend.core.risk_manager import RiskManager

class {strategy_name}(BaseStrategy):
    def __init__(self):
        super().__init__("{strategy_name}")
        self.regime = "{regime.value}"

    async def run(self, ctx: StrategyContext) -> list[TradingSignal]:
        risk = RiskManager()
        # Strategy: {description}
        # Implement signal generation logic based on the description above
        # Use ctx.settings for configurable thresholds
        # Return list of TradingSignal when edge is detected
        return []

    def validate(self, ctx: StrategyContext) -> bool:
        return True
'''

        generated = GeneratedStrategy(
            name=strategy_name,
            code=code,
            description=description,
            regime=regime,
        )
        return generated

    def validate_syntax(self, code: str) -> ValidationResult:
        import ast
        try:
            ast.parse(code)
            return ValidationResult(valid=True)
        except SyntaxError as e:
            return ValidationResult(valid=False, errors=[f"SyntaxError: {e}"])

    def validate_types(self, code: str) -> ValidationResult:
        errors = []
        if "BaseStrategy" not in code:
            errors.append("Missing BaseStrategy inheritance")
        if "RiskManager" not in code:
            errors.append("Missing RiskManager call")
        return ValidationResult(valid=len(errors) == 0, errors=errors)

    def lint_code(self, code: str) -> ValidationResult:
        errors = []
        if "import os" in code or "import subprocess" in code or "import shutil" in code:
            errors.append("Forbidden import: os/subprocess/shutil not allowed")
        if "import sys" in code:
            errors.append("Forbidden import: sys not allowed in generated code")
        return ValidationResult(valid=len(errors) == 0, errors=errors)

    def safe_import_test(self, code: str) -> ValidationResult:
        import types
        try:
            module = types.ModuleType("test_module")
            exec(code, module.__dict__)
            if not hasattr(module, "GeneratedStrategy") and "class" in code:
                for line in code.splitlines():
                    if line.strip().startswith("class ") and "BaseStrategy" in line:
                        return ValidationResult(valid=True)
            return ValidationResult(valid=True)
        except Exception as e:
            return ValidationResult(valid=False, errors=[f"Import failed: {e}"])

    def register_generated(self, generated: GeneratedStrategy) -> str:
        syntax_check = self.validate_syntax(generated.code)
        if not syntax_check:
            raise ValueError(f"Syntax validation failed: {syntax_check.errors}")

        type_check = self.validate_types(generated.code)
        if not type_check:
            raise ValueError(f"Type validation failed: {type_check.errors}")

        lint_check = self.lint_code(generated.code)
        if not lint_check:
            raise ValueError(f"Lint validation failed: {lint_check.errors}")

        existing = self._session.query(ExperimentRecord).filter_by(name=generated.name).first()
        if existing:
            return str(existing.id)

        experiment = ExperimentRecord(
            name=generated.name,
            strategy_composition={"code": generated.code, "description": generated.description},
            status="shadow",
        )
        self._session.add(experiment)
        self._session.commit()
        generated.validation_passed = True
        return str(experiment.id)

    def track_cost(self, cost: float) -> bool:
        if cost > self.MAX_COST_PER_GENERATION:
            return False
        if self._daily_cost + cost > self.MAX_COST_PER_GENERATION * self.MAX_RETRIES_PER_DAY:
            return False
        self._daily_cost += cost
        return True
