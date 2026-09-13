"""Methods carved verbatim out of ``backend/bot/telegram_bot.py``."""

from .telegram_bot import (
    Callable,
    Optional,
)

from . import telegram_bot as _facade

class PolyEdgeBotMixin:
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

        self._app: _facade.Optional["Application"] = None
        self._bot: _facade.Optional["Bot"] = None
        self._paused = False

        # Pending weather signals awaiting user confirmation
        # key: signal_id (condition_id), value: signal data dict
        self._pending_signals: dict[str, dict] = {}
    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def start(self):
        """Initialize and start the bot (non-blocking — runs in background task)."""
        if not _facade.TELEGRAM_AVAILABLE:
            _facade.logger.warning("Telegram bot disabled — python-telegram-bot not installed")
            return

        if not self.token or self.token == "disabled":
            _facade.logger.info("Telegram bot token not configured — alerts disabled")
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

        if hasattr(app.state, "task_manager"):
            await app.state.task_manager.create_task(
                self._app.updater.start_polling(drop_pending_updates=True),
                name="telegram_bot_polling",
            )
        else:
            _facade.asyncio.create_task(
                self._app.updater.start_polling(drop_pending_updates=True)
            )
        _facade.logger.info(f"Telegram bot started — admins: {self.admin_ids}")
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
            _facade.logger.error(f"Telegram send failed: {e}")
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

        market = signal.market
        condition_id = market.market_id

        # Store pending signal for callback
        self._pending_signals[condition_id] = {
            "signal": signal,
            "stored_at": _facade.datetime.now(_facade.timezone.utc).isoformat(),
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
                        url=f"{_facade.settings.POLYMARKET_BASE_URL}/event/{market.slug or condition_id}",
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
                else (
                    f"${signal.suggested_size:.2f}"
                    if hasattr(signal, "suggested_size")
                    else "—"
                )
            )
            mode_str = ", ".join(m.upper() for m in sorted(_facade.settings.active_modes_set))
            primary_mode = (
                sorted(_facade.settings.active_modes_set)[0].upper()
                if _facade.settings.active_modes_set
                else "PAPER"
            )
            mode_emoji = {"PAPER": "🟠", "TESTNET": "🟡", "LIVE": "🔴"}.get(
                primary_mode, "⚪"
            )
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
            _facade.logger.error(f"send_btc_signal error: {e}")
    async def send_trade_opened(self, trade) -> None:
        """Notify when any trade is opened."""
        if not self._bot:
            return
        try:

            _mode_str = ", ".join(m.upper() for m in sorted(_facade.settings.active_modes_set))
            primary_mode = (
                sorted(_facade.settings.active_modes_set)[0].upper()
                if _facade.settings.active_modes_set
                else "PAPER"
            )
            mode_emoji = {"PAPER": "🟠", "TESTNET": "🟡", "LIVE": "🔴"}.get(
                primary_mode, "⚪"
            )
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
            _facade.logger.error(f"send_trade_opened error: {e}")
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
                else f"-${abs(pnl):.2f}" if pnl else "—"
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
            _facade.logger.error(f"send_trade_settled error: {e}")
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
            _facade.logger.error(f"send_scan_summary error: {e}")
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
            _facade.logger.error(f"send_high_confidence_signal error: {e}")
