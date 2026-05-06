"""
Copy Trader Strategy for PolyEdge.

Monitors top Polymarket traders (by leaderboard score) and mirrors
their trades proportionally to our bankroll.

Execution mode: auto_with_limits — trades execute within risk manager
bounds without Telegram confirmation. Post-execution alerts are sent.

Data flow:
  Polymarket Leaderboard → score top 50 → track top N wallets
  Every 60s: poll /trades per wallet → detect new trades → mirror proportionally
  Exit tracking: cumulative SELL >= 50% of original entry → mirror exit
"""

import asyncio
import json
import logging
from typing import Optional

import httpx

from backend.core.activity_logger import activity_logger
from backend.config import settings

logger = logging.getLogger("trading_bot")

GAMMA_HOST = settings.GAMMA_API_URL


async def _fetch_token_id(
    condition_id: str, http: Optional[httpx.AsyncClient] = None
) -> Optional[str]:
    """Fetch clobTokenIds[0] for a condition_id from Gamma API."""
    close_client = False
    if http is None:
        http = httpx.AsyncClient(timeout=10.0)
        close_client = True
    try:
        resp = await http.get(
            f"{GAMMA_HOST}/markets",
            params={"conditionId": condition_id},
        )
        if resp.status_code == 200:
            markets = resp.json()
            if markets and isinstance(markets, list) and len(markets) > 0:
                clob_token_ids = markets[0].get("clobTokenIds") or []
                if isinstance(clob_token_ids, str):
                    try:
                        clob_token_ids = json.loads(clob_token_ids)
                    except Exception as e:
                        logger.debug(f"Failed to parse clobTokenIds JSON: {e}")
                        clob_token_ids = []
                if clob_token_ids:
                    return str(clob_token_ids[0])
        return None
    except Exception as e:
        logger.warning(f"Failed to fetch token_id for {condition_id[:20]}...: {e}")
        return None
    finally:
        if close_client:
            await http.aclose()


# Import from extracted modules
from backend.strategies.wallet_sync import WalletWatcher, WalletTrade
from backend.strategies.order_executor import (
    LeaderboardScorer,
    ScoredTrader,
    CopySignal,
    OrderExecutor,
)


class CopyTrader:
    """
    Orchestrates the copy trading strategy.

    - Refreshes leaderboard every 6h
    - Polls top wallets every 60s
    - Generates CopySignal for each new trade within risk limits
    """

    def __init__(
        self, bankroll: float = 1000.0, max_wallets: int = 10, min_score: float = 30.0
    ):
        self.bankroll = bankroll
        self.max_wallets = max_wallets
        self.min_score = min_score
        self._tracked: list[ScoredTrader] = []
        self._tracked_lock = asyncio.Lock()
        self._http: Optional[httpx.AsyncClient] = None
        self._watcher: Optional[WalletWatcher] = None
        self._scorer: Optional[LeaderboardScorer] = None
        self._executor: OrderExecutor = OrderExecutor(bankroll)
        self._last_refresh: float = 0.0
        self._running = False

    async def start(self):
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            limits=httpx.Limits(max_keepalive_connections=5),
        )
        self._watcher = WalletWatcher(self._http)
        self._scorer = LeaderboardScorer(self._http)
        self._executor = OrderExecutor(self.bankroll, http=self._http)
        self._running = True
        await self._refresh_leaderboard()

    async def stop(self):
        self._running = False
        if self._http:
            await self._http.aclose()

    async def _refresh_leaderboard(self):
        """Refresh tracked wallets from leaderboard."""
        scored = await self._scorer.fetch_and_score(top_n=50)
        self._tracked = [t for t in scored if t.score >= self.min_score][
            : self.max_wallets
        ]
        self._last_refresh = asyncio.get_running_loop().time()
        logger.info(f"Tracking {len(self._tracked)} wallets after leaderboard refresh")

    async def poll_once(self) -> list[CopySignal]:
        """Poll all tracked wallets once. Returns new copy signals."""
        now = asyncio.get_running_loop().time()
        if now - self._last_refresh > 21600:
            await self._refresh_leaderboard()

        signals: list[CopySignal] = []
        seen_condition_ids: set = set()

        for trader in self._tracked:
            if not trader.user:
                continue
            try:
                new_buys, new_exits = await self._watcher.poll(trader.user)

                for trade in new_buys:
                    if trade.condition_id in seen_condition_ids:
                        continue
                    seen_condition_ids.add(trade.condition_id)
                    signal = await self._executor.mirror_buy_async(trader, trade)
                    if signal:
                        signals.append(signal)

                for trade in new_exits:
                    signal = self._executor.mirror_exit(trader, trade)
                    if signal:
                        signals.append(signal)

            except Exception as e:
                logger.warning(f"Poll error for {trader.pseudonym}: {e}")

        return signals

    def _mirror_buy(self, trader, trade):
        """Synchronous mirror_buy delegation — uses executor if started, else creates one."""
        executor = self._executor or OrderExecutor(self.bankroll)
        return executor.mirror_buy(trader, trade)

    async def run_loop(self, poll_interval: int = 60, on_signal=None):
        """
        Main polling loop. Calls on_signal(signals) for each batch of new signals.
        Run this as an asyncio task.
        """
        logger.info(
            f"Copy trader loop started — polling {len(self._tracked)} wallets every {poll_interval}s"
        )
        while self._running:
            try:
                signals = await self.poll_once()
                if signals and on_signal:
                    await on_signal(signals)
            except Exception as e:
                logger.error(f"Copy trader loop error: {e}")
            await asyncio.sleep(poll_interval)


