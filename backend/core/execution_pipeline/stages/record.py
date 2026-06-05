from backend.core.execution_pipeline.base import (
    BaseExecutionStage,
    ExecutionStageManifest,
)
from backend.core.execution_pipeline.registry import registry


class RecordStage(BaseExecutionStage):
    @classmethod
    def manifest(cls):
        return ExecutionStageManifest(
            name="record",
            display_name="Record Execution",
            version="1.0.0",
            mode="*",
            order=3,
            required_env_vars=[],
            tags=["persistence", "record"],
        )

    def execute(self, decision, ctx):
        db = ctx.get("db")
        if db is None:
            return {"status": "skipped", "reason": "No database session"}

        mode = ctx.get("mode", "paper")
        size = float(decision.get("size", 0.0) or 0.0)
        price = float(decision.get("entry_price", decision.get("price", 0.0)) or 0.0)

        from backend.core.wallet.botstate_ledger import BotStateLedger

        try:
            BotStateLedger.debit_for_fill(
                db=db,
                mode=mode,
                size=size,
                price=price,
                source="execution_pipeline.record",
            )
        except LookupError as exc:
            return {"status": "skipped", "reason": str(exc)}

        return {"status": "recorded", "state_updated": True}

    def record(self, decision, result, ctx):
        db = ctx.get("db")
        if db is None:
            return

        trade_id = ctx.get("trade_id")
        if trade_id:
            pass

    def validate(self, decision, ctx):
        return True

    def health_check(self):
        return True


registry.plugin(RecordStage)
