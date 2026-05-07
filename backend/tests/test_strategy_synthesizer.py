
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.strategy_synthesizer import (
    StrategySynthesizer,
    GeneratedStrategy,
    ValidationResult,
)
from backend.core.agi_types import MarketRegime
from backend.models.kg_models import Base, ExperimentRecord


def make_synthesizer_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    synthesizer = StrategySynthesizer(session=session)
    return synthesizer, session, engine


class TestStrategySynthesizerGenerate:
    def test_generate_creates_strategy(self):
        synthesizer, _, _ = make_synthesizer_session()
        result = synthesizer.generate_strategy(
            description="Momentum strategy for bull regime",
            regime=MarketRegime.BULL,
        )
        assert result.name.startswith("generated_strategy_")
        assert result.regime == MarketRegime.BULL
        assert "BaseStrategy" in result.code
        assert result.validation_passed is False

    def test_generate_includes_regime(self):
        synthesizer, _, _ = make_synthesizer_session()
        result = synthesizer.generate_strategy(
            description="Sideways strategy",
            regime=MarketRegime.SIDEWAYS,
        )
        assert "sideways" in result.code.lower() or "SIDEWAYS" in result.code


class TestStrategySynthesizerValidateSyntax:
    def test_valid_syntax_passes(self):
        synthesizer, _, _ = make_synthesizer_session()
        code = "def hello():\n    return 42"
        result = synthesizer.validate_syntax(code)
        assert result.valid

    def test_invalid_syntax_fails(self):
        synthesizer, _, _ = make_synthesizer_session()
        code = "def hello(\n    return 42"
        result = synthesizer.validate_syntax(code)
        assert not result.valid
        assert any("SyntaxError" in e for e in result.errors)


class TestStrategySynthesizerValidateTypes:
    def test_valid_types_pass(self):
        synthesizer, _, _ = make_synthesizer_session()
        code = '''
class MyStrategy(BaseStrategy):
    def __init__(self):
        self.risk = RiskManager()
'''
        result = synthesizer.validate_types(code)
        assert result.valid

    def test_missing_basestrategy_fails(self):
        synthesizer, _, _ = make_synthesizer_session()
        code = "def some_function():\n    pass"
        result = synthesizer.validate_types(code)
        assert not result.valid
        assert any("BaseStrategy" in e for e in result.errors)

    def test_missing_riskmanager_fails(self):
        synthesizer, _, _ = make_synthesizer_session()
        code = '''
class MyStrategy(BaseStrategy):
    pass
'''
        result = synthesizer.validate_types(code)
        assert not result.valid
        assert any("RiskManager" in e for e in result.errors)


class TestStrategySynthesizerLintCode:
    def test_clean_code_passes(self):
        synthesizer, _, _ = make_synthesizer_session()
        code = "x = 1\ny = 2\nprint(x + y)"
        result = synthesizer.lint_code(code)
        assert result.valid

    def test_forbidden_os_import_fails(self):
        synthesizer, _, _ = make_synthesizer_session()
        code = "import os\nprint(os.getcwd())"
        result = synthesizer.lint_code(code)
        assert not result.valid
        assert any("os" in e for e in result.errors)

    def test_forbidden_subprocess_fails(self):
        synthesizer, _, _ = make_synthesizer_session()
        code = "import subprocess\nsubprocess.run(['ls'])"
        result = synthesizer.lint_code(code)
        assert not result.valid
        assert any("subprocess" in e for e in result.errors)


class TestStrategySynthesizerSafeImport:
    def test_safe_import_succeeds(self):
        synthesizer, _, _ = make_synthesizer_session()
        code = '''
class GeneratedStrategy:
    def run(self):
        return []
'''
        result = synthesizer.safe_import_test(code)
        assert result.valid

    def test_unsafe_import_fails(self):
        synthesizer, _, _ = make_synthesizer_session()
        code = "import os\nos.remove('test')"
        result = synthesizer.safe_import_test(code)
        assert not result.valid


class TestStrategySynthesizerRegister:
    def test_register_valid_strategy(self):
        synthesizer, session, _ = make_synthesizer_session()
        generated = GeneratedStrategy(
            name="test_strat",
            code="class test_strat(BaseStrategy):\n    def __init__(self):\n        self.risk = RiskManager()",
            description="Test",
            regime=MarketRegime.BULL,
            validation_passed=True,
        )
        experiment_id = synthesizer.register_generated(generated)
        assert experiment_id is not None
        record = session.query(ExperimentRecord).filter_by(id=int(experiment_id)).first()
        assert record is not None
        assert record.status == "shadow"

    def test_register_invalid_syntax_fails(self):
        synthesizer, _, _ = make_synthesizer_session()
        generated = GeneratedStrategy(
            name="bad_strat",
            code="invalid syntax here ===",
            description="Bad",
            regime=MarketRegime.BEAR,
        )
        with pytest.raises(ValueError, match="Syntax validation failed"):
            synthesizer.register_generated(generated)


class TestStrategySynthesizerCostTracking:
    def test_track_cost_within_limit(self):
        synthesizer, _, _ = make_synthesizer_session()
        result = synthesizer.track_cost(0.30)
        assert result is True

    def test_track_cost_exceeds_limit(self):
        synthesizer, _, _ = make_synthesizer_session()
        result = synthesizer.track_cost(0.60)
        assert result is False

    def test_track_cost_accumulates(self):
        synthesizer, _, _ = make_synthesizer_session()
        synthesizer.track_cost(0.50)
        synthesizer.track_cost(0.50)
        synthesizer.track_cost(0.50)
        result = synthesizer.track_cost(0.50)
        assert result is False


class TestGeneratedStrategy:
    def test_to_dict(self):
        gs = GeneratedStrategy(
            name="test",
            code="print('hello')",
            description="Test strategy",
            regime=MarketRegime.BULL,
            validation_passed=True,
        )
        d = gs.to_dict()
        assert d["name"] == "test"
        assert d["regime"] == "bull"
        assert d["validation_passed"] is True

    def test_creation(self):
        gs = GeneratedStrategy(
            name="my_strat",
            code="x = 1",
            description="My strategy",
            regime=MarketRegime.SIDEWAYS,
        )
        assert gs.name == "my_strat"
        assert gs.regime == MarketRegime.SIDEWAYS


class TestValidationResult:
    def test_valid_result(self):
        vr = ValidationResult(valid=True)
        assert vr.valid
        assert bool(vr) is True

    def test_invalid_result(self):
        vr = ValidationResult(valid=False, errors=["SyntaxError"])
        assert not vr.valid
        assert bool(vr) is False
        assert len(vr.errors) == 1
