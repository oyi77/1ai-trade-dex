"""Order execution module for CopyTrader.

Handles leaderboard scoring, trader selection, and order mirroring logic.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import httpx

from backend.strategies.wallet_sync import WalletTrade
from backend.config import settings, _cfg
from backend.core.circuit_breaker import CircuitBreaker, CircuitOpenError
from backend.monitoring.hft_metrics import record_execution, order_placement_latency
from backend.utils.redaction import redact_sensitive

from loguru import logger

data_api_breaker = CircuitBreaker(
    "data_api",
    failure_threshold=settings.CB_FAILURE_THRESHOLD,
    recovery_timeout=settings.CB_RECOVERY_TIMEOUT,
)

DATA_HOST = settings.DATA_API_URL
GAMMA_HOST = settings.GAMMA_API_URL

BTC_5M_SLUG_PATTERN = "btc-updown-5m"


@dataclass
class ScoredTrader:
    """Represents a scored trader from the leaderboard."""

    user: str  # Polymarket user ID (for /trades API)
    wallet: str  # Wallet address (0x...) for on-chain stuff
    pseudonym: str
    profit_30d: float
    win_rate: float
    total_trades: int
    unique_markets: int
    estimated_bankroll: (
        float  # sum of open positions + recent pnl — manual override via config
    )
    score: float = 0.0

    @property
    def market_diversity(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return min(1.0, self.unique_markets / self.total_trades)


@dataclass
class CopySignal:
    """Represents a copy trading signal."""

    source_wallet: str
    source_trade: WalletTrade
    our_side: str
    our_outcome: str
    our_size: float  # Kelly-proportioned USDC size
    market_price: float
    trader_score: float
    reasoning: str
    timestamp: any  # datetime from datetime.now(timezone.utc)


class LeaderboardScorer:
    """Fetches and scores Polymarket leaderboard traders."""

    WEIGHTS = {
        "profit_30d": settings.ORDER_EXECUTOR_WEIGHT_PROFIT_30D,
        "win_rate": settings.ORDER_EXECUTOR_WEIGHT_WIN_RATE,
        "market_diversity": settings.ORDER_EXECUTOR_WEIGHT_MARKET_DIVERSITY,
        "consistency": settings.ORDER_EXECUTOR_WEIGHT_CONSISTENCY,
    }

    def __init__(self, http: httpx.AsyncClient):
        self._http = http

    async def _fetch_win_rate(self, user_id: str) -> Optional[float]:
        """Fetch actual win rate from trade history via data API."""
        try:
            resp = await self._http.get(
                f"{DATA_HOST}/trades",
                params={"user": user_id, "limit": 200},
                timeout=10.0,
            )
            if resp.status_code != 200:
                return None
            trades = resp.json()
            if not trades:
                return None
            settled = [
                t
                for t in trades
                if t.get("settled") or t.get("outcome") or t.get("result")
            ]
            if len(settled) < 5:
                return None
            wins = sum(
                1
                for t in settled
                if t.get("outcome") in ("win", "YES")
                or t.get("result") in ("win", "YES")
                or (t.get("pnl") is not None and float(t.get("pnl", 0)) > 0)
            )
            return wins / len(settled)
        except Exception as e:
            logger.debug(f"Win rate fetch failed for {user_id}: {e}")
            return None

    async def _fetch_actual_bankroll(self, wallet: str) -> Optional[float]:
        async def _fetch_positions() -> Optional[float]:
            resp = await self._http.get(
                f"{DATA_HOST}/positions",
                params={"user": wallet},
                timeout=10.0,
            )
            if resp.status_code != 200:
                return None
            positions = resp.json()
            if not positions:
                return None

            total_value = 0.0
            for pos in positions:
                value = pos.get("assetValue") or pos.get("value") or pos.get("size")
                if value:
                    try:
                        total_value += abs(float(value))
                    except (ValueError, TypeError):
                        logger.debug("order_executor: invalid assetValue in position data")

            realized_pnl = 0.0
            if positions and len(positions) > 0:
                for pos in positions:
                    pnl = (
                        pos.get("realizedPnl")
                        or pos.get("realizedPnl24h")
                        or pos.get("pnl")
                    )
                    if pnl:
                        try:
                            realized_pnl += float(pnl)
                        except (ValueError, TypeError):
                            logger.debug("order_executor: invalid realizedPnl in position data")

            return total_value + realized_pnl

        try:
            return await data_api_breaker.call(_fetch_positions)
        except CircuitOpenError:
            logger.warning(
                "[order_executor] Data API circuit open, cannot fetch bankroll"
            )
            return None
        except Exception as e:
            logger.debug(f"Bankroll fetch failed for {redact_sensitive(wallet)}: {e}")
            return None

    async def fetch_and_score(self, top_n: int = 50) -> list[ScoredTrader]:
        entries = []
        try:
            resp = await self._http.get(
                f"{DATA_HOST}/{settings.DATA_API_VERSION}/leaderboard",
                params={
                    "timePeriod": "MONTH",
                    "limit": top_n,
                    "category": "OVERALL",
                    "orderBy": "PNL",
                },
            )
            resp.raise_for_status()
            raw_entries = resp.json()
            # Normalize v1 API fields (pnl→profit, vol→volume) to match downstream expectations
            entries = []
            for e in raw_entries:
                entries.append(
                    {
                        "id": e.get("id", ""),
                        "user": e.get("user", ""),
                        "proxyWallet": e.get("proxyWallet", e.get("address", "")),
                        "name": e.get("userName", e.get("name", "")),
                        "profit": float(e.get("pnl", e.get("profit", 0))),
                        "pnlPercentage": float(e.get("pnlPercentage", 0)),
                        "tradesCount": int(e.get("tradesCount", e.get("vol", 0))),
                        "marketsTraded": int(e.get("marketsTraded", 0)),
                        "volume": float(e.get("vol", e.get("volume", 0))),
                    }
                )
        except (httpx.HTTPError, Exception) as e:
            logger.debug(
                f"[order_executor.fetch_and_score] Leaderboard data-api unavailable ({type(e).__name__}: {e}), trying scraper fallback"
            )
            try:
                from backend.data.polymarket_scraper import fetch_real_leaderboard

                scraped = await fetch_real_leaderboard(limit=top_n)
                if scraped:
                    entries = [
                        {
                            "proxyWallet": t.get("wallet", t.get("address", "")),
                            "name": t.get(
                                "pseudonym", t.get("name", t.get("username", "unknown"))
                            ),
                            "profit": t.get(
                                "profit_30d", t.get("profit_loss", t.get("pnl", 0))
                            ),
                            "pnlPercentage": t.get("win_rate", 0) * 100,
                            "tradesCount": t.get(
                                "total_trades",
                                t.get("positions_count", t.get("trades", 0)),
                            ),
                            "marketsTraded": t.get(
                                "unique_markets", t.get("markets_traded", 0)
                            ),
                        }
                        for t in scraped
                    ]
                    logger.info(
                        f"[order_executor] Scraper fallback returned {len(entries)} traders"
                    )
            except Exception as scrape_err:
                logger.debug(
                    f"[order_executor.fetch_and_score] Scraper fallback also failed ({type(scrape_err).__name__}: {scrape_err})"
                )

        if not entries:
            return []

        profits = [float(e.get("profit", 0)) for e in entries]

        max_profit = max(profits) if profits else 1.0
        max_profit = max_profit if max_profit > 0 else 1.0

        traders = []
        for e in entries[:top_n]:
            profit = float(e.get("profit", 0))
            trades = int(e.get("tradesCount", 0))

            user = e.get("id", e.get("user", ""))  # user ID for /trades API
            proxy = e.get("proxyWallet", e.get("address", ""))  # 0x... wallet address

            # For scraped entries, use proxyWallet as user if no id
            if not user:
                user = proxy

            if not user:
                continue

            # E-242: Compute actual win rate from trade history, not pnlPercentage
            actual_win_rate = await self._fetch_win_rate(user)
            win_rate = actual_win_rate if actual_win_rate is not None else 0.0

            actual_bankroll = await self._fetch_actual_bankroll(user)
            if actual_bankroll and actual_bankroll >= 100:
                est_bankroll = actual_bankroll
            else:
                # E-109: Use settings bankroll instead of profit heuristic
                est_bankroll = float(getattr(settings, "INITIAL_BANKROLL", 1000.0))

            trader = ScoredTrader(
                user=user,
                wallet=proxy,
                pseudonym=e.get("name", e.get("pseudonym", "unknown")),
                profit_30d=profit,
                win_rate=max(0.0, min(1.0, win_rate)),
                total_trades=trades,
                unique_markets=int(
                    e.get("marketsTraded", trades)
                ),  # fallback to trades
                estimated_bankroll=est_bankroll,
            )

            # Composite score (0–100)
            profit_score = min(1.0, profit / max_profit) if max_profit > 0 else 0.0
            win_rate_score = trader.win_rate
            diversity_score = trader.market_diversity
            # Consistency: prefer traders with similar-sized bets (low variance in size)
            # We don't have per-trade sizes from leaderboard, so use proxy:
            # higher trade count with consistent profit = more consistent
            consistency_score = min(1.0, trades / 100) * win_rate_score

            trader.score = 100 * (
                self.WEIGHTS["profit_30d"] * profit_score
                + self.WEIGHTS["win_rate"] * win_rate_score
                + self.WEIGHTS["market_diversity"] * diversity_score
                + self.WEIGHTS["consistency"] * consistency_score
            )

            traders.append(trader)

        if not traders:
            logger.info("[order_executor] No traders to score")
            return []

        traders.sort(key=lambda t: t.score, reverse=True)
        logger.info(
            f"Scored {len(traders)} traders. Top: {traders[0].pseudonym} score={traders[0].score:.1f}"
        )
        return traders


class OrderExecutor:
    """Handles order mirroring logic for copy trading."""

    def __init__(
        self, bankroll: float = 1000.0, http: Optional[httpx.AsyncClient] = None
    ):
        self.bankroll = bankroll
        self._http = http
        # Cache: condition_id -> (slug, end_date_iso) or None
        self._market_cache: dict[str, Optional[tuple[str, str]]] = {}

    async def _fetch_market_meta(self, condition_id: str) -> Optional[tuple[str, str]]:
        """Fetch (slug, end_date_iso) for a market from Gamma API. Returns None on failure."""
        if condition_id in self._market_cache:
            return self._market_cache[condition_id]

        if not self._http:
            return None

        try:
            resp = await self._http.get(
                f"{GAMMA_HOST}/markets",
                params={"conditionId": condition_id},
                timeout=10.0,
            )
            if resp.status_code != 200:
                self._market_cache[condition_id] = None
                return None
            data = resp.json()
            markets = data if isinstance(data, list) else data.get("markets", [data])
            if not markets:
                self._market_cache[condition_id] = None
                return None
            m = markets[0]
            slug = m.get("slug", "")
            end_date = m.get("endDate") or m.get("end_date") or m.get("endDateIso", "")
            result = (slug, end_date) if end_date else (slug, "")
            self._market_cache[condition_id] = result
            return result
        except (httpx.HTTPError, Exception) as e:
            logger.debug(
                f"[order_executor._fetch_market_meta] {type(e).__name__}: Market meta fetch failed for {condition_id[:12]}: {e}",
                exc_info=True,
            )
            self._market_cache[condition_id] = None
            return None

    async def mirror_buy_async(
        self, trader: ScoredTrader, trade: WalletTrade
    ) -> Optional[CopySignal]:
        if trade.size < _cfg("ORDER_EXECUTOR_MIN_WHALE_SIZE", 50.0):
            logger.debug(
                f"Skipping copy: trade size ${trade.size:.2f} < ${_cfg('ORDER_EXECUTOR_MIN_WHALE_SIZE', 50.0)} min | {trade.title[:40]}"
            )
            return None

        meta = await self._fetch_market_meta(trade.condition_id)
        if meta:
            slug, end_date_iso = meta

            if BTC_5M_SLUG_PATTERN in slug:
                logger.debug(f"Skipping copy: BTC 5-min market slug={slug}")
                return None

            if end_date_iso:
                try:
                    end_dt = datetime.fromisoformat(end_date_iso.replace("Z", "+00:00"))
                    days_remaining = (end_dt - datetime.now(timezone.utc)).days
                    if days_remaining < _cfg(
                        "ORDER_EXECUTOR_MIN_DAYS_TO_RESOLUTION", 7
                    ):
                        logger.debug(
                            f"Skipping copy: only {days_remaining}d to resolution (need {_cfg('ORDER_EXECUTOR_MIN_DAYS_TO_RESOLUTION', 7)}d) | {trade.title[:40]}"
                        )
                        return None
                except ValueError as e:
                    logger.debug(
                        f"[order_executor.mirror_buy_async] {type(e).__name__}: Could not parse end_date '{end_date_iso}': {e}"
                    )

        return self.mirror_buy(trader, trade)

    def mirror_buy(
        self, trader: ScoredTrader, trade: WalletTrade
    ) -> Optional[CopySignal]:
        """Create a proportional buy signal from a trader's buy trade."""
        if trader.estimated_bankroll <= 0:
            return None

        # Filter: minimum whale trade size (conviction filter)
        if trade.size < _cfg("ORDER_EXECUTOR_MIN_WHALE_SIZE", 50.0):
            logger.debug(
                f"Skipping copy: trade size ${trade.size:.2f} < ${_cfg('ORDER_EXECUTOR_MIN_WHALE_SIZE', 50.0)} min | {trade.title[:40]}"
            )
            return None

        # Filter: skip BTC 5-min markets by title heuristic (slug not available here)
        if BTC_5M_SLUG_PATTERN in (trade.title or "").lower():
            logger.debug(
                f"Skipping copy: BTC 5-min market in title | {trade.title[:40]}"
            )
            return None

        # Proportional sizing: (their trade size / their bankroll) * our bankroll
        their_pct = trade.size / trader.estimated_bankroll
        our_size = their_pct * self.bankroll

        # Cap at MAX_POSITION_FRACTION of our bankroll
        max_position_frac = _cfg("MAX_POSITION_FRACTION", 0.05)
        our_size = min(our_size, max_position_frac * self.bankroll)

        # Cap at MAX_TRADE_SIZE from risk profile (e.g. $50 extreme)
        max_trade_size = _cfg("MAX_TRADE_SIZE", 100.0)
        our_size = min(our_size, max_trade_size)

        our_size = max(0.0, our_size)

        if our_size < 1.0:  # Below Polymarket minimum
            return None

        reasoning = (
            f"Copying {trader.pseudonym} (score={trader.score:.0f}) | "
            f"BUY {trade.outcome} @ {trade.price:.3f} | "
            f"Their size: ${trade.size:.2f} / ~${trader.estimated_bankroll:.0f} bankroll "
            f"= {their_pct:.1%} -> our size: ${our_size:.2f}"
        )

        record_execution(
            strategy="copy_trader", side="BUY", status="placed", latency_s=0.0
        )
        order_placement_latency.labels(strategy="copy_trader", side="BUY").observe(0.0)
        # Convert trade outcome to valid direction for CLOB
        # trade.outcome comes from Polymarket API and should be "YES" or "NO"
        our_side = (
            trade.outcome.upper() if trade.outcome.upper() in ("YES", "NO") else "YES"
        )

        return CopySignal(
            source_wallet=trader.user,
            source_trade=trade,
            our_side=our_side,
            our_outcome=trade.outcome,
            our_size=our_size,
            market_price=trade.price,
            trader_score=trader.score,
            reasoning=reasoning,
            timestamp=datetime.now(timezone.utc),
        )

    def mirror_exit(
        self, trader: ScoredTrader, trade: WalletTrade
    ) -> Optional[CopySignal]:
        """Create an exit signal from a trader's sell trade."""
        from datetime import datetime, timezone

        reasoning = (
            f"EXIT signal from {trader.pseudonym} (score={trader.score:.0f}) | "
            f"SELL {trade.outcome} — cumulative sell >=50% of entry | "
            f"Closing our mirrored position"
        )

        record_execution(
            strategy="copy_trader", side="SELL", status="placed", latency_s=0.0
        )
        order_placement_latency.labels(strategy="copy_trader", side="SELL").observe(0.0)
        return CopySignal(
            source_wallet=trader.user,
            source_trade=trade,
            our_side="SELL",
            our_outcome=trade.outcome,
            our_size=0.0,  # Will be set to full position size by executor
            market_price=trade.price,
            trader_score=trader.score,
            reasoning=reasoning,
            timestamp=datetime.now(timezone.utc),
        )
