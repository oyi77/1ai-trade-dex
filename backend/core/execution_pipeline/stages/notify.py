from loguru import logger

from backend.core.execution_pipeline.base import BaseExecutionStage, ExecutionStageManifest
from backend.core.execution_pipeline.registry import registry
from backend.bot.notification.registry import registry as notification_registry


class NotifyStage(BaseExecutionStage):
    @classmethod
    def manifest(cls):
        return ExecutionStageManifest(
            name="notify",
            display_name="Notify Events",
            version="1.0.0",
            mode="*",
            order=4,
            required_env_vars=[],
            tags=["notification", "events"],
        )

    def execute(self, decision, ctx):
        market_ticker = decision.get("market_ticker", "")
        direction = decision.get("direction", "")
        size = float(decision.get("size", 0.0))
        entry_price = float(decision.get("entry_price", 0.5))
        confidence = float(decision.get("confidence", 0.0))
        mode = ctx.get("mode", "paper")
        strategy_name = ctx.get("strategy_name", "unknown")

        event = {
            "type": "trade_executed",
            "market_ticker": market_ticker,
            "direction": direction,
            "size": size,
            "entry_price": entry_price,
            "confidence": confidence,
            "mode": mode,
            "strategy_name": strategy_name,
        }

        for name, provider in notification_registry._plugins.items():
            if notification_registry._enabled.get(name, False):
                try:
                    provider.send(event)
                except Exception:
                    logger.warning("Notification provider '%s' failed", name, exc_info=True)

        return {"status": "notified", "providers_notified": len(notification_registry._plugins)}

    def record(self, decision, result, ctx):
        pass

    def validate(self, decision, ctx):
        return True

    def health_check(self):
        try:
            from backend.bot.notification.registry import notification_registry
            notification_registry
            return True
        except Exception:
            return False


registry.plugin(NotifyStage)
