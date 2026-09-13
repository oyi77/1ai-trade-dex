"""Methods carved verbatim out of ``backend/core/orchestrator.py``."""

from . import orchestrator as _facade

class OrchestratorMixin2:
    async def _register_activity_sources(self):
        """Register platform activity sources with ActivityTracker."""
        from backend.config import settings

        addr = settings.WALLET_ADDRESS or settings.POLYMARKET_WALLET_ADDRESS or "0x0"
        tracker = self._activity_tracker
        skip_raw = _facade.os.environ.get("SKIP_ACTIVITY_SOURCES", "").strip().lower()
        skip_sources = (
            set(s.strip() for s in skip_raw.split(",") if s.strip())
            if skip_raw
            else set()
        )

        # Aster — WebSocket fills + balance + positions
        try:
            if "aster" in skip_sources:
                raise RuntimeError("SKIP_ACTIVITY_SOURCES")
            from backend.markets.providers.aster_provider import AsterProvider
            from backend.core.activity.sources.aster_source import AsterActivitySource

            aster = AsterProvider()
            await aster.connect()
            tracker.register_source("aster", AsterActivitySource(addr, aster))
        except Exception as e:
            _facade.logger.warning(f"Aster activity source skipped: {e}")

        # Hyperliquid — WebSocket user_fills
        try:
            from backend.markets.providers.hyperliquid_provider import (
                HyperliquidProvider,
            )
            from backend.core.activity.sources.hyperliquid_source import (
                HyperliquidActivitySource,
            )

            hl = HyperliquidProvider()
            await hl.connect()
            tracker.register_source("hyperliquid", HyperliquidActivitySource(addr, hl))
        except Exception as e:
            _facade.logger.warning(f"Hyperliquid activity source skipped: {e}")

        # Lighter — WebSocket balance + fills
        try:
            from backend.markets.providers.lighter_provider import LighterProvider
            from backend.core.activity.sources.lighter_source import (
                LighterActivitySource,
            )

            lighter = LighterProvider()
            await lighter.connect()
            tracker.register_source("lighter", LighterActivitySource(addr, lighter))
        except Exception as e:
            _facade.logger.warning(f"Lighter activity source skipped: {e}")

        # Polymarket — CLOB fills (REST) + Polygon on-chain
        try:
            from backend.core.activity.sources.polymarket_source import (
                PolymarketActivitySource,
            )

            clob = _facade.clob_from_settings()
            tracker.register_source("polymarket", PolymarketActivitySource(addr, clob))
        except Exception as e:
            _facade.logger.warning(f"Polymarket activity source skipped: {e}")

        # Azuro — Gnosis Chain subgraph bets
        try:
            from backend.clients.azuro_client import AzuroClient
            from backend.core.activity.sources.azuro_source import AzuroActivitySource

            azuro_client = AzuroClient()
            tracker.register_source("azuro", AzuroActivitySource(addr, azuro_client))
        except Exception as e:
            _facade.logger.warning(f"Azuro activity source skipped: {e}")

        # Limitless — DISABLED (smart wallet not deployed on Base, 2026-05-30)
        # try:
        #     from backend.clients.limitless_client import LimitlessClient
        #     from backend.core.activity.sources.limitless_source import LimitlessActivitySource
        #     limitless_client = LimitlessClient()
        #     tracker.register_source("limitless", LimitlessActivitySource(addr, limitless_client))
        # except Exception as e:
        #     logger.warning(f"Limitless activity source skipped: {e}")

        # Kalshi — REST fills + position polling (skip when disabled or no credentials)
        if settings.KALSHI_ENABLED and settings.KALSHI_PRIVATE_KEY_PATH and _facade.Path(settings.KALSHI_PRIVATE_KEY_PATH).expanduser().exists():
            try:
                from backend.data.kalshi_client import KalshiClient
                from backend.core.activity.sources.kalshi_source import KalshiActivitySource

                kalshi_client = KalshiClient()
                tracker.register_source("kalshi", KalshiActivitySource(addr, kalshi_client))
            except Exception as e:
                _facade.logger.warning(f"Kalshi activity source skipped: {e}")

        # Ostium — SDK fills + position polling
        try:
            from backend.clients.ostium_client import OstiumClient
            from backend.core.activity.sources.ostium_source import OstiumActivitySource

            ostium_client = OstiumClient()
            tracker.register_source("ostium", OstiumActivitySource(addr, ostium_client))
        except Exception as e:
            _facade.logger.warning(f"Ostium activity source skipped: {e}")

        # Myriad — REST fills + position polling
        try:
            from backend.clients.myriad_client import MyriadClient
            from backend.core.activity.sources.myriad_source import MyriadActivitySource

            myriad_client = MyriadClient()
            tracker.register_source("myriad", MyriadActivitySource(addr, myriad_client))
        except Exception as e:
            _facade.logger.warning(f"Myriad activity source skipped: {e}")

        # SXBet — REST fills + balance polling
        try:
            from backend.clients.sxbet_client import SXBetClient
            from backend.core.activity.sources.sxbet_source import SXBetActivitySource

            sxbet_client = SXBetClient()
            tracker.register_source("sxbet", SXBetActivitySource(addr, sxbet_client))
        except Exception as e:
            _facade.logger.warning(f"SXBet activity source skipped: {e}")

        # Paper — event-driven (no polling, emits from trading engine)
        try:
            from backend.core.activity.sources.paper_source import PaperActivitySource

            tracker.register_source("paper", PaperActivitySource())
        except Exception as e:
            _facade.logger.warning(f"Paper activity source skipped: {e}")
    def _patch_weather_job(self) -> None:
        """Replace weather_scan_and_trade_job with a version that dispatches Telegram alerts."""
        import backend.core.scheduling.scheduler as sched_mod

        bot = self._bot
        clob = self._clob

        original_job = sched_mod.weather_scan_and_trade_job

        async def patched_weather_job(mode: str = "paper"):
            """Weather job with Telegram dispatch."""
            from backend.core.weather_signals import scan_for_weather_signals
            from backend.core.scheduling.scheduler import log_event

            signals = await scan_for_weather_signals(mode=mode)
            actionable = [s for s in signals if s.passes_threshold]

            log_event(
                "data", f"Weather: {len(signals)} signals, {len(actionable)} actionable"
            )

            if not actionable:
                return

            # Telegram confirm-mode: send alert with keyboard, wait for user press
            if bot and bot._bot:
                for signal in actionable[:3]:
                    try:
                        await bot.send_weather_signal(signal)
                        log_event(
                            "info",
                            f"Telegram alert sent: {signal.market.city_name} {signal.direction.upper()}",
                        )
                    except Exception as e:
                        _facade.logger.warning(
                            f"[orchestrator.patched_weather_job] {type(e).__name__}: Failed to send weather alert: {e}",
                            exc_info=True,
                        )
            else:
                if mode == "paper":
                    await _facade._auto_execute_weather(actionable[:3], clob)

            try:
                await original_job(mode)
            except Exception as e:
                _facade.logger.debug(
                    f"[orchestrator.patched_weather_job] {type(e).__name__}: Original weather job error (non-fatal): {e}",
                    exc_info=True,
                )

        sched_mod.weather_scan_and_trade_job = patched_weather_job
    async def _execute_weather_signal(self, signal) -> None:
        """Execute a weather signal triggered by Telegram COPY TRADE button."""
        from backend.core.strategy_executor import execute_decision

        market = signal.market
        token_id = getattr(market, "token_id", "") or market.market_id
        price = market.yes_price if signal.direction == "yes" else market.no_price

        decision = {
            "market_ticker": market.market_id,
            "direction": signal.direction,
            "size": signal.suggested_size,
            "entry_price": price,
            "edge": getattr(signal, "edge", 0.0),
            "confidence": getattr(signal, "model_probability", 0.5),
            "model_probability": getattr(signal, "model_probability", 0.5),
            "token_id": token_id,
            "platform": _facade.settings.DEFAULT_VENUE,
            "market_type": "weather",
            "reasoning": "weather copy trade",
        }

        result = await execute_decision(decision, "weather_emos", db=None)
        if result is None:
            _facade.logger.warning(
                f"Weather copy trade rejected (non-fatal): {signal.direction} "
                f"${signal.suggested_size:.2f} @ {price:.3f}"
            )
            return None

        _facade.logger.info(
            f"Weather trade executed: {signal.direction} ${signal.suggested_size:.2f} @ {price:.3f}"
        )
        return result
    async def _handle_copy_signals(self, signals: list) -> None:
        # Apply CopyPolicyEngine filtering if available
        from backend.core.wallet.registry import get_copy_engine

        copy_engine = get_copy_engine()
        if copy_engine is not None:
            try:
                from backend.core.copy_source import CopySignalData
                from datetime import datetime, timezone

                policy_signals = [
                    CopySignalData(
                        source_name=getattr(sig, "source_name", "orchestrator"),
                        leader_address=getattr(sig, "leader_address", ""),
                        condition_id=getattr(sig.source_trade, "condition_id", ""),
                        side=getattr(sig, "our_side", "BUY"),
                        raw_size=getattr(sig, "our_size", 0.0),
                        confidence=getattr(sig, "confidence", 0.5),
                        captured_at=datetime.now(timezone.utc),
                    )
                    for sig in signals
                ]
                source_name = (
                    getattr(signals[0], "source_name", "orchestrator")
                    if signals
                    else "orchestrator"
                )
                accepted = await copy_engine.process(policy_signals, source_name)
                if not accepted:
                    _facade.logger.info("[orchestrator] CopyPolicyEngine filtered all signals")
                    return
                # Map back: keep only signals whose (condition_id, side) survived policy
                accepted_keys = {(s.condition_id, s.side) for s in accepted}
                signals = [
                    sig
                    for sig in signals
                    if (
                        getattr(getattr(sig, "source_trade", None), "condition_id", ""),
                        getattr(sig, "our_side", ""),
                    )
                    in accepted_keys
                ]
            except Exception as e:
                _facade.logger.warning(f"CopyPolicyEngine filtering failed (non-fatal): {e}")

        for sig in signals:
            try:
                result = await self._execute_copy_signal(sig)
                executed = result.success if result else False
                order_id = result.order_id if result else ""

                if self._bot:
                    await self._bot.send_copy_alert(
                        sig, executed=executed, order_id=order_id
                    )
                else:
                    _facade.logger.info(
                        f"Copy signal: {sig.our_side} ${sig.our_size:.2f} "
                        f"executed={executed} order={order_id}"
                    )
            except Exception as e:
                _facade.logger.error(
                    f"[orchestrator._handle_copy_signals] {type(e).__name__}: Copy signal execution error: {e}",
                    exc_info=True,
                )
                if self._bot:
                    await self._bot.send_error_alert(
                        str(e), context="Copy trade execution"
                    )
    async def _execute_copy_signal(self, signal):
        if not self._clob:
            return None

        trade = signal.source_trade
        token_id = await self._condition_to_token(trade.condition_id, trade.outcome)

        if signal.our_side == "SELL":
            size = signal.our_size if signal.our_size > 0 else 10.0
        else:
            size = signal.our_size

        if size < 1.0:
            _facade.logger.debug(f"Copy signal size ${size:.2f} below minimum — skipping")
            return None

        if not self._clob:
            _facade.logger.warning("CLOB not available — skipping order placement")
            return None

        return await self._clob.place_limit_order(
            token_id=token_id,
            side=signal.our_side,
            price=signal.market_price,
            size=size,
        )
    async def on_mode_switch(self, new_mode: str) -> None:
        _facade.settings.ACTIVE_MODES = new_mode
        _facade.logger.info(f"Trading modes updated to: {new_mode}")
    async def _on_pause(self) -> None:
        from backend.core.scheduling.scheduler import stop_scheduler

        stop_scheduler()
        _facade.logger.info("Trading paused via Telegram")
    async def _on_resume(self) -> None:
        from backend.core.scheduling.scheduler import start_scheduler

        start_scheduler()
        _facade.logger.info("Trading resumed via Telegram")
    async def _condition_to_token(self, condition_id: str, outcome: str) -> str:
        """Map condition_id + outcome ("YES"/"NO") to a CLOB token ID via Gamma API."""
        cache_key = f"{condition_id}:{outcome}"
        if cache_key in self._condition_cache:
            return self._condition_cache[cache_key]

        import httpx as _httpx

        try:
            async with _httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{_facade.settings.GAMMA_API_URL}/markets",
                    params={"conditionId": condition_id},
                    timeout=10.0,
                )
            resp.raise_for_status()
            data = resp.json()
            if not data:
                _facade.logger.warning(
                    f"No market found for condition_id={condition_id}, using fallback"
                )
                result = condition_id
                self._condition_cache[cache_key] = result
                return result

            market = data[0]
            tokens = market.get("tokens", [])
            if outcome.upper() == "YES" and len(tokens) > 0:
                result = str(tokens[0].get("token_id", condition_id))
            elif outcome.upper() == "NO" and len(tokens) > 1:
                result = str(tokens[1].get("token_id", condition_id))
            else:
                result = condition_id

            self._condition_cache[cache_key] = result
            return result
        except (_httpx.HTTPError, KeyError, IndexError) as e:
            _facade.logger.warning(
                f"[orchestrator._condition_to_token] {type(e).__name__}: Failed to resolve token_id for {condition_id}/{outcome}: {e}",
                exc_info=True,
            )
            return condition_id
