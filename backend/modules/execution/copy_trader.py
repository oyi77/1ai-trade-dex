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
import os
import time
from typing import Optional

import httpx

DEFAULT_MIN_SCORE = float(os.environ.get("COPY_TRADER_MIN_SCORE", 15.0))

from backend.core.activity_logger import activity_logger
from backend.config import settings

from loguru import logger

GAMMA_HOST = settings.GAMMA_API_URL
CLOB_HOST = settings.CLOB_API_URL
DATA_HOST = settings.DATA_API_URL


def _extract_clob_token_id(market_data: dict) -> Optional[str]:
    """Extract the first clobTokenId from a market data dict.

    Handles both string-encoded JSON and native list formats for
    the ``clobTokenIds`` field.  Also checks ``tokens`` array and
    ``clob_token_id`` scalar as fallback keys seen in some Gamma
    responses.
    """
    clob_token_ids = market_data.get("clobTokenIds")
    if clob_token_ids:
        if isinstance(clob_token_ids, str):
            try:
                clob_token_ids = json.loads(clob_token_ids)
            except Exception:
                logger.exception("Failed to parse CLOB token IDs JSON")
                clob_token_ids = []
        if isinstance(clob_token_ids, list) and clob_token_ids:
            return str(clob_token_ids[0])

    tokens = market_data.get("tokens")
    if isinstance(tokens, list) and tokens:
        first = tokens[0]
        if isinstance(first, dict):
            tid = first.get("token_id") or first.get("clob_token_id")
            if tid:
                return str(tid)

    scalar = market_data.get("clob_token_id")
    if scalar:
        return str(scalar)

    return None


async def _fetch_token_id(
    condition_id: str, http: Optional[httpx.AsyncClient] = None
) -> Optional[str]:
    """Fetch clobTokenIds[0] for a condition_id via multiple API fallbacks.

    Resolution order:
      1. Gamma /markets?conditionId=... (query param — original path)
      2. Gamma /markets/{condition_id}   (path segment)
      3. CLOB /markets/{condition_id}    (CLOB markets endpoint)
    """
    close_client = False
    if http is None:
        http = httpx.AsyncClient(timeout=10.0)
        close_client = True
    attempts: list[str] = []

    # Rate-limited token resolution cache (in-memory, process-local)
    # Reduces Gamma API calls from 3-per-condition to cache-hits
    if not hasattr(_fetch_token_id, "_cache"):
        _fetch_token_id._cache = {}  # type: dict[str, Optional[str]]
        _fetch_token_id._lock = asyncio.Lock()

    async with _fetch_token_id._lock:
        if condition_id in _fetch_token_id._cache:
            return _fetch_token_id._cache[condition_id]

    token_id = None

    try:
        # --- Attempt 1: Gamma query-param (original approach) ---
        attempts.append("gamma-query")
        await asyncio.sleep(0.3)  # Respect Gamma rate limit: 300 req/10s
        resp = await http.get(
            f"{GAMMA_HOST}/markets",
            params={"conditionId": condition_id},
        )
        if resp.status_code == 200:
            markets = resp.json()
            if markets and isinstance(markets, list) and len(markets) > 0:
                token_id = _extract_clob_token_id(markets[0])

        if not token_id:
            # --- Attempt 2: Gamma path-segment ---
            attempts.append("gamma-path")
            await asyncio.sleep(0.3)
            resp = await http.get(f"{GAMMA_HOST}/markets/{condition_id}")
            if resp.status_code == 200:
                data = resp.json()
                market = (
                    data
                    if isinstance(data, dict)
                    else (data[0] if isinstance(data, list) and data else None)
                )
                if market:
                    token_id = _extract_clob_token_id(market)

        if not token_id:
            # --- Attempt 3: CLOB markets endpoint ---
            attempts.append("clob-markets")
            await asyncio.sleep(0.3)
            resp = await http.get(f"{CLOB_HOST}/markets/{condition_id}")
            if resp.status_code == 200:
                data = resp.json()
                market = (
                    data
                    if isinstance(data, dict)
                    else (data[0] if isinstance(data, list) and data else None)
                )
                if market:
                    token_id = _extract_clob_token_id(market)

        if not token_id:
            logger.warning(
                f"CopyTrader: token_id fetch failed for condition_id={condition_id[:20]}... "
                f"— tried: {', '.join(attempts)}"
            )
        return token_id
    except Exception as e:
        logger.warning(
            f"CopyTrader: token_id fetch error for condition_id={condition_id[:20]}... "
            f"(tried: {', '.join(attempts)}): {e}"
        )
        return None
    finally:
        # Cache result for this cycle (positive or negative)
        async with _fetch_token_id._lock:
            _fetch_token_id._cache[condition_id] = token_id
        if close_client:
            await http.aclose()


