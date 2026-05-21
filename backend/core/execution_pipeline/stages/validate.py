from loguru import logger

from backend.core.execution_pipeline.base import (
    BaseExecutionStage,
    ExecutionStageManifest,
)
from backend.core.execution_pipeline.registry import registry
from backend.core.risk_manager import RiskManager


class ValidationStage(BaseExecutionStage):
    @classmethod
    def manifest(cls):
        return ExecutionStageManifest(
            name="validation",
            display_name="Risk Validation",
            version="1.0.0",
            mode="*",
            order=1,
            required_env_vars=[],
            tags=["validation", "risk"],
        )

    def __init__(self):
        self.risk_manager = RiskManager()

    def validate(self, decision, ctx):
        size = float(decision.get("size", 0.0))
        current_exposure = ctx.get("current_exposure", 0.0)
        bankroll = ctx.get("bankroll", 0.0)
        confidence = float(decision.get("confidence", 0.0))
        market_ticker = decision.get("market_ticker")
        mode = ctx.get("mode", "paper")
        strategy_name = ctx.get("strategy_name", "unknown")
        direction = decision.get("direction")

        risk_decision = self.risk_manager.validate_trade(
            size=size,
            current_exposure=current_exposure,
            bankroll=bankroll,
            confidence=confidence,
            market_ticker=market_ticker,
            mode=mode,
            strategy_name=strategy_name,
            direction=direction,
        )

        return risk_decision.allowed

    def execute(self, decision, ctx):
        return {"validation_passed": True}

    def record(self, decision, result, ctx):
        market_ticker = decision.get("market_ticker", "unknown")
        passed = result.get("validation_passed", False)
        logger.info(
            "[ValidationStage] recorded: market={} passed={}",
            market_ticker, passed,
        )


registry.plugin(ValidationStage)
