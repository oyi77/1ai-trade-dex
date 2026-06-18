import asyncio
import csv
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

from backend.bot.bnb_hack.alerter import BnbHackAlerter
from backend.bot.bnb_hack.data_feed import BinanceFeed
from backend.bot.bnb_hack.exchange import LiveTWAKExchange, PaperEngine
from backend.bot.bnb_hack.metrics import MetricsCollector, TradeMetrics
from backend.bot.bnb_hack.signals import SignalEngine
from backend.bot.bnb_hack.state import BotState, Position
from backend.clients.twak_client import TWAKClient, TWAKConfig
from backend.config import settings


class BnbHackBot:
    def __init__(
        self,
        feed: BinanceFeed,
        signal_engine: SignalEngine,
        exchange: Any,
        state: Optional[BotState] = None,
        metrics: Optional[MetricsCollector] = None,
        alerter: Optional[BnbHackAlerter] = None,
    ):
        self.feed = feed
        self.signals = signal_engine
        self.exchange = exchange
        self.state = state or BotState()
        self.metrics = metrics or MetricsCollector()
        self.alerter = alerter or BnbHackAlerter()
        self._running = False
        self._log_path = Path("logs/bnb_hack_trades.csv")
        self._started_at = datetime.now(timezone.utc)
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._log_path.exists():
            with open(self._log_path, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow([
                    "timestamp", "action", "token", "price", "amount_usdc",
                    "amount_token", "pnl_usdc", "reason", "sma_fast", "sma_slow",
                ])

    @classmethod
    def from_config(cls, paper: bool = False) -> "BnbHackBot":
        feed = BinanceFeed()
        config = TWAKConfig(
            access_id=settings.bnb_hack.access_id,
            hmac_secret=settings.bnb_hack.hmac_secret,
            wallet_password=settings.bnb_hack.wallet_password,
            default_chain="bsc",
        )
        exchange = PaperEngine() if paper else LiveTWAKExchange(TWAKClient(config))
        return cls(feed, SignalEngine(feed), exchange)

    async def close(self):
        await self.feed.close()

    def has_position(self) -> bool:
        return len(self.state.positions) > 0

    async def _check_exit(self, price: float) -> Optional[str]:
        if not self.has_position():
            return None
        pos = list(self.state.positions.values())[0]
        pnl = ((price - pos.entry_price) / pos.entry_price) * 100
        if pnl >= settings.bnb_hack.take_profit_pct:
            return "take_profit"
        if pnl <= -settings.bnb_hack.stop_loss_pct:
            return "stop_loss"
        return None

    async def _buy(self, signal: Dict[str, Any]) -> bool:
        bal = await self.exchange.balance()
        usdc = float(next(
            (t["balance"] for t in bal.get("tokens", []) if t["symbol"] == "USDC"), "0"
        ))
        if usdc < 1:
            logger.warning("USDC too low to trade — ${}", usdc)
            return False
        amount = round(usdc * (settings.bnb_hack.max_position_pct / 100), 2)
        if amount < 1:
            logger.warning("Trade amount too small: ${}", amount)
            return False
        price = signal["price"]
        logger.info("BUY ${} USDC -> BNB @ ${} (conf: {})",
                     amount, price, signal["confidence"])
        result = await self.exchange.swap(str(amount), "USDC", "BNB")
        token_qty = result.get("toAmount", 0)
        logger.info("BUY filled: {} BNB", token_qty)
        await self.alerter.on_buy(price, amount, signal["confidence"], signal["reason"])
        self.state.positions["BNB"] = Position(
            token="BNB",
            entry_time=datetime.now(timezone.utc),
            entry_price=price,
            amount_token=token_qty,
            amount_usdc=amount,
            take_profit=price * (1 + settings.bnb_hack.take_profit_pct / 100),
            stop_loss=price * (1 - settings.bnb_hack.stop_loss_pct / 100),
        )
        self._log("buy", price, amount, token_qty, 0, signal["reason"], signal)
        return True

    async def _sell(self, reason: str) -> bool:
        if not self.has_position():
            return False
        pos = list(self.state.positions.values())[0]
        price = await self.feed.get_price("BNBUSDT")
        pnl = ((price - pos.entry_price) / pos.entry_price) * 100
        logger.info("SELL {} BNB -> USDC (reason: {}, PnL: {:+.2f}%)",
                     pos.amount_token, reason, pnl)
        result = await self.exchange.swap(str(round(pos.amount_token, 6)), "BNB", "USDC")
        usdc_recv = float(result.get("toAmount", 0))
        trade_pnl = usdc_recv - pos.amount_usdc
        self.state.total_pnl_usd += trade_pnl
        self.state.daily_pnl_usd += trade_pnl
        logger.info("SELL filled: ${} USDC (PnL: ${:+.2f}, {:+.2f}%)",
                     usdc_recv, trade_pnl, pnl)
        await self.alerter.on_sell(price, trade_pnl, pnl, reason)
        self._log("sell", price, pos.amount_usdc, usdc_recv, trade_pnl, reason, {})
        if trade_pnl < 0:
            self.state.consecutive_losses += 1
            if self.state.consecutive_losses >= settings.bnb_hack.max_consecutive_losses:
                logger.warning("{} consecutive losses — halting",
                               settings.bnb_hack.max_consecutive_losses)
                await self.alerter.on_risk_limit_hit(
                    "consecutive_losses",
                    self.state.consecutive_losses
                )
                self.state.in_cooldown = True
                self.state.cooldown_until = datetime.now(timezone.utc) + timedelta(hours=4)
        else:
            self.state.consecutive_losses = 0
        if pnl <= -settings.bnb_hack.stop_loss_pct:
            self.state.in_cooldown = True
            self.state.cooldown_until = datetime.now(timezone.utc) + timedelta(
                minutes=settings.bnb_hack.cooldown_minutes
            )
        self.state.positions.clear()
        self.state.trades_today += 1
        return True

    def _log(self, action, price, amount_usdc, amount_token, pnl, reason, signal):
        ind = signal.get("indicators", {})
        now = datetime.now(timezone.utc)
        with open(self._log_path, "a", newline="") as f:
            w = csv.writer(f)
            w.writerow([
                now.isoformat(),
                action, "BNB", round(price, 2),
                round(amount_usdc, 2), round(amount_token, 6), round(pnl, 2),
                reason, ind.get("sma_fast", ""), ind.get("sma_slow", ""),
            ])
        trade = TradeMetrics(
            timestamp=now,
            action=action,
            token="BNB",
            price=price,
            amount_usdc=amount_usdc,
            amount_token=amount_token,
            pnl_usdc=pnl,
            reason=reason,
            sma_fast=ind.get("sma_fast"),
            sma_slow=ind.get("sma_slow"),
        )
        self.metrics.record_trade(trade)

    async def tick(self) -> str:
        now = datetime.now(timezone.utc)
        if self.state.in_cooldown and self.state.cooldown_until:
            if now < self.state.cooldown_until:
                remaining = int((self.state.cooldown_until - now).total_seconds() // 60)
                return f"cooldown ({remaining}m)"
            self.state.in_cooldown = False
            self.state.cooldown_until = None
        if self.state.daily_pnl_usd <= -settings.bnb_hack.max_daily_loss_usd:
            await self.alerter.on_risk_limit_hit("daily_loss_limit", self.state.daily_pnl_usd)
            return "daily_loss_limit"
        try:
            price = await self.feed.get_price("BNBUSDT")
        except Exception as e:
            logger.error("Price fetch: {}", e)
            await self.alerter.on_error("price_fetch", str(e))
            return "price_error"
        if self.has_position():
            exit_reason = await self._check_exit(price)
            if exit_reason:
                await self._sell(exit_reason)
                return exit_reason
            pos = list(self.state.positions.values())[0]
            pnl = ((price - pos.entry_price) / pos.entry_price) * 100
            return f"holding ({pnl:+.2f}%)"
        signal = await self.signals.evaluate()
        if signal["action"] == "buy" and signal["confidence"] >= settings.bnb_hack.min_confidence:
            await self._buy(signal)
            return f"buy (conf: {signal['confidence']})"
        ind = signal.get("indicators", {})
        return f"hold (SMA: {ind.get('sma_cross', '?')})"

    async def run(self):
        self._running = True
        last_day = datetime.now(timezone.utc).day
        logger.info("Bot loop started — paper={}, interval={}s",
                     isinstance(self.exchange, PaperEngine),
                     settings.bnb_hack.check_interval_seconds)
        while self._running:
            try:
                now = datetime.now(timezone.utc)
                if now.day != last_day:
                    self.state.daily_pnl_usd = 0.0
                    self.state.trades_today = 0
                    last_day = now.day
                    logger.info("Daily reset — total PnL: ${:+.2f}", self.state.total_pnl_usd)

                self.metrics.update_equity(self.state.total_pnl_usd)
                start_dt = datetime.fromisoformat(
                    settings.bnb_hack.competition_start.replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(
                    settings.bnb_hack.competition_end.replace("Z", "+00:00"))
                if not (start_dt <= now <= end_dt):
                    delta = (start_dt - now).days if now < start_dt else 0
                    logger.info("Idle — competition {}", f"starts in {delta}d" if delta else "ended")
                    await asyncio.sleep(60)
                    continue
                result = await self.tick()
                logger.info("[{}] {}", now.strftime("%H:%M"), result)
                logger.info("  PnL: ${:+.2f} total | ${:+.2f} today | {} trades",
                             self.state.total_pnl_usd, self.state.daily_pnl_usd,
                             self.state.trades_today)
                await asyncio.sleep(settings.bnb_hack.check_interval_seconds)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Cycle error")
                await asyncio.sleep(30)
        self._running = False
        await self.close()
        logger.info("Bot stopped. Duration: {}", datetime.now(timezone.utc) - self._started_at)