# Import from extracted modules
from backend.strategies.wallet_sync import (  # noqa: E402
    WalletWatcher as WalletWatcher,
    WalletTrade as WalletTrade,
)
from backend.strategies.order_executor import (  # noqa: E402
    LeaderboardScorer,
    ScoredTrader,
    CopySignal,
    OrderExecutor,
)


def get_target_wallet_db_stats(db, wallet_address: str) -> tuple[float, float, int]:
    """Query the DB for the 30-day win rate, ROI, and sample size of the target wallet.

    Returns:
        (win_rate, roi, sample_size)
    """
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import and_
    from backend.models.database import Trade, CopyTraderEntry

    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)

    # Query trades joined with CopyTraderEntry on condition_id matching the wallet
    try:
        trades = (
            db.query(Trade)
            .join(CopyTraderEntry, and_(
                Trade.condition_id == CopyTraderEntry.condition_id,
                CopyTraderEntry.wallet == wallet_address
            ))
            .filter(
                Trade.strategy == "copy_trader",
                Trade.settled.is_(True),
                Trade.timestamp >= thirty_days_ago
            )
            .all()
        )
    except Exception as e:
        logger.warning(f"Failed to query target wallet DB stats: {e}")
        return 0.0, 0.0, 0

    if not trades:
        return 0.0, 0.0, 0

    sample_size = len(trades)
    wins = sum(1 for t in trades if t.result == "win")
    win_rate = wins / sample_size if sample_size > 0 else 0.0

    total_cost = sum(t.size for t in trades)
    total_pnl = sum(t.pnl if t.pnl is not None else 0.0 for t in trades)
    roi = total_pnl / total_cost if total_cost > 0 else 0.0

    return win_rate, roi, sample_size


