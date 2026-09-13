"""Methods carved verbatim out of ``backend/bot/telegram_bot.py``."""

from . import telegram_bot as _facade

class PolyEdgeBotMixin2:
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
        from backend.models.database import SessionLocal, BotState, for_update

        mode_emoji = {"paper": "🟠 PAPER", "testnet": "🟡 TESTNET", "live": "🔴 LIVE"}
        mode_str = ", ".join(
            mode_emoji.get(m, "🟠 PAPER") for m in sorted(_facade.settings.active_modes_set)
        )
        paused = "⏸ PAUSED" if self._paused else "🟢 RUNNING"

        bankroll = _facade.settings.INITIAL_BANKROLL
        try:
            with SessionLocal() as db:
                state = for_update(db, db.query(BotState)).first()
                if state:
                    if _facade.settings.is_mode_active("paper"):
                        bankroll = (
                            state.paper_bankroll
                            if state.paper_bankroll is not None
                            else _facade.settings.INITIAL_BANKROLL
                        )
                    elif _facade.settings.is_mode_active("testnet"):
                        bankroll = (
                            state.testnet_bankroll
                            if state.testnet_bankroll is not None
                            else _facade.settings.INITIAL_BANKROLL
                        )
                    else:
                        bankroll = (
                            state.bankroll
                            if state.bankroll is not None
                            else _facade.settings.INITIAL_BANKROLL
                        )
        except Exception:
            _facade.logger.exception("Failed to retrieve bot status for Telegram command")

        await update.message.reply_text(
            f"<b>PolyEdge Status</b>\n\n"
            f"Mode:     {mode_str}\n"
            f"Scanner:  {paused}\n"
            f"Bankroll: ${bankroll:,.2f}\n"
            f"Cities:   {_facade.settings.WEATHER_CITIES}\n"
            f"Edge min: {_facade.settings.WEATHER_MIN_EDGE_THRESHOLD:.0%}",
            parse_mode=ParseMode.HTML,
        )
    async def _cmd_positions(
        self, update: "Update", context: "ContextTypes.DEFAULT_TYPE"
    ):
        try:
            from backend.models.database import SessionLocal, Trade

            with SessionLocal() as db:

                pending = (
                    db.query(Trade)
                    .filter(Trade.settled.is_(False))
                    .filter(Trade.trading_mode.in_(_facade.settings.active_modes_set))
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

        await update.message.reply_text(
            f"<b>PolyEdge Settings</b>\n\n"
            f"Active modes:      {', '.join(sorted(_facade.settings.active_modes_set))}\n"
            f"Kelly fraction:    {_facade.settings.KELLY_FRACTION}\n"
            f"Max trade size:    ${_facade.settings.WEATHER_MAX_TRADE_SIZE}\n"
            f"Edge threshold:    {_facade.settings.WEATHER_MIN_EDGE_THRESHOLD:.0%}\n"
            f"Max entry price:   {_facade.settings.WEATHER_MAX_ENTRY_PRICE:.0%}\n"
            f"Scan interval:     {_facade.settings.WEATHER_SCAN_INTERVAL_SECONDS}s",
            parse_mode=ParseMode.HTML,
        )
    async def _cmd_mode(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
        if not self._is_admin(update):
            await update.message.reply_text("❌ Admin only.")
            return
        args = context.args
        if not args or args[0] not in ("paper", "testnet", "live"):

            current = _facade.settings.TRADING_MODE
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
            from backend.core.learning.calibration import get_calibration_report

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
            from backend.core.scheduling.scheduler import scan_and_trade_job

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

                trades = (
                    db.query(Trade)
                    .filter(Trade.trading_mode.in_(_facade.settings.active_modes_set))
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

            with SessionLocal() as db:

                pending = (
                    db.query(Trade)
                    .filter(Trade.settled.is_(False))
                    .filter(Trade.trading_mode.in_(_facade.settings.active_modes_set))
                    .all()
                )
                settled = (
                    db.query(Trade)
                    .filter(Trade.settled.is_(True))
                    .filter(Trade.trading_mode.in_(_facade.settings.active_modes_set))
                    .all()
                )
            total_pnl = sum(t.pnl or 0.0 for t in settled)
            exposure = sum(t.size for t in pending)
            equity = _facade.settings.INITIAL_BANKROLL + total_pnl
            _mode_str = ", ".join(m.upper() for m in sorted(_facade.settings.active_modes_set))
            primary_mode = (
                sorted(_facade.settings.active_modes_set)[0].upper()
                if _facade.settings.active_modes_set
                else "PAPER"
            )
            mode_emoji = {"PAPER": "🟠", "TESTNET": "🟡", "LIVE": "🔴"}.get(
                primary_mode, "⚪"
            )
            await update.message.reply_text(
                f"<b>💰 Bankroll {mode_emoji}</b>\n"
                f"\n"
                f"Starting:   ${_facade.settings.INITIAL_BANKROLL:,.2f}\n"
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
            from backend.core.scheduling.scheduler import settlement_job

            await settlement_job()
            await update.message.reply_text("✅ Settlement check complete.")
        except Exception as e:
            await update.message.reply_text(f"❌ Settlement error: {e}")
    async def _cmd_pnl(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
        """Show P&L breakdown."""
        try:
            from backend.models.database import SessionLocal, Trade

            with SessionLocal() as db:

                all_trades = (
                    db.query(Trade)
                    .filter(Trade.settled.is_(True))
                    .filter(Trade.trading_mode.in_(_facade.settings.active_modes_set))
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