# ---------------------------------------------------------------------------
# BaseStrategy wrapper
# ---------------------------------------------------------------------------

from backend.strategies.base import BaseStrategy, CycleResult  # noqa: E402


class CopyTraderStrategy(BaseStrategy):
    """Wraps CopyTrader engine in the BaseStrategy plugin interface."""

    default_params = {
        "max_wallets": 20,
        "min_score": 30.0,
        "poll_interval": 60,
        "interval_seconds": 60,
    }

    name = "copy_trader"
    description = "Mirror top Polymarket whale traders proportionally to our bankroll"
    category = "copy_trading"

    def __init__(self, max_wallets: int = 20, min_score: float = 30.0):
        super().__init__()
        # Resolve bankroll from DB (BotState) or fall back to default
        bankroll = self._resolve_bankroll()
        self._engine = CopyTrader(
            bankroll=bankroll, max_wallets=max_wallets, min_score=min_score
        )
        self._task: asyncio.Task | None = None

    @staticmethod
    def _resolve_bankroll(mode: str = None) -> float:
        try:
            from backend.models.database import SessionLocal, BotState
            from backend.config import settings as _settings

            effective = mode or _settings.TRADING_MODE
            db = SessionLocal()
            try:
                state = db.query(BotState).first()
                if state:
                    if effective == "paper":
                        return float(
                            state.paper_bankroll
                            if state.paper_bankroll is not None
                            else _settings.INITIAL_BANKROLL
                        )
                    elif effective == "testnet":
                        return float(
                            state.testnet_bankroll
                            if state.testnet_bankroll is not None
                            else _settings.INITIAL_BANKROLL
                        )
                    else:
                        return float(
                            state.bankroll
                            if state.bankroll is not None
                            else _settings.INITIAL_BANKROLL
                        )
            finally:
                db.close()
        except Exception:
            pass
        return 1000.0  # safe default

    async def market_filter(self, markets):
        return markets

    async def _get_active_wallets(self, ctx) -> list[str]:
        """
        Return union of: leaderboard top-N + enabled WalletConfig rows.
        WalletConfig rows are always included (user-curated, may not score well).
        """
        from backend.models.database import WalletConfig

        max_wallets = ctx.params.get("max_wallets", 20)
        min_score = ctx.params.get("min_score", 30.0)

        # 1. Get user-configured wallets
        user_wallets = [
            w.address
            for w in ctx.db.query(WalletConfig)
            .filter(WalletConfig.enabled.is_(True))
            .all()
        ]

        # 2. Get leaderboard top wallets
        leaderboard_wallets = []
        try:
            traders = await self._engine._scorer.fetch_and_score(top_n=50)
            scored = [t for t in traders if t.score >= min_score]
            scored.sort(key=lambda t: t.score, reverse=True)
            ctx.logger.info(f"CopyTrader: min_score={min_score}, total traders={len(traders)}, scored (>=min_score)={len(scored)}, top5_scores={[round(t.score,1) for t in scored[:5]]}")
            leaderboard_wallets = [t.user for t in scored[:max_wallets]]
        except Exception as e:
            ctx.logger.warning(f"CopyTrader: leaderboard fetch failed: {e}")

        # 3. Union (preserve order: user-curated first, then leaderboard)
        seen = set()
        result = []
        for w in user_wallets + leaderboard_wallets:
            if w not in seen:
                seen.add(w)
                result.append(w)

        return result[: max_wallets * 2]  # cap at 2x to avoid runaway

    async def run_cycle(self, ctx):
        from backend.models.database import DecisionLog

        max_wallets = ctx.params.get("max_wallets", 20)
        min_score = ctx.params.get("min_score", 30.0)

        result = CycleResult(decisions_recorded=0, trades_attempted=0, trades_placed=0)
        try:
            # Refresh bankroll from DB each cycle so it stays current
            self._engine.bankroll = self._resolve_bankroll(mode=ctx.mode)
            if self._engine._executor:
                self._engine._executor.bankroll = self._engine.bankroll

            if not self._engine._running:
                await self._engine.start()

            wallet_pool = await self._get_active_wallets(ctx)

            signals = await self._engine.poll_once()

            if not signals:
                ctx.logger.info(
                    f"CopyTrader: no new copy signals this cycle "
                    f"(tracked={len(self._engine._tracked)} wallets)"
                )

            # Build a set of wallets that produced signals for fast lookup
            signaled_wallets = {s.source_wallet for s in signals} if signals else set()

            # Record a DecisionLog row for each wallet polled
            for wallet in wallet_pool:
                decision = "FOLLOW" if wallet in signaled_wallets else "SKIP"
                # Find matching signal for scoring breakdown if present
                wallet_signals = [
                    s for s in (signals or []) if s.source_wallet == wallet
                ]
                if wallet_signals:
                    signal_data = json.dumps(
                        {
                            "trader_score": wallet_signals[0].trader_score,
                            "signals_count": len(wallet_signals),
                            "outcomes": [s.our_side for s in wallet_signals],
                            "sources": ["copy_trader", "whale_tracker"],
                        }
                    )
                    reason = wallet_signals[0].reasoning
                else:
                    signal_data = json.dumps(
                        {"min_score": min_score, "max_wallets": max_wallets, "sources": ["copy_trader"]}
                    )
                    reason = f"No new trades detected for wallet {wallet[:10]}..."

                log_row = DecisionLog(
                    strategy=self.name,
                    market_ticker=wallet[:42],  # wallet address as identifier
                    decision=decision,
                    confidence=wallet_signals[0].trader_score / 100.0
                    if wallet_signals
                    else None,
                    signal_data=signal_data if wallet_signals else json.dumps(
                        {"min_score": min_score, "max_wallets": max_wallets, "sources": ["copy_trader"]}
                    ),
                    reason=reason,
                )
                ctx.db.add(log_row)

            ctx.db.commit()
            result.decisions_recorded = len([s for s in (signals or []) if s])
            result.trades_attempted = len(signals) if signals else 0

            # Fetch token_ids in parallel for all signals
            token_id_tasks = [
                _fetch_token_id(s.source_trade.condition_id, self._engine._http)
                for s in (signals or [])
            ]
            token_ids = (
                await asyncio.gather(*token_id_tasks, return_exceptions=True)
                if token_id_tasks
                else []
            )

            # Populate result.decisions so strategy_executor can place trades
            for i, signal in enumerate(signals or []):
                raw_tid = token_ids[i] if i < len(token_ids) else None
                token_id = raw_tid if isinstance(raw_tid, str) else None
                if not token_id:
                    ctx.logger.warning(
                        f"CopyTrader: skipping signal for {signal.source_trade.condition_id[:20]}... — no token_id"
                    )
                    continue

                confidence = signal.trader_score / 100.0 if signal.trader_score else 0.5
                edge = abs(signal.market_price - 0.5) if signal.market_price else 0.0
                copy_direction = signal.our_side.lower()
                copy_entry_price = signal.market_price
                if copy_direction in ("no", "down") and signal.market_price:
                    copy_entry_price = round(1.0 - signal.market_price, 6)
                
                activity_logger.log_entry(
                    strategy_name="copy_trader",
                    decision_type="entry",
                    data={
                        "market_ticker": signal.source_trade.condition_id,
                        "whale_address": signal.source_trade.wallet,  # wallet address (0x...)
                        "trader_score": signal.trader_score,
                        "our_size": signal.our_size,
                        "direction": copy_direction,
                        "market_price": signal.market_price,
                        "reasoning": signal.reasoning,
                    },
                    confidence=confidence,
                    mode=ctx.mode,
                    db=ctx.db
                )
                
                result.decisions.append(
                    {
                        "decision": "BUY",
                        "market_ticker": signal.source_trade.condition_id,
                        "token_id": token_id,
                        "direction": copy_direction,
                        "confidence": confidence,
                        "edge": edge,
                        "size": signal.our_size,
                        "entry_price": copy_entry_price,
                        "suggested_size": signal.our_size,
                        "model_probability": confidence,
                        "market_probability": signal.market_price,
                        "platform": "polymarket",
                        "strategy_name": "copy_trader",
                        "reasoning": signal.reasoning,
                    }
                )

        except Exception as e:
            result.errors.append(str(e))
            ctx.logger.error(f"CopyTraderStrategy cycle error: {e}")
        return result