class CopyTrader:
    """
    Orchestrates the copy trading strategy.

    - Refreshes leaderboard every 6h
    - Polls top wallets every 60s
    - Generates CopySignal for each new trade within risk limits
    """

    def __init__(
        self, bankroll: float = 1000.0, max_wallets: int = 10, min_score: float = DEFAULT_MIN_SCORE
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
        async with self._tracked_lock:
            self._tracked = [t for t in scored if t.score >= self.min_score][
                : self.max_wallets
            ]
        self._last_refresh = asyncio.get_running_loop().time()
        logger.info(f"Tracking {len(self._tracked)} wallets after leaderboard refresh")

    async def poll_once(self, db=None) -> list[CopySignal]:
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
                # Dynamic wallet scoring checks
                win_rate = trader.win_rate
                sample_size = trader.total_trades
                roi = 0.0

                if db is not None:
                    db_win_rate, db_roi, db_sample_size = get_target_wallet_db_stats(db, trader.user)
                    if db_sample_size >= 5:
                        win_rate = db_win_rate
                        roi = db_roi
                        sample_size = db_sample_size

                if win_rate < 0.45:
                    logger.info(
                        f"CopyTrader: skipping wallet {trader.pseudonym} ({trader.user[:10]}) — "
                        f"win rate {win_rate:.1%} < 45%"
                    )
                    continue
                if sample_size < 5:
                    logger.info(
                        f"CopyTrader: skipping wallet {trader.pseudonym} ({trader.user[:10]}) — "
                        f"sample size {sample_size} < 5 trades"
                    )
                    continue

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
        "min_score": DEFAULT_MIN_SCORE,
        "poll_interval": 60,
        "interval_seconds": 60,
    }

    name = "copy_trader"
    description = "Mirror top Polymarket whale traders proportionally to our bankroll"
    category = "copy_trading"

    # Event-driven WebSocket subscriptions
    subscribed_tokens: set[str] = set()
    subscribed_events: set[str] = {"last_trade_price"}

    # Cache for active market condition_ids (refreshed every 5 min)
    _ACTIVE_CACHE_TTL = 300  # seconds

    def __init__(self, max_wallets: int = 20, min_score: float = DEFAULT_MIN_SCORE):
        super().__init__()
        # Defer bankroll resolution — _resolve_bankroll() uses FOR UPDATE which
        # can block/deadlock when called during startup inside the event loop.
        # The engine bankroll will be resolved lazily on first run_cycle().
        self._bankroll_resolved = False
        self._max_wallets = max_wallets
        self._min_score = min_score
        self._engine = CopyTrader(
            bankroll=1000.0, max_wallets=max_wallets, min_score=min_score
        )
        self._task: asyncio.Task | None = None
        self._active_condition_ids: set[str] = set()
        self._active_cache_ts: float = 0.0

    @staticmethod
    def _resolve_bankroll(mode: str = None) -> float:
        try:
            from backend.models.database import SessionLocal, BotState

            effective = mode or settings.TRADING_MODE
            db = SessionLocal()
            try:
                state = db.query(BotState).first()
                if state:
                    if effective == "paper":
                        return float(
                            state.paper_bankroll
                            if state.paper_bankroll is not None
                            else settings.INITIAL_BANKROLL
                        )
                    elif effective == "testnet":
                        return float(
                            state.testnet_bankroll
                            if state.testnet_bankroll is not None
                            else settings.INITIAL_BANKROLL
                        )
                    else:
                        return float(
                            state.bankroll
                            if state.bankroll is not None
                            else settings.INITIAL_BANKROLL
                        )
            finally:
                db.close()
        except Exception:
            logger.exception("Failed to retrieve bot bankroll for copy trader")
        return 1000.0  # safe default

    async def _fetch_active_condition_ids(self) -> set[str]:
        if (
            self._active_condition_ids
            and (time.monotonic() - self._active_cache_ts) < self._ACTIVE_CACHE_TTL
        ):
            return self._active_condition_ids

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{GAMMA_HOST}/markets",
                    params={"closed": "false", "active": "true"},
                )
                if resp.status_code == 200:
                    markets = resp.json()
                    if isinstance(markets, list):
                        self._active_condition_ids = {
                            m["conditionId"]
                            for m in markets
                            if isinstance(m, dict) and m.get("conditionId")
                        }
                        self._active_cache_ts = time.monotonic()
                        logger.info(
                            f"CopyTrader: refreshed active market cache — "
                            f"{len(self._active_condition_ids)} active condition_ids"
                        )
        except Exception as e:
            logger.warning(f"CopyTrader: failed to fetch active markets: {e}")

        return self._active_condition_ids

    async def market_filter(self, markets):
        return markets

    async def _get_active_wallets(self, ctx) -> list[str]:
        """
        Return union of: leaderboard top-N + enabled WalletConfig rows.
        WalletConfig rows are always included (user-curated, may not score well).
        """
        from backend.db.utils import get_db_session
        from backend.models.database import WalletConfig

        max_wallets = ctx.params.get("max_wallets", 20)
        min_score = ctx.params.get("min_score", DEFAULT_MIN_SCORE)

        # 1. Get user-configured wallets
        with get_db_session() as db:
            user_wallets = [
                wallet.address
                for wallet in db.query(WalletConfig)
                .filter(WalletConfig.enabled.is_(True))
                .all()
            ]

        # 2. Get leaderboard top wallets
        leaderboard_wallets = []
        try:
            traders = await self._engine._scorer.fetch_and_score(top_n=50)
            scored = [t for t in traders if t.score >= min_score]
            scored.sort(key=lambda t: t.score, reverse=True)
            ctx.logger.info(
                f"CopyTrader: min_score={min_score}, total traders={len(traders)}, scored (>=min_score)={len(scored)}, top5_scores={[round(t.score,1) for t in scored[:5]]}"
            )
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

    async def on_market_event(self, event):
        """Handle CLOB WS events for leaderboard traders' tokens."""
        from backend.strategies.base import MarketEvent

        if not isinstance(event, MarketEvent):
            return None
        if event.event_type != "last_trade_price":
            return None
        price = float(event.data.get("price", 0))
        size = float(event.data.get("size", 0))
        if size <= 0 or price <= 0:
            return None
        self.subscribed_tokens.add(event.token_id)
        confidence = min(0.85, size / 1000.0)
        edge = abs(price - 0.50) * 0.3
        # E-101: Copy trade direction should follow the copied trader's actual side,
        # not just price > 0.50. Use event data if available, else derive from edge.
        copied_side = event.data.get("side", "").upper()
        if copied_side not in ("BUY", "SELL"):
            # Default: BUY when edge is positive (price implies value), SKIP otherwise
            decision = "BUY" if edge > 0.01 else "SKIP"
            direction = "yes" if price > 0.50 else "no"
        else:
            decision = copied_side
            direction = event.data.get("outcome", "yes" if price > 0.50 else "no")
        return {
            "decision": decision,
            "market_ticker": event.token_id,
            "confidence": confidence,
            "edge": edge,
            "size": min(10.0, size * 0.01),
            "direction": direction,
            "model_probability": price,
            "platform": settings.DEFAULT_VENUE,
            "strategy_name": self.name,
            "reasoning": "copy_trader_ws_event",
        }

    async def run_cycle(self, ctx):
        from backend.models.database import DecisionLog

        max_wallets = ctx.params.get("max_wallets", 20)
        min_score = ctx.params.get("min_score", DEFAULT_MIN_SCORE)

        result = CycleResult(decisions_recorded=0, trades_attempted=0, trades_placed=0)
        try:
            # Refresh bankroll from DB each cycle so it stays current
            self._engine.bankroll = self._resolve_bankroll(mode=ctx.mode)
            if self._engine._executor:
                self._engine._executor.bankroll = self._engine.bankroll

            if not self._engine._running:
                await self._engine.start()

            # Ensure shared httpx client exists to prevent per-call client leaks
            if not self._engine._http:
                self._engine._http = httpx.AsyncClient(
                    timeout=httpx.Timeout(15.0),
                    limits=httpx.Limits(max_keepalive_connections=5),
                )

            wallet_pool = await self._get_active_wallets(ctx)
            result.markets_scanned = len(wallet_pool)

            signals = await self._engine.poll_once(db=ctx.db)

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
                        {
                            "min_score": min_score,
                            "max_wallets": max_wallets,
                            "sources": ["copy_trader"],
                        }
                    )
                    reason = f"No new trades detected for wallet {wallet[:10]}..."

                log_row = DecisionLog(
                    strategy=self.name,
                    market_ticker=wallet[:42],  # wallet address as identifier
                    decision=decision,
                    # E-102: None check on trader_score before division
                    confidence=(
                        (wallet_signals[0].trader_score / 100.0)
                        if wallet_signals and wallet_signals[0].trader_score is not None
                        else None
                    ),
                    signal_data=(
                        signal_data
                        if wallet_signals
                        else json.dumps(
                            {
                                "min_score": min_score,
                                "max_wallets": max_wallets,
                                "sources": ["copy_trader"],
                            }
                        )
                    ),
                    reason=reason,
                )
                ctx.db.add(log_row)

            ctx.db.commit()
            ctx.db.expire_all()
            result.decisions_recorded = len([s for s in (signals or []) if s])
            result.trades_attempted = len(signals) if signals else 0

            # Filter out signals for expired/settled markets
            if signals:
                active_ids = await self._fetch_active_condition_ids()
                before_count = len(signals)
                signals = [
                    s for s in signals if s.source_trade.condition_id in active_ids
                ]
                filtered = before_count - len(signals)
                if filtered:
                    ctx.logger.info(
                        f"CopyTrader: filtered {filtered}/{before_count} signals "
                        f"for expired/settled markets — {len(signals)} remain"
                    )
                result.trades_attempted = len(signals)

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
                    db=ctx.db,
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
                        "platform": settings.DEFAULT_VENUE,
                        "strategy_name": "copy_trader",
                        "reasoning": signal.reasoning,
                    }
                )

        except Exception as e:
            result.errors.append(str(e))
            ctx.logger.error(f"CopyTraderStrategy cycle error: {e}")
        return result
