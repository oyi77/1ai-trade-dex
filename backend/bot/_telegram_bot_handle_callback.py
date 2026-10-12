"""Methods carved verbatim out of ``backend/bot/telegram_bot.py``."""

from . import telegram_bot as _facade
from .tracker_client import tracker_get
from .wallet_watchlist import add_wallet, remove_wallet, list_wallets

try:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.constants import ParseMode
except ImportError:
    InlineKeyboardButton = None  # type: ignore[assignment]
    InlineKeyboardMarkup = None  # type: ignore[assignment]
    ParseMode = None  # type: ignore[assignment]

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
        # --- menu / watchlist callback dispatch ---
        elif data.startswith("menu:"):
            action = data[5:]
            if action == "wallets":
                await self._cmd_wallets(update, context)
            elif action == "sniper":
                await self._cmd_sniper(update, context)
            elif action == "whaleflow":
                await self._cmd_whaleflow(update, context)
            else:
                await query.edit_message_text("Unknown menu action.")
        elif data.startswith("rmwallet:"):
            addr = data[9:]
            result = remove_wallet(addr)
            await query.edit_message_text(result["msg"], parse_mode=ParseMode.HTML)
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
            f"/wallets — smart money wallet list\n"
            f"/sniper — sniper scan history\n"
            f"/wallet &lt;addr&gt; — wallet profiler\n"
            f"/whaleflow — whale flow board\n"
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

    async def _cmd_wallets(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
        """List tracked smart-money wallets from tracker API."""
        data = await tracker_get("/api/v1/smart-money", {"pageSize": "15", "sort": "score", "order": "desc"})
        if data is None:
            await update.message.reply_text("⚠️ Tracker API unreachable.", parse_mode=ParseMode.HTML)
            return
        wallets = data.get("data") or []
        if not wallets:
            await update.message.reply_text("📊 <b>Smart Money Wallets</b>\n\nNo wallets found.", parse_mode=ParseMode.HTML)
            return
        lines = [f"📊 <b>Smart Money Wallets ({len(wallets)})</b>\n"]
        for w in wallets[:15]:
            addr = (w.get("wallet") or {}).get("address", "?")
            addr_short = f"{addr[:6]}…{addr[-4:]}" if len(addr) > 12 else addr
            cat = w.get("category") or "—"
            score = w.get("score")
            score_str = f" score={score:.1f}" if isinstance(score, (int, float)) else ""
            pnl = w.get("pnl30d")
            pnl_str = f" pnl30d={'+' if (pnl or 0) >= 0 else ''}{pnl:.1f}" if isinstance(pnl, (int, float)) else ""
            wr = w.get("winRate")
            wr_str = f" wr={wr:.0%}" if isinstance(wr, (int, float)) else ""
            status = w.get("status") or ""
            lines.append(f"• <b>{addr_short}</b> {cat}{score_str}{pnl_str}{wr_str} {status}")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    async def _cmd_sniper(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
        """Show recent sniper scan results from tracker."""
        data = await tracker_get("/api/v1/meme/sniper/history")
        if data is None:
            await update.message.reply_text("⚠️ Tracker API unreachable.", parse_mode=ParseMode.HTML)
            return
        payload = data.get("data") or {}
        entries = payload.get("entries") or []
        counts = payload.get("counts") or {}
        if not entries:
            await update.message.reply_text("🎯 <b>Sniper Scan History</b>\n\nNo scans found.", parse_mode=ParseMode.HTML)
            return
        summary = " ".join(f"{k}={v}" for k, v in counts.items())
        lines = [f"🎯 <b>Sniper Scan History</b> ({summary})\n"]
        for e in entries[:15]:
            status = e.get("status") or "?"
            metrics = e.get("metrics") or {}
            age = metrics.get("ageMinutes")
            age_str = f" {age:.0f}m" if isinstance(age, (int, float)) else ""
            vol = metrics.get("volMcRatio")
            vol_str = f" vol/mcap={vol:.1f}x" if isinstance(vol, (int, float)) else ""
            snip = metrics.get("sniperPercent")
            snip_str = f" snip={snip:.0%}" if isinstance(snip, (int, float)) else ""
            top10 = metrics.get("top10Percent")
            top10_str = f" top10={top10:.0%}" if isinstance(top10, (int, float)) else ""
            contract = (e.get("contract") or "")[:10]
            lines.append(f"• <b>{status}</b> {contract}…{age_str}{vol_str}{snip_str}{top10_str}")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    async def _cmd_wallet(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
        """Profile a single wallet from tracker."""
        if not context.args:
            await update.message.reply_text("Usage: /wallet &lt;address&gt;", parse_mode=ParseMode.HTML)
            return
        addr = context.args[0]
        data = await tracker_get("/api/v1/smart-money/wallet", {"address": addr, "chain": "eth"})
        if data is None:
            await update.message.reply_text("⚠️ Tracker API unreachable.", parse_mode=ParseMode.HTML)
            return
        d = data.get("data") or {}
        entity = d.get("entity") or {}
        label = entity.get("label") or "Unknown"
        cat = entity.get("category") or "—"
        conf = entity.get("confidence")
        conf_str = f" ({conf:.0%})" if isinstance(conf, (int, float)) else ""
        tx_count = d.get("txCount", 0)
        transfer_count = d.get("tokenTransferCount", 0)
        lines = [
            f"🔍 <b>Wallet Profile</b>\n",
            f"Address: <code>{addr}</code>",
            f"Entity: {label} [{cat}]{conf_str}",
            f"TXs: {tx_count}  Transfers: {transfer_count}",
        ]
        recent = (d.get("recentTxs") or [])[:5]
        if recent:
            lines.append("\n<b>Recent TXs:</b>")
            for tx in recent:
                ts = tx.get("timestamp", "")[:19]
                val = tx.get("value", "")
                lines.append(f"  {ts} {val}")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    async def _cmd_whaleflow(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
        """Show smart money flow board from tracker."""
        data = await tracker_get("/api/v1/smart-money/flow")
        if data is None:
            await update.message.reply_text("⚠️ Tracker API unreachable.", parse_mode=ParseMode.HTML)
            return
        flows = data.get("flows") or []
        total = data.get("totalEntities", 0)
        if not flows:
            await update.message.reply_text("🐋 <b>Whale Flow</b>\n\nNo flow data found.", parse_mode=ParseMode.HTML)
            return
        lines = [f"🐋 <b>Whale Flow Board</b> ({total} entities)\n"]
        for f in flows[:15]:
            label = f.get("label") or f.get("category") or "—"
            icon = f.get("icon") or "•"
            count = f.get("entityCount", 0)
            chains = ", ".join(f.get("chains") or [])
            lines.append(f"{icon} <b>{label}</b> — {count} entities {chains}")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
    # =========================================================================
    # Inline menu + watchlist commands
    # =========================================================================

    async def _reply_safe(self, update, text, reply_markup=None, parse_mode=ParseMode.HTML):
        """Reply via message or callback_query depending on context."""
        if update.callback_query and update.callback_query.message:
            await update.callback_query.message.reply_text(
                text, reply_markup=reply_markup, parse_mode=parse_mode
            )
        else:
            await update.message.reply_text(
                text, reply_markup=reply_markup, parse_mode=parse_mode
            )

    async def _cmd_menu(self, update, context):
        """Show inline keyboard menu."""
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("📊 Wallets", callback_data="menu:wallets")],
                [InlineKeyboardButton("🎯 Sniper", callback_data="menu:sniper")],
                [InlineKeyboardButton("🐋 Whale Flow", callback_data="menu:whaleflow")],
                [InlineKeyboardButton("➕ Add Wallet", callback_data="menu:addwallet")],
                [InlineKeyboardButton("📋 My Watchlist", callback_data="menu:mywallets")],
            ]
        )
        await update.message.reply_text(
            "<b>PolyEdge Menu</b>\n\nTap a button below:",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
        )

    async def _cmd_addwallet(self, update, context):
        """Add a wallet to the watchlist.
        Usage: /addwallet 0xABC123... [chain] [label...]
        """
        if not context.args:
            await update.message.reply_text(
                "Usage: <code>/addwallet &lt;address&gt; [chain] [label]</code>\n"
                "Example: <code>/addwallet 0xABC123... eth whale-1</code>",
                parse_mode=ParseMode.HTML,
            )
            return
        addr = context.args[0]
        chain = context.args[1] if len(context.args) > 1 else "eth"
        label = " ".join(context.args[2:]) if len(context.args) > 2 else ""
        result = add_wallet(addr, chain, label)
        emoji = "✅" if result["ok"] else "⚠️"
        await update.message.reply_text(
            f"{emoji} {result['msg']}", parse_mode=ParseMode.HTML
        )

    async def _cmd_mywallets(self, update, context):
        """List watched wallets with inline remove buttons."""
        wallets = list_wallets()
        if not wallets:
            await update.message.reply_text(
                "📋 <b>Watchlist</b>\n\nNo wallets tracked. Use /addwallet to add one.",
                parse_mode=ParseMode.HTML,
            )
            return
        lines = [f"📋 <b>Watchlist ({len(wallets)})</b>\n"]
        buttons = []
        for i, w in enumerate(wallets):
            addr = w.get("address", "?")
            chain = w.get("chain", "eth")
            label = w.get("label", "")
            label_str = f" — {label}" if label else ""
            addr_short = f"{addr[:14]}…{addr[-4:]}" if len(addr) > 20 else addr
            lines.append(f"{i+1}. <code>{addr_short}</code> [{chain}]{label_str}")
            buttons.append(
                [InlineKeyboardButton(f"🗑 Remove {addr[:10]}…", callback_data=f"rmwallet:{addr}")]
            )
        keyboard = InlineKeyboardMarkup(buttons)
        await update.message.reply_text(
            "\n".join(lines), reply_markup=keyboard, parse_mode=ParseMode.HTML
        )
