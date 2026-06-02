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
            version="1.1.0",
            mode="*",
            order=1,
            required_env_vars=[],
            tags=["validation", "risk", "dedup"],
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
        token_id = decision.get("token_id")
        db = ctx.get("db")

        # ── Permanent Fix: prevent duplicate trades on same token_id ──
        if db is not None and token_id:
            try:
                from sqlalchemy import text as _sql_text
                existing = db.execute(
                    _sql_text(
                        "SELECT id FROM trades "
                        "WHERE token_id = :tid AND trading_mode = :mode "
                        "AND status NOT IN ('closed', 'SETTLED', 'cancelled', 'error', 'closed_errored')"
                    ),
                    {"tid": token_id, "mode": mode},
                ).fetchone()
                if existing:
                    logger.warning(
                        f"[ValidationStage] DUPLICATE BLOCKED: token_id={token_id} "
                        f"mode={mode} already has open trade id={existing[0]}"
                    )
                    return False
            except Exception as e:
                logger.debug(f"[ValidationStage] dedup check failed (non-fatal): {e}")

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
            market_ticker,
            passed,
        )


registry.plugin(ValidationStage)
