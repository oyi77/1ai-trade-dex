from backend.core.execution_pipeline.base import BaseExecutionStage, ExecutionStageManifest
from backend.core.execution_pipeline.registry import registry
from backend.core.paper_slippage import PaperSlippageSimulator


class PaperSimulationStage(BaseExecutionStage):
    @classmethod
    def manifest(cls):
        return ExecutionStageManifest(
            name="paper_simulate",
            display_name="Paper Simulation",
            version="1.0.0",
            mode="paper",
            order=2,
            required_env_vars=[],
            tags=["simulation", "paper"],
        )

    def __init__(self):
        self.simulator = PaperSlippageSimulator()

    def execute(self, decision, ctx):
        db = ctx.get("db")
        entry_price = float(decision.get("entry_price", 0.5))
        size = float(decision.get("size", 0.0))
        direction = decision.get("direction", "")
        market_ticker = decision.get("market_ticker", "")

        result = self.simulator.simulate_fill(
            entry_price=entry_price,
            size=size,
            direction=direction,
            market_ticker=market_ticker,
            db=db,
        )

        if result["rejected"]:
            return {
                "status": "rejected",
                "rejection_reason": result.get("rejection_reason", "Unknown rejection"),
            }

        return {
            "status": "simulated",
            "fill_price": result["fill_price"],
            "slippage_bps": result["slippage_bps"],
            "fee_usd": result["fee_usd"],
            "slippage_allowed": True,
        }

    def record(self, decision, result, ctx):
        db = ctx.get("db")
        if db is None:
            return

        mode = ctx.get("mode", "paper")
        state = ctx.get("state")
        adjusted_size = float(decision.get("size", 0.0))

        if state:
            if mode == "paper" and hasattr(state, "paper_bankroll"):
                state.paper_bankroll = (state.paper_bankroll or 0.0) - adjusted_size
                state.paper_trades = (state.paper_trades or 0) + 1
            elif mode == "testnet" and hasattr(state, "testnet_bankroll"):
                state.testnet_bankroll = (state.testnet_bankroll or 0.0) - adjusted_size
                state.testnet_trades = (state.testnet_trades or 0) + 1

    def validate(self, decision, ctx):
        return True

    def health_check(self):
        try:
            self.simulator
            return True
        except Exception:
            return False


registry.plugin(PaperSimulationStage)
