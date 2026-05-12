from backend.core.execution_pipeline.base import BaseExecutionStage, ExecutionStageManifest
from backend.core.execution_pipeline.registry import registry


class LiveExecuteStage(BaseExecutionStage):
    @classmethod
    def manifest(cls):
        return ExecutionStageManifest(
            name="live_execute",
            display_name="Live Execution",
            version="1.0.0",
            mode="live",
            order=2,
            required_env_vars=["CLOB_API_URL", "CLOB_API_KEY", "CLOB_SECRET_KEY", "CLOB_PASSPHRASE"],
            tags=["execution", "live", "clob"],
        )

    def validate(self, decision, ctx):
        market_ticker = decision.get("market_ticker", "")
        token_id = decision.get("token_id")
        if not token_id:
            return False
        return True

    def execute(self, decision, ctx):
        db = ctx.get("db")
        if db is None:
            return {"status": "error", "reason": "No database session"}

        from backend.markets.provider_registry import market_registry

        market_ticker = decision.get("market_ticker", "")
        platform = decision.get("platform", "polymarket")
        direction = decision.get("direction", "")
        size = float(decision.get("size", 0.0))
        entry_price = float(decision.get("entry_price", 0.5))

        is_kalshi = market_ticker.startswith("KX") or platform == "kalshi"

        try:
            provider_name = "kalshi" if is_kalshi else "polymarket"
            client = market_registry.get(provider_name)
        except Exception:
            return {
                "status": "error",
                "reason": "Market provider not available",
            }

        if not is_kalshi:
            return self._execute_polymarket(client, decision, ctx)

        return self._execute_kalshi(client, decision, ctx)

    def _execute_polymarket(self, client, decision, ctx):
        token_id = decision.get("token_id")
        direction = decision.get("direction", "")
        size = float(decision.get("size", 0.0))
        entry_price = float(decision.get("entry_price", 0.5))

        order_type = "sell" if direction.upper() in ("NO", "SELL") else "buy"

        try:
            result = client.place_order(
                token_id=token_id,
                order_type=order_type,
                price=entry_price,
                size=size,
            )

            return {
                "status": "executed",
                "order_id": result.get("order_id"),
                "fill_price": result.get("fill_price", entry_price),
                "filled_size": result.get("filled_size", size),
            }
        except Exception as e:
            return {
                "status": "error",
                "reason": str(e),
            }

    def _execute_kalshi(self, client, decision, ctx):
        market_ticker = decision.get("market_ticker", "")
        direction = decision.get("direction", "")
        size = float(decision.get("size", 0.0))
        entry_price = float(decision.get("entry_price", 0.5))
        side = "yes" if direction.upper() == "YES" else "no"

        try:
            result = client.place_order(
                market=market_ticker,
                side=side,
                price=entry_price,
                size=size,
            )

            return {
                "status": "executed",
                "order_id": result.get("order_id"),
                "fill_price": result.get("fill_price", entry_price),
                "filled_size": result.get("filled_size", size),
            }
        except Exception as e:
            return {
                "status": "error",
                "reason": str(e),
            }

    def record(self, decision, result, ctx):
        if result["status"] == "error":
            return

        db = ctx.get("db")
        if db is None:
            return

        state = ctx.get("state")
        mode = ctx.get("mode", "live")
        adjusted_size = float(decision.get("size", 0.0))

        if state and mode == "live":
            state.bankroll = max(0.0, (state.bankroll or 0.0) - adjusted_size)
            state.total_trades = (state.total_trades or 0) + 1

    def health_check(self):
        try:
            from backend.markets.provider_registry import market_registry
            polymarket = market_registry.get("polymarket")
            if polymarket:
                if not polymarket.health_check():
                    return False
            return True
        except Exception:
            return False


registry.plugin(LiveExecuteStage)
