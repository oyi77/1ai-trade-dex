"""
PolyEdge Telegram Bot.

Provides:
- Signal alerts: weather (with COPY/SKIP keyboard) and copy trade (notify-only)
- Commands: /status /positions /leaderboard /pause /resume /settings /mode
- Admin-only guard for destructive commands
- Error alerting: unhandled exceptions forwarded to admin

Execution modes:
- Weather signals: sends alert with inline keyboard [COPY TRADE][SKIP][VIEW MARKET]
  User must press COPY TRADE to execute (confirm mode)
- Copy trade signals: auto-executes within risk limits, sends notification after
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional, Callable

from loguru import logger

try:
    from telegram import (
        Bot,
        InlineKeyboardButton,
        InlineKeyboardMarkup,
        Update,
    )
    from telegram.ext import (
        Application,
        CallbackQueryHandler,
        CommandHandler,
        ContextTypes,
    )
    from telegram.constants import ParseMode

    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    logger.warning("python-telegram-bot not installed — Telegram alerts disabled")


class PolyEdgeBot:
    """
    Telegram bot for PolyEdge.

    Usage:
        bot = PolyEdgeBot(token="...", admin_ids=[123456])
        await bot.start()
        await bot.send_weather_signal(signal)  # sends alert with keyboard
        await bot.send_copy_alert(signal)      # sends post-execution notify
        await bot.stop()
    """

    def __init__(
        self,
        token: str,
        admin_ids: list[int],
        on_copy_trade: Optional[Callable] = None,  # called when user presses COPY TRADE
        on_pause: Optional[Callable] = None,
        on_resume: Optional[Callable] = None,
        on_mode_switch: Optional[Callable] = None,
    ):
        self.token = token
        self.admin_ids = set(admin_ids)
        self.on_copy_trade = on_copy_trade
        self.on_pause = on_pause
        self.on_resume = on_resume
        self.on_mode_switch = on_mode_switch

        self._app: Optional["Application"] = None
        self._bot: Optional["Bot"] = None
        self._paused = False

        # Pending weather signals awaiting user confirmation
        # key: signal_id (condition_id), value: signal data dict
        self._pending_signals: dict[str, dict] = {}

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def start(self):
        """Initialize and start the bot (non-blocking — runs in background task)."""
        if not TELEGRAM_AVAILABLE:
            logger.warning("Telegram bot disabled — python-telegram-bot not installed")
            return

        if not self.token or self.token == "disabled":
            logger.info("Telegram bot token not configured — alerts disabled")
            return

        self._app = Application.builder().token(self.token).build()
        self._bot = self._app.bot

        # Register handlers
        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(CommandHandler("positions", self._cmd_positions))
        self._app.add_handler(CommandHandler("leaderboard", self._cmd_leaderboard))
        self._app.add_handler(CommandHandler("pause", self._cmd_pause))
        self._app.add_handler(CommandHandler("resume", self._cmd_resume))
        self._app.add_handler(CommandHandler("settings", self._cmd_settings))
        self._app.add_handler(CommandHandler("mode", self._cmd_mode))
        self._app.add_handler(CommandHandler("calibration", self._cmd_calibration))
        self._app.add_handler(CommandHandler("scan", self._cmd_scan))
        self._app.add_handler(CommandHandler("trades", self._cmd_trades))
        self._app.add_handler(CommandHandler("bankroll", self._cmd_bankroll))
        self._app.add_handler(CommandHandler("settle", self._cmd_settle))
        self._app.add_handler(CommandHandler("pnl", self._cmd_pnl))
        self._app.add_handler(CallbackQueryHandler(self._handle_callback))

        await self._app.initialize()
        await self._app.start()

        from backend.api.main import app
        if hasattr(app.state, 'task_manager'):
            await app.state.task_manager.create_task(
                self._app.updater.start_polling(drop_pending_updates=True),
                name="telegram_bot_polling"
            )
        else:
            asyncio.create_task(self._app.updater.start_polling(drop_pending_updates=True))
        logger.info(f"Telegram bot started — admins: {self.admin_ids}")

    async def stop(self):
        """Graceful shutdown."""
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()

    def _is_admin(self, update: "Update") -> bool:
        if not self.admin_ids:
            return True  # No restriction if no admin IDs configured
        return update.effective_user.id in self.admin_ids

    async def _send(self, chat_id: int, text: str, reply_markup=None, parse_mode=None):
        """Safe send with error logging."""
        if not self._bot:
            return
        try:
            await self._bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode or ParseMode.HTML,
            )
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")

    async def alert_all_admins(self, text: str, reply_markup=None):
        """Send a message to all admin chat IDs."""
        for cid in self.admin_ids:
            await self._send(cid, text, reply_markup=reply_markup)

    # =========================================================================
    # Signal Alerts
    # =========================================================================

    async def send_weather_signal(self, signal) -> None:
        """
        Send a weather signal alert with inline keyboard.
        Signal must have: market, edge, model_probability, market_probability,
        suggested_size, reasoning, ensemble_mean, ensemble_std, ensemble_members
        """
        if not self._bot or self._paused:
            return
        from backend.config import settings

        market = signal.market
        condition_id = market.market_id

        # Store pending signal for callback
        self._pending_signals[condition_id] = {
            "signal": signal,
            "stored_at": datetime.now(timezone.utc).isoformat(),
        }

        edge_pct = abs(signal.edge) * 100
        direction = signal.direction.upper()
        entry_price = market.yes_price if direction == "YES" else market.no_price

        text = (
            f"<b>WEATHER SIGNAL</b>\n"
            f"\n"
            f"<b>{market.city_name}</b> — {market.metric.title()} Temp\n"
            f"<i>{market.title[:60]}</i>\n"
            f"\n"
            f"Side:     <b>{direction}</b> @ {entry_price:.2f}\n"
            f"Model:    {signal.model_probability:.0%}  "
            f"(ensemble {signal.ensemble_mean:.1f}°F ±{signal.ensemble_std:.1f}°F, "
            f"{signal.ensemble_members}m)\n"
            f"Market:   {signal.market_probability:.0%}\n"
            f"<b>Edge:     +{edge_pct:.1f}%</b>\n"
            f"Size:     <b>${signal.suggested_size:.2f}</b>\n"
            f"\n"
            f"Expires: {market.target_date}"
        )

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ COPY TRADE", callback_data=f"copy:{condition_id}"
                    ),
                    InlineKeyboardButton(
                        "❌ SKIP", callback_data=f"skip:{condition_id}"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "📊 View Market",
                        url=f"{settings.POLYMARKET_BASE_URL}/event/{market.slug or condition_id}",
                    ),
                ],
            ]
        )

        await self.alert_all_admins(text, reply_markup=keyboard)

    async def send_copy_alert(
        self, signal, executed: bool = True, order_id: str = ""
    ) -> None:
        """
        Send a post-execution copy trade notification (no keyboard — already executed).
        """
        if not self._bot:
            return

        trade = signal.source_trade
        status = "✅ EXECUTED" if executed else "⚠️ FAILED"
        action = "EXIT" if signal.our_side == "SELL" else "COPY"

        text = (
            f"<b>{action} TRADE — {status}</b>\n"
            f"\n"
            f"Trader: <b>{signal.source_wallet[:10]}...</b> "
            f"(score {signal.trader_score:.0f})\n"
            f"Market: <i>{trade.title[:50]}</i>\n"
            f"\n"
            f"Side:   <b>{signal.our_side} {signal.our_outcome}</b>\n"
            f"Price:  {signal.market_price:.3f}\n"
            f"Size:   <b>${signal.our_size:.2f}</b>\n"
            + (f"Order:  <code>{order_id}</code>\n" if order_id else "")
            + f"\n<i>{signal.reasoning[:120]}</i>"
        )

        await self.alert_all_admins(text)

    async def send_error_alert(self, error: str, context: str = "") -> None:
        """Send an error alert to admins."""
        if not self._bot:
            return
        text = (
            f"<b>⚠️ POLYEDGE ERROR</b>\n"
            f"\n"
            f"{context + chr(10) if context else ''}"
            f"<code>{error[:300]}</code>"
        )
        await self.alert_all_admins(text)

    async def send_btc_signal(self, signal, trade=None) -> None:
        """Send BTC market signal alert."""
        if not self._bot or self._paused:
            return
        try:
            from backend.config import settings

            edge_pct = abs(getattr(signal, "edge", 0) or 0) * 100
            direction = getattr(signal, "direction", "N/A").upper()
            entry = (
                getattr(signal, "entry_price", None)
                or getattr(signal, "market_probability", None)
                or 0
            )
            size_str = (
                f"${trade.size:.2f}"
                if trade
                else f"${signal.suggested_size:.2f}"
                if hasattr(signal, "suggested_size")
                else "—"
            )
            mode_str = ", ".join(m.upper() for m in sorted(settings.active_modes_set))
            primary_mode = sorted(settings.active_modes_set)[0].upper() if settings.active_modes_set else "PAPER"
            mode_emoji = {"PAPER": "🟠", "TESTNET": "🟡", "LIVE": "🔴"}.get(primary_mode, "⚪")
            executed = "✅ TRADE PLACED" if trade else "📊 SIGNAL (no trade)"
            text = (
                f"<b>BTC SIGNAL {mode_emoji} {mode_str}</b>\n"
                f"\n"
                f"<b>{executed}</b>\n"
                f"Market: <i>{getattr(signal, 'market_ticker', 'N/A')}</i>\n"
                f"\n"
                f"Direction:  <b>{direction}</b>\n"
                f"Entry:      {entry:.3f}\n"
                f"Model prob: {getattr(signal, 'model_probability', 0):.1%}\n"
                f"Market:     {getattr(signal, 'market_probability', 0):.1%}\n"
                f"<b>Edge:       +{edge_pct:.1f}%</b>\n"
                f"Size:       <b>{size_str}</b>\n"
                + (
                    f"Order ID:   <code>{trade.clob_order_id}</code>\n"
                    if trade and getattr(trade, "clob_order_id", None)
                    else ""
                )
            )
            await self.alert_all_admins(text)
        except Exception as e:
            logger.error(f"send_btc_signal error: {e}")

    async def send_trade_opened(self, trade) -> None:
        """Notify when any trade is opened."""
        if not self._bot:
            return
        try:
            from backend.config import settings

            _mode_str = ", ".join(m.upper() for m in sorted(settings.active_modes_set))
            primary_mode = sorted(settings.active_modes_set)[0].upper() if settings.active_modes_set else "PAPER"
            mode_emoji = {"PAPER": "🟠", "TESTNET": "🟡", "LIVE": "🔴"}.get(primary_mode, "⚪")
            text = (
                f"<b>📈 TRADE OPENED {mode_emoji}</b>\n"
                f"\n"
                f"Market:     <i>{trade.market_ticker}</i>\n"
                f"Direction:  <b>{trade.direction.upper()}</b>\n"
                f"Entry:      {trade.entry_price:.3f}\n"
                f"Size:       <b>${trade.size:.2f}</b>\n"
                f"Strategy:   {trade.strategy or 'manual'}\n"
                + (
                    f"Order:      <code>{trade.clob_order_id}</code>\n"
                    if getattr(trade, "clob_order_id", None)
                    else ""
                )
            )
            await self.alert_all_admins(text)
        except Exception as e:
            logger.error(f"send_trade_opened error: {e}")

    async def send_trade_settled(self, trade) -> None:
        """Notify when a trade settles."""
        if not self._bot:
            return
        try:
            result = getattr(trade, "result", None) or "unknown"
            pnl = getattr(trade, "pnl", None)
            if result == "win":
                emoji = "✅ WIN"
            elif result == "loss":
                emoji = "❌ LOSS"
            else:
                emoji = "⏳ SETTLED"
            pnl_str = (
                f"+${pnl:.2f}"
                if pnl and pnl > 0
                else f"-${abs(pnl):.2f}"
                if pnl
                else "—"
            )
            text = (
                f"<b>{emoji}</b>\n"
                f"\n"
                f"Market:  <i>{trade.market_ticker}</i>\n"
                f"Side:    {trade.direction.upper()} @ {trade.entry_price:.3f}\n"
                f"Size:    ${trade.size:.2f}\n"
                f"<b>PnL:     {pnl_str}</b>\n"
            )
            await self.alert_all_admins(text)
        except Exception as e:
            logger.error(f"send_trade_settled error: {e}")

    async def send_scan_summary(self, total: int, actionable: int, placed: int) -> None:
        """Send scan summary when actionable signals are found."""
        if not self._bot:
            return
        try:
            text = (
                f"<b>🔍 SCAN COMPLETE</b>\n"
                f"\n"
                f"Markets scanned: {total}\n"
                f"Actionable:      <b>{actionable}</b>\n"
                f"Trades placed:   <b>{placed}</b>"
            )
            await self.alert_all_admins(text)
        except Exception as e:
            logger.error(f"send_scan_summary error: {e}")

    async def send_high_confidence_signal(
        self,
        strategy: str,
        market_title: str,
        direction: str,
        confidence: float,
        edge: float,
        reasoning: str,
        market_url: str = "",
    ) -> None:
        """Alert admins about high-confidence trading opportunities."""
        if not self._bot or self._paused:
            return
        try:
            confidence_bar = "🟢" * int(confidence * 5) + "⚪" * (
                5 - int(confidence * 5)
            )
            edge_pct = edge * 100
            text = (
                f"<b>🎯 HIGH CONFIDENCE SIGNAL</b>\n"
                f"\n"
                f"Strategy:   <b>{strategy}</b>\n"
                f"Market:     <i>{market_title[:80]}</i>\n"
                f"\n"
                f"Direction:  <b>{direction.upper()}</b>\n"
                f"Confidence: {confidence_bar} {confidence:.0%}\n"
                f"Edge:       <b>+{edge_pct:.1f}%</b>\n"
                f"\n"
                f"<i>{reasoning[:200]}</i>"
            )
            if market_url:
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup

                keyboard = InlineKeyboardMarkup(
                    [[InlineKeyboardButton("📊 View Market", url=market_url)]]
                )
                await self.alert_all_admins(text, reply_markup=keyboard)
            else:
                await self.alert_all_admins(text)
        except Exception as e:
            logger.error(f"send_high_confidence_signal error: {e}")

    # =========================================================================
    # Callback handler (inline keyboard buttons)
    # =========================================================================

    async def _handle_callback(
        self, update: "Update", context: "ContextTypes.DEFAULT_TYPE"
    ):
        query = update.callback_query
        await query.answer()

        if not self._is_admin(update):
            await query.edit_message_text("❌ Not authorized.")
            return

        data = query.data
        if data.startswith("copy:"):
            condition_id = data[5:]
            pending = self._pending_signals.pop(condition_id, None)
            if not pending:
                await query.edit_message_text("⚠️ Signal expired or already acted on.")
                return

            signal = pending["signal"]
            if self.on_copy_trade:
                try:
                    result = await self.on_copy_trade(signal)
                    order_id = getattr(result, "order_id", "")
                    await query.edit_message_text(
                        f"✅ Trade executed!\n"
                        f"Size: ${signal.suggested_size:.2f} | "
                        f"Order: {order_id or 'paper'}"
                    )
                except Exception as e:
                    await query.edit_message_text(f"❌ Execution failed: {e}")
            else:
                await query.edit_message_text(
                    "✅ Signal acknowledged (no executor configured)."
                )

        elif data.startswith("skip:"):
            condition_id = data[5:]
            self._pending_signals.pop(condition_id, None)
            await query.edit_message_text("❌ Signal skipped.")

    # =========================================================================
    # Command handlers
    # =========================================================================

    async def _cmd_start(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
        status = "🟢 RUNNING" if not self._paused else "⏸ PAUSED"
        await update.message.reply_text(
            f"<b>PolyEdge Bot</b> {status}\n\n"
            f"Commands:\n"
            f"/status — system status\n"
            f"/positions — open positions\n"
            f"/trades [n] — recent trades with PnL\n"
            f"/bankroll — bankroll and equity\n"
            f"/pnl — P&L breakdown\n"
            f"/leaderboard — tracked traders\n"
            f"/scan — trigger BTC scan now (admin)\n"
            f"/settle — run settlement check (admin)\n"
            f"/pause — pause scanning (admin)\n"
            f"/resume — resume scanning (admin)\n"
            f"/settings — current config\n"
            f"/calibration — weather calibration report\n"
            f"/mode paper|testnet|live — switch mode (admin)",
            parse_mode=ParseMode.HTML,
        )

    async def _cmd_status(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
        from backend.config import settings
        from backend.models.database import SessionLocal, BotState, for_update

        mode_emoji = {"paper": "🟠 PAPER", "testnet": "🟡 TESTNET", "live": "🔴 LIVE"}
        mode_str = ", ".join(mode_emoji.get(m, "🟠 PAPER") for m in sorted(settings.active_modes_set))
        paused = "⏸ PAUSED" if self._paused else "🟢 RUNNING"

        bankroll = settings.INITIAL_BANKROLL
        try:
            with SessionLocal() as db:
                state = for_update(db, db.query(BotState)).first()
                if state:
                    if settings.is_mode_active("paper"):
                        bankroll = (
                            state.paper_bankroll
                            if state.paper_bankroll is not None
                            else settings.INITIAL_BANKROLL
                        )
                    elif settings.is_mode_active("testnet"):
                        bankroll = (
                            state.testnet_bankroll
                            if state.testnet_bankroll is not None
                            else settings.INITIAL_BANKROLL
                        )
                    else:
                        bankroll = (
                            state.bankroll
                            if state.bankroll is not None
                            else settings.INITIAL_BANKROLL
                        )
        except Exception:
            logger.exception("Failed to retrieve bot status for Telegram command")
            pass

        await update.message.reply_text(
            f"<b>PolyEdge Status</b>\n\n"
            f"Mode:     {mode_str}\n"
            f"Scanner:  {paused}\n"
            f"Bankroll: ${bankroll:,.2f}\n"
            f"Cities:   {settings.WEATHER_CITIES}\n"
            f"Edge min: {settings.WEATHER_MIN_EDGE_THRESHOLD:.0%}",
            parse_mode=ParseMode.HTML,
        )

    async def _cmd_positions(
        self, update: "Update", context: "ContextTypes.DEFAULT_TYPE"
    ):
        try:
            from backend.models.database import SessionLocal, Trade

            with SessionLocal() as db:
                from backend.config import settings as _s

                pending = (
                    db.query(Trade)
                    .filter(Trade.settled.is_(False))
                    .filter(Trade.trading_mode.in_(_s.active_modes_set))
                    .order_by(Trade.timestamp.desc())
                    .all()
                )

            if not pending:
                await update.message.reply_text(
                    "📊 <b>Open Positions</b>\n\nNo open positions.",
                    parse_mode=ParseMode.HTML,
                )
                return

            lines = ["📊 <b>Open Positions</b>\n"]
            total_size = 0.0
            for t in pending[:15]:
                mode_tag = (
                    f"[{(getattr(t, 'trading_mode', None) or 'paper').upper()[:1]}]"
                )
                lines.append(
                    f"{mode_tag} <b>{t.direction.upper()}</b> {getattr(t, 'event_slug', None) or t.market_ticker} "
                    f"${t.size:.0f} @ {t.entry_price:.0%} "
                    f"<i>{t.market_ticker[:20]}</i>"
                )
                total_size += t.size

            if len(pending) > 15:
                lines.append(f"\n... and {len(pending) - 15} more")

            lines.append(
                f"\n<b>Total exposure: ${total_size:.0f}</b> across {len(pending)} positions"
            )
            await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
        except Exception as e:
            await update.message.reply_text(f"Error loading positions: {e}")

    async def _cmd_leaderboard(
        self, update: "Update", context: "ContextTypes.DEFAULT_TYPE"
    ):
        await update.message.reply_text(
            "🏆 <b>Leaderboard</b>\n\n"
            "Copy trader leaderboard data loads on next poll cycle.\n"
            "Use /status to check scanner state.",
            parse_mode=ParseMode.HTML,
        )

    async def _cmd_pause(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
        if not self._is_admin(update):
            await update.message.reply_text("❌ Admin only.")
            return
        self._paused = True
        if self.on_pause:
            await self.on_pause()
        await update.message.reply_text("⏸ Scanning paused. Use /resume to restart.")

    async def _cmd_resume(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
        if not self._is_admin(update):
            await update.message.reply_text("❌ Admin only.")
            return
        self._paused = False
        if self.on_resume:
            await self.on_resume()
        await update.message.reply_text("🟢 Scanning resumed.")

    async def _cmd_settings(
        self, update: "Update", context: "ContextTypes.DEFAULT_TYPE"
    ):
        from backend.config import settings

        await update.message.reply_text(
            f"<b>PolyEdge Settings</b>\n\n"
            f"Active modes:      {', '.join(sorted(settings.active_modes_set))}\n"
            f"Kelly fraction:    {settings.KELLY_FRACTION}\n"
            f"Max trade size:    ${settings.WEATHER_MAX_TRADE_SIZE}\n"
            f"Edge threshold:    {settings.WEATHER_MIN_EDGE_THRESHOLD:.0%}\n"
            f"Max entry price:   {settings.WEATHER_MAX_ENTRY_PRICE:.0%}\n"
            f"Scan interval:     {settings.WEATHER_SCAN_INTERVAL_SECONDS}s",
            parse_mode=ParseMode.HTML,
        )

    async def _cmd_mode(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
        if not self._is_admin(update):
            await update.message.reply_text("❌ Admin only.")
            return
        args = context.args
        if not args or args[0] not in ("paper", "testnet", "live"):
            from backend.config import settings

            current = settings.TRADING_MODE
            await update.message.reply_text(
                f"Current mode: <b>{current.upper()}</b>\n\nUsage: /mode paper|testnet|live",
                parse_mode=ParseMode.HTML,
            )
            return
        new_mode = args[0]
        if self.on_mode_switch:
            await self.on_mode_switch(new_mode)

        mode_emoji = {"paper": "🟠", "testnet": "🟡", "live": "🔴"}
        await update.message.reply_text(
            f"{mode_emoji.get(new_mode, '⚪')} Mode switched to <b>{new_mode.upper()}</b>.\n"
            f"New trades will execute in {new_mode} mode.",
            parse_mode=ParseMode.HTML,
        )

    async def _cmd_calibration(
        self, update: "Update", context: "ContextTypes.DEFAULT_TYPE"
    ):
        try:
            from backend.core.calibration import get_calibration_report

            report = get_calibration_report()
            await update.message.reply_text(
                f"<pre>{report}</pre>", parse_mode=ParseMode.HTML
            )
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

    async def _cmd_scan(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
        """Trigger an immediate multi-strategy market scan."""
        if not self._is_admin(update):
            await update.message.reply_text("❌ Admin only.")
            return
        await update.message.reply_text("🔍 Running multi-strategy market scan...")
        try:
            from backend.core.scheduler import scan_and_trade_job

            await scan_and_trade_job("paper")
            await update.message.reply_text(
                "✅ Scan complete. Check /positions for results."
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Scan error: {e}")

    async def _cmd_trades(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
        """Show recent trades with PnL."""
        try:
            n = 10
            if context.args:
                try:
                    n = int(context.args[0])
                except ValueError:
                    pass
            from backend.models.database import SessionLocal, Trade

            with SessionLocal() as db:
                from backend.config import settings as _s

                trades = (
                    db.query(Trade)
                    .filter(Trade.trading_mode.in_(_s.active_modes_set))
                    .order_by(Trade.timestamp.desc())
                    .limit(n)
                    .all()
                )
            if not trades:
                await update.message.reply_text(
                    "📊 <b>Recent Trades</b>\n\nNo trades found.",
                    parse_mode=ParseMode.HTML,
                )
                return
            lines = [f"📊 <b>Recent Trades (last {len(trades)})</b>\n"]
            total_pnl = 0.0
            for t in trades:
                pnl = t.pnl or 0.0
                total_pnl += pnl
                status = {"win": "✅", "loss": "❌", None: "⏳"}.get(t.result, "⏳")
                pnl_str = f" {'+' if pnl >= 0 else ''}{pnl:.2f}" if t.result else ""
                lines.append(
                    f"{status} <b>{t.direction.upper()}</b> {t.market_type or 'btc'} "
                    f"${t.size:.0f} @ {t.entry_price:.2%}"
                    f"{pnl_str}"
                )
            lines.append(
                f"\n<b>Total PnL: {'+' if total_pnl >= 0 else ''}{total_pnl:.2f}</b>"
            )
            await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

    async def _cmd_bankroll(
        self, update: "Update", context: "ContextTypes.DEFAULT_TYPE"
    ):
        """Show current bankroll and equity."""
        try:
            from backend.models.database import SessionLocal, Trade
            from backend.config import settings

            with SessionLocal() as db:
                from backend.config import settings as _s

                pending = (
                    db.query(Trade)
                    .filter(Trade.settled.is_(False))
                    .filter(Trade.trading_mode.in_(_s.active_modes_set))
                    .all()
                )
                settled = (
                    db.query(Trade)
                    .filter(Trade.settled.is_(True))
                    .filter(Trade.trading_mode.in_(_s.active_modes_set))
                    .all()
                )
            total_pnl = sum(t.pnl or 0.0 for t in settled)
            exposure = sum(t.size for t in pending)
            equity = settings.INITIAL_BANKROLL + total_pnl
            _mode_str = ", ".join(m.upper() for m in sorted(settings.active_modes_set))
            primary_mode = sorted(settings.active_modes_set)[0].upper() if settings.active_modes_set else "PAPER"
            mode_emoji = {"PAPER": "🟠", "TESTNET": "🟡", "LIVE": "🔴"}.get(primary_mode, "⚪")
            await update.message.reply_text(
                f"<b>💰 Bankroll {mode_emoji}</b>\n"
                f"\n"
                f"Starting:   ${settings.INITIAL_BANKROLL:,.2f}\n"
                f"Total PnL:  {'+' if total_pnl >= 0 else ''}{total_pnl:,.2f}\n"
                f"<b>Equity:     ${equity:,.2f}</b>\n"
                f"\n"
                f"Open pos:   {len(pending)}\n"
                f"Exposure:   ${exposure:,.2f}\n"
                f"Settled:    {len(settled)} trades",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

    async def _cmd_settle(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
        """Trigger manual settlement check."""
        if not self._is_admin(update):
            await update.message.reply_text("❌ Admin only.")
            return
        await update.message.reply_text("⚙️ Running settlement check...")
        try:
            from backend.core.scheduler import settlement_job

            await settlement_job()
            await update.message.reply_text("✅ Settlement check complete.")
        except Exception as e:
            await update.message.reply_text(f"❌ Settlement error: {e}")

    async def _cmd_pnl(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
        """Show P&L breakdown."""
        try:
            from backend.models.database import SessionLocal, Trade

            with SessionLocal() as db:
                from backend.config import settings as _s

                all_trades = (
                    db.query(Trade)
                    .filter(Trade.settled.is_(True))
                    .filter(Trade.trading_mode.in_(_s.active_modes_set))
                    .all()
                )
            if not all_trades:
                await update.message.reply_text("📊 No settled trades yet.")
                return
            wins = [t for t in all_trades if t.result == "win"]
            losses = [t for t in all_trades if t.result == "loss"]
            total_pnl = sum(t.pnl or 0.0 for t in all_trades)
            win_pnl = sum(t.pnl or 0.0 for t in wins)
            loss_pnl = sum(t.pnl or 0.0 for t in losses)
            win_rate = len(wins) / len(all_trades) * 100 if all_trades else 0
            avg_win = win_pnl / len(wins) if wins else 0
            avg_loss = loss_pnl / len(losses) if losses else 0
            await update.message.reply_text(
                f"<b>📊 P&L Report</b>\n"
                f"\n"
                f"Trades:    {len(all_trades)} settled\n"
                f"Win rate:  {win_rate:.0f}% ({len(wins)}W / {len(losses)}L)\n"
                f"\n"
                f"Wins:      +${win_pnl:.2f} (avg +${avg_win:.2f})\n"
                f"Losses:     ${loss_pnl:.2f} (avg ${avg_loss:.2f})\n"
                f"<b>Net P&L:   {'+' if total_pnl >= 0 else ''}{total_pnl:.2f}</b>",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")


def bot_from_settings() -> "PolyEdgeBot":
    """Create PolyEdgeBot from app settings."""
    from backend.config import settings

    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "") or ""
    raw_ids = getattr(settings, "TELEGRAM_ADMIN_CHAT_IDS", "") or ""
    admin_ids = []
    for part in str(raw_ids).split(","):
        part = part.strip()
        if part.isdigit():
            admin_ids.append(int(part))

    return PolyEdgeBot(token=token, admin_ids=admin_ids)
