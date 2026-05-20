from backend.core.execution_pipeline.base import BaseExecutionStage, ExecutionStageManifest
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
        state = ctx.get("state")

        if state:
            if mode == "paper" and hasattr(state, "paper_bankroll"):
                state.paper_bankroll = (state.paper_bankroll or 0.0) - float(decision.get("size", 0.0))
                state.paper_trades = (state.paper_trades or 0) + 1
            elif mode == "testnet" and hasattr(state, "testnet_bankroll"):
                state.testnet_bankroll = (state.testnet_bankroll or 0.0) - float(decision.get("size", 0.0))
                state.testnet_trades = (state.testnet_trades or 0) + 1
            elif mode == "live" and hasattr(state, "bankroll"):
                state.bankroll = (state.bankroll or 0.0) - float(decision.get("size", 0.0))
                state.total_trades = (state.total_trades or 0) + 1

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
