import importlib
import pytest
from unittest.mock import MagicMock, patch

import sys

sys.path.insert(0, "/home/openclaw/projects/1ai-trade-dex")

from backend.core.execution_pipeline.base import (
    BaseExecutionStage,
    ExecutionStageManifest,
)
from backend.core.execution_pipeline.registry import ExecutionPipelineRegistry, registry
from backend.core.plugin_errors import PluginNotFound


class TestValidationStage:

    def setup_method(self, method):
        ExecutionPipelineRegistry.reset()

    def test_validate_passed(self):
        from backend.core.execution_pipeline.stages.validate import ValidationStage

        stage = ValidationStage()
        decision = {
            "size": 100.0,
            "confidence": 0.8,
            "direction": "YES",
            "market_ticker": "US election",
        }
        ctx = {
            "mode": "paper",
            "bankroll": 1000.0,
            "current_exposure": 100.0,
            "strategy_name": "test_strategy",
        }

        result = stage.validate(decision, ctx)

        assert result is True

    def test_validate_rejected_low_confidence(self):
        from backend.core.execution_pipeline.stages.validate import ValidationStage

        stage = ValidationStage()
        decision = {
            "size": 100.0,
            "confidence": 0.1,
            "direction": "YES",
            "market_ticker": "US election",
        }
        ctx = {
            "mode": "paper",
            "bankroll": 1000.0,
            "current_exposure": 100.0,
            "strategy_name": "test_strategy",
        }

        result = stage.validate(decision, ctx)

        assert result is False


class TestPaperSimulationStage:

    def setup_method(self, method):
        ExecutionPipelineRegistry.reset()

    def test_execute_simulation(self):
        from backend.core.execution_pipeline.stages.simulate import PaperSimulationStage

        stage = PaperSimulationStage()
        decision = {
            "entry_price": 0.5,
            "size": 100.0,
            "direction": "YES",
            "market_ticker": "US election",
        }
        ctx = {
            "db": None,
            "mode": "paper",
        }

        result = stage.execute(decision, ctx)

        assert "status" in result

    def test_validate_always_passes(self):
        from backend.core.execution_pipeline.stages.simulate import PaperSimulationStage

        stage = PaperSimulationStage()
        decision = {"test": "decision"}
        ctx = {"mode": "paper"}

        result = stage.validate(decision, ctx)

        assert result is True


class TestLiveExecuteStage:

    def setup_method(self, method):
        ExecutionPipelineRegistry.reset()

    def test_validate_with_token_id(self):
        from backend.core.execution_pipeline.stages.execute import LiveExecuteStage

        stage = LiveExecuteStage()
        decision = {
            "token_id": "0x123",
            "market_ticker": "US election",
        }
        ctx = {"mode": "live"}

        result = stage.validate(decision, ctx)

        assert result is True

    def test_validate_without_token_id(self):
        from backend.core.execution_pipeline.stages.execute import LiveExecuteStage

        stage = LiveExecuteStage()
        decision = {
            "market_ticker": "US election",
        }
        ctx = {"mode": "live"}

        result = stage.validate(decision, ctx)

        assert result is False

    def test_health_check(self):
        from backend.core.execution_pipeline.stages.execute import LiveExecuteStage

        stage = LiveExecuteStage()

        with patch(
            "backend.markets.provider_registry.market_registry"
        ) as mock_registry:
            mock_manager = MagicMock()
            mock_provider = MagicMock()
            mock_provider.health_check.return_value = True
            mock_manager.get.return_value = mock_provider
            mock_registry._plugins = {"polymarket": mock_provider}
            mock_registry.get = mock_manager.get

            result = stage.health_check()

            assert result is True


class TestRecordStage:

    def setup_method(self, method):
        ExecutionPipelineRegistry.reset()

    def test_execute_record(self):
        from backend.core.execution_pipeline.stages.record import RecordStage

        stage = RecordStage()
        decision = {
            "size": 100.0,
        }
        ctx = {
            "mode": "paper",
            "db": MagicMock(),
            "state": MagicMock(),
        }
        ctx["state"].paper_bankroll = 1000.0
        ctx["state"].paper_trades = 0

        result = stage.execute(decision, ctx)

        assert result["status"] == "recorded"
        assert result["state_updated"] is True

    def test_validate_always_passes(self):
        from backend.core.execution_pipeline.stages.record import RecordStage

        stage = RecordStage()
        result = stage.validate({}, {})
        assert result is True


class TestNotifyStage:

    def setup_method(self, method):
        ExecutionPipelineRegistry.reset()

    def test_execute_notify(self):
        from backend.core.execution_pipeline.stages.notify import NotifyStage

        stage = NotifyStage()
        decision = {
            "market_ticker": "US election",
            "direction": "YES",
            "size": 100.0,
            "entry_price": 0.5,
            "confidence": 0.8,
        }
        ctx = {
            "mode": "paper",
            "strategy_name": "test_strategy",
        }

        result = stage.execute(decision, ctx)

        assert result["status"] == "notified"
        assert "providers_notified" in result

    def test_validate_always_passes(self):
        from backend.core.execution_pipeline.stages.notify import NotifyStage

        stage = NotifyStage()
        result = stage.validate({}, {})
        assert result is True


