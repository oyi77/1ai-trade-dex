from typing import Dict, Any, Optional

from loguru import logger


class BnbHackAlerter:
    def __init__(self):
        self._registry = None
        self._enabled = False
        self._load_registry()

    def _load_registry(self):
        try:
            from backend.bot.notification import NotificationRegistry
            self._registry = NotificationRegistry()
            enabled = self._registry.get_enabled()
            self._enabled = len(enabled) > 0
            if self._enabled:
                logger.info("Notification providers available: {}", enabled)
        except Exception as e:
            logger.warning("Notification registry not available: {}", e)
            self._enabled = False

    async def send_alert(self, title: str, message: str, event_type: str = "trade",
                         details: Optional[Dict[str, Any]] = None):
        if not self._enabled or not self._registry:
            return

        try:
            await self._registry.broadcast(message, event_type, details or {})
        except Exception as e:
            logger.error("Alert send failed: {}", e)

    async def on_buy(self, price: float, amount: float, confidence: float, reason: str):
        title = f"🟢 BUY Signal"
        message = f"BNB Buy @ ${price:.2f}\nAmount: ${amount:.2f}\nConfidence: {confidence:.0%}\nReason: {reason}"
        details = {
            "action": "buy",
            "price": price,
            "amount": amount,
            "confidence": confidence,
            "reason": reason,
        }
        await self.send_alert(title, message, "trade", details)

    async def on_sell(self, price: float, pnl_usd: float, pnl_pct: float, reason: str):
        emoji = "🟢" if pnl_usd >= 0 else "🔴"
        title = f"{emoji} SELL Signal"
        message = f"BNB Sell @ ${price:.2f}\nP&L: ${pnl_usd:+.2f} ({pnl_pct:+.1f}%)\nReason: {reason}"
        details = {
            "action": "sell",
            "price": price,
            "pnl_usd": pnl_usd,
            "pnl_pct": pnl_pct,
            "reason": reason,
        }
        await self.send_alert(title, message, "trade", details)

    async def on_error(self, error_type: str, error_msg: str):
        title = f"⚠️ Error: {error_type}"
        message = f"BNB HACK Bot Error\n{error_msg}"
        details = {
            "error_type": error_type,
            "error_message": error_msg,
        }
        await self.send_alert(title, message, "error", details)

    async def on_risk_limit_hit(self, limit_type: str, value: float):
        title = f"🛑 Risk Limit Hit"
        message = f"BNB HACK Risk Alert\nLimit: {limit_type}\nValue: {value}"
        details = {
            "limit_type": limit_type,
            "value": value,
        }
        await self.send_alert(title, message, "risk", details)

    async def on_daily_summary(self, pnl_usd: float, trades: int, win_rate: float):
        message = (
            f"📊 Daily Summary\n"
            f"P&L: ${pnl_usd:+.2f}\n"
            f"Trades: {trades}\n"
            f"Win Rate: {win_rate:.1f}%"
        )
        details = {
            "pnl_usd": pnl_usd,
            "trades": trades,
            "win_rate": win_rate,
        }
        await self.send_alert("Daily Report", message, "summary", details)