class TestRegistry:

    def setup_method(self, method):
        ExecutionPipelineRegistry.reset()

    def test_register_valid_stage(self):
        class TestStage(BaseExecutionStage):
            @classmethod
            def manifest(cls):
                return ExecutionStageManifest(
                    name="test_stage",
                    display_name="Test Stage",
                    version="1.0.0",
                    mode="*",
                    order=1,
                    required_env_vars=[],
                    tags=[],
                )

            def validate(self, decision, ctx):
                return True

            def execute(self, decision, ctx):
                return {}

            def record(self, decision, result, ctx):
                pass

        registry.register(TestStage)

        assert "test_stage" in registry._plugins
        assert registry._enabled["test_stage"] is True
        assert registry._health_status["test_stage"] is True

    def test_get_missing_stage(self):
        with pytest.raises(PluginNotFound):
            registry.get("nonexistent")

    def test_get_disabled_stage(self):
        class SimpleStage(BaseExecutionStage):
            @classmethod
            def manifest(cls):
                return ExecutionStageManifest(
                    name="simple",
                    display_name="Simple",
                    version="1.0.0",
                    mode="*",
                    order=1,
                    required_env_vars=[],
                    tags=[],
                )

            def validate(self, decision, ctx):
                return True

            def execute(self, decision, ctx):
                return {}

            def record(self, decision, result, ctx):
                pass

        registry.register(SimpleStage)
        registry.set_enabled("simple", False)

        with pytest.raises(PluginNotFound):
            registry.get("simple")

    def test_run_pipeline(self):
        class TestPipelineStage(BaseExecutionStage):
            @classmethod
            def manifest(cls):
                return ExecutionStageManifest(
                    name="pipeline_test",
                    display_name="Pipeline Test",
                    version="1.0.0",
                    mode="*",
                    order=1,
                    required_env_vars=[],
                    tags=[],
                )

            def validate(self, decision, ctx):
                return True

            def execute(self, decision, ctx):
                return {"pipeline_test": True}

            def record(self, decision, result, ctx):
                pass

        registry.register(TestPipelineStage)

        decision = {
            "size": 100.0,
            "confidence": 0.8,
            "direction": "YES",
            "market_ticker": "test",
        }
        context = {
            "mode": "paper",
            "bankroll": 1000.0,
            "current_exposure": 0.0,
            "strategy_name": "test_strategy",
        }

        result = registry.run_pipeline(decision, context)

        assert result["pipeline_test"] is True

    def test_run_mode_filter(self):
        class PaperStage(BaseExecutionStage):
            @classmethod
            def manifest(cls):
                return ExecutionStageManifest(
                    name="paper_stage",
                    display_name="Paper Stage",
                    version="1.0.0",
                    mode="paper",
                    order=1,
                    required_env_vars=[],
                    tags=[],
                )

            def validate(self, decision, ctx):
                return True

            def execute(self, decision, ctx):
                return {"paper_mode": True}

            def record(self, decision, result, ctx):
                pass

        class LiveStage(BaseExecutionStage):
            @classmethod
            def manifest(cls):
                return ExecutionStageManifest(
                    name="live_stage",
                    display_name="Live Stage",
                    version="1.0.0",
                    mode="live",
                    order=1,
                    required_env_vars=[],
                    tags=[],
                )

            def validate(self, decision, ctx):
                return True

            def execute(self, decision, ctx):
                return {"live_mode": True}

            def record(self, decision, result, ctx):
                pass

        registry.register(PaperStage)
        registry.register(LiveStage)

        decision = {
            "size": 100.0,
            "confidence": 0.8,
            "direction": "YES",
            "market_ticker": "test",
        }
        context = {
            "mode": "paper",
            "bankroll": 1000.0,
            "current_exposure": 0.0,
            "strategy_name": "test_strategy",
        }

        result = registry.run_mode("paper", decision, context)

        assert result.get("paper_mode") is True
        assert "live_mode" not in result

    def test_auto_discover(self):
        # Earlier tests may have reset the singleton registry. Stage classes
        # register via import-time decorators, and reloading only the package
        # __init__ does not re-execute already-imported submodules — purge
        # them from sys.modules so the decorators run again.
        for name in [
            m
            for m in list(sys.modules)
            if m.startswith("backend.core.execution_pipeline.stages")
        ]:
            del sys.modules[name]
        import backend.core.execution_pipeline.stages  # noqa: F401

        from backend.core.execution_pipeline.registry import registry

        assert "validation" in registry._plugins
        assert "paper_simulate" in registry._plugins
        assert "live_execute" in registry._plugins
        assert "record" in registry._plugins
        assert "notify" in registry._plugins

    def test_health_check(self):
        registry.reset()

        result = registry.health_check()

        assert result is True or result is False

    def test_stage_failure_stops_pipeline(self):
        class FailingStage(BaseExecutionStage):
            @classmethod
            def manifest(cls):
                return ExecutionStageManifest(
                    name="failing_stage",
                    display_name="Failing Stage",
                    version="1.0.0",
                    mode="*",
                    order=1,
                    required_env_vars=[],
                    tags=[],
                )

            def validate(self, decision, ctx):
                return False

            def execute(self, decision, ctx):
                return {"failed": True}

            def record(self, decision, result, ctx):
                pass

        class LaterStage(BaseExecutionStage):
            @classmethod
            def manifest(cls):
                return ExecutionStageManifest(
                    name="later_stage",
                    display_name="Later Stage",
                    version="1.0.0",
                    mode="*",
                    order=2,
                    required_env_vars=[],
                    tags=[],
                )

            def validate(self, decision, ctx):
                return True

            def execute(self, decision, ctx):
                return {"later": True}

            def record(self, decision, result, ctx):
                pass

        registry.register(FailingStage)
        registry.register(LaterStage)

        decision = {"size": 100.0}
        context = {"mode": "paper"}

        result = registry.run_pipeline(decision, context)

        assert result.get("validation_failed") is True
        assert "later" not in result
