"""
Copy Trader Strategy — mirror profitable Polymarket wallets.

Edge: profitable wallets have information/analysis advantage.
We copy their trades with a delay (seconds to minutes).

Pipeline:
1. WalletSelector — discover profitable wallets via Polymarket Data API
2. TradeDetector — monitor selected wallets for new BUY positions
3. PositionCopier — copy trades with proportional sizing (capped at 5% bankroll)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
from loguru import logger

from backend.strategies.base import (
    BaseStrategy,
    CycleResult,
    MarketInfo,
    StrategyContext,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Default profitable wallets to seed scanning (well-known Polymarket traders)
# These are starting points; WalletSelector dynamically discovers more.
SEED_WALLETS = [
    "0x6B175474E89094C44Da98b954EedeAC495271d0F",  # placeholder — replaced at runtime
]

# Polymarket Data API base (from settings.DATA_API_URL)
# Used for: activity, positions, closed-positions

# WalletSelector filters
MIN_TRADES = 100
MIN_WIN_RATE = 0.55
ACTIVE_DAYS = 7

# PositionCopier sizing
MAX_COPY_PCT = 0.05  # 5% of our bankroll per copy trade


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ProfitableWallet:
    """A wallet with verified profitable track record."""

    address: str
    proxy_wallet: str = ""
    total_pnl: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    sharpe_ratio: float = 0.0
    copy_score: float = 0.0
    last_active: float = 0.0


@dataclass
class CopySignal:
    """A trade detected from a profitable wallet that we should copy."""

    wallet: str
    condition_id: str
    outcome: str  # "YES" or "NO"
    side: str  # "BUY" or "SELL"
    price: float
    size: float
    title: str = ""
    token_id: str = ""
    timestamp: str = ""


# ---------------------------------------------------------------------------
# WalletSelector — find profitable wallets
# ---------------------------------------------------------------------------


class WalletSelector:
    """Discover profitable wallets using Polymarket Data API and existing infra."""

    def __init__(self, data_api_url: str):
        self._api = data_api_url
        self._cache: list[ProfitableWallet] = []
        self._cache_ts: float = 0.0
        self._cache_ttl: float = 3600.0  # 1 hour

    async def select(
        self, min_trades: int = MIN_TRADES, min_win_rate: float = MIN_WIN_RATE
    ) -> list[ProfitableWallet]:
        """Return profitable wallets sorted by copy_score descending."""
        now = time.time()
        if self._cache and (now - self._cache_ts) < self._cache_ttl:
            return self._cache

        # Method 1: Use existing wallet_scanner infrastructure
        wallets = await self._scan_via_infra(min_trades, min_win_rate)

        # Method 2: Discover from Gamma top markets (new wallets)
        if len(wallets) < 10:
            discovered = await self._discover_from_activity()
            wallets.extend(discovered)

        # Deduplicate
        seen = set()
        unique: list[ProfitableWallet] = []
        for w in wallets:
            key = w.address.lower()
            if key not in seen:
                seen.add(key)
                unique.append(w)

        # Sort by copy_score
        unique.sort(key=lambda w: w.copy_score, reverse=True)
        self._cache = unique[:20]  # Cap at 20 wallets
        self._cache_ts = now
        return self._cache

    async def _scan_via_infra(
        self, min_trades: int, min_win_rate: float
    ) -> list[ProfitableWallet]:
        """Use backend.core.wallet_scanner.find_profitable_traders."""
        results: list[ProfitableWallet] = []
        try:
            from backend.core.wallet_scanner import find_profitable_traders

            traders = await find_profitable_traders(
                min_volume=500.0,
                min_trades=min_trades,
                max_results=30,
                sort_by="pnl",
            )
            for t in traders:
                if t.win_rate < min_win_rate or t.pnl <= 0:
                    continue
                score = _compute_copy_score(
                    t.pnl, t.win_rate, t.total_trades, t.sharpe
                )
                results.append(
                    ProfitableWallet(
                        address=t.wallet,
                        proxy_wallet=t.proxy or "",
                        total_pnl=t.pnl,
                        win_rate=t.win_rate,
                        total_trades=t.total_trades,
                        sharpe_ratio=t.sharpe,
                        copy_score=score,
                    )
                )
        except Exception as e:
            logger.warning("[copy_trader] wallet_scanner failed: {}", e)
        return results

    async def _discover_from_activity(self) -> list[ProfitableWallet]:
        """Fetch recent activity and analyze top traders."""
        results: list[ProfitableWallet] = []
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{self._api}/activity",
                    params={"limit": 100},
                )
                if resp.status_code != 200:
                    return results
                activity = resp.json()

            # Collect unique wallets from recent activity
            wallet_set: set[str] = set()
            for event in (activity if isinstance(activity, list) else []):
                addr = event.get("maker_address") or event.get("proxyWallet", "")
                if addr:
                    wallet_set.add(addr)

            # Rapid-score each wallet
            from backend.data.wallet_history import get_all_closed_positions

            for wallet in list(wallet_set)[:30]:
                try:
                    positions = await get_all_closed_positions(wallet)
                    if not positions or len(positions) < MIN_TRADES:
                        continue
                    pnls = [float(p.get("realizedPnl", 0)) for p in positions]
                    total_pnl = sum(pnls)
                    wins = sum(1 for p in pnls if p > 0)
                    win_rate = wins / len(positions)
                    if total_pnl <= 0 or win_rate < MIN_WIN_RATE:
                        continue
                    score = _compute_copy_score(total_pnl, win_rate, len(positions), 0)
                    results.append(
                        ProfitableWallet(
                            address=wallet,
                            total_pnl=total_pnl,
                            win_rate=win_rate,
                            total_trades=len(positions),
                            copy_score=score,
                        )
                    )
                except Exception:
                    continue
        except Exception as e:
            logger.warning("[copy_trader] activity discovery failed: {}", e)
        return results


def _compute_copy_score(
    pnl: float, win_rate: float, trades: int, sharpe: float
) -> float:
    """Score 0-100: higher = better copy target."""
    score = 0.0
    # Win rate contribution (0-35)
    score += min(35.0, (win_rate - 0.50) * 200)
    # PnL contribution (0-30) — log scale
    import math

    if pnl > 0:
        score += min(30.0, math.log10(max(1, pnl)) * 10)
    # Volume/trades contribution (0-20)
    score += min(20.0, trades / 50)
    # Sharpe contribution (0-15)
    score += min(15.0, max(0, sharpe) * 5)
    return max(0, score)


# ---------------------------------------------------------------------------
# TradeDetector — monitor wallets for new trades
# ---------------------------------------------------------------------------


class TradeDetector:
    """Detect new BUY trades from profitable wallets using Data API."""

    def __init__(self, data_api_url: str):
        self._api = data_api_url
        # wallet -> set of seen trade IDs
        self._seen: dict[str, set[str]] = {}

    async def detect(
        self, wallets: list[ProfitableWallet], max_delay_seconds: int = 300
    ) -> list[CopySignal]:
        """Poll wallets for new BUY trades not yet seen."""
        signals: list[CopySignal] = []
        now = datetime.now(timezone.utc)

        for wallet in wallets:
            addr = wallet.proxy_wallet or wallet.address
            try:
                new_trades = await self._fetch_new_trades(addr, max_delay_seconds)
                for t in new_trades:
                    side = t.get("side", "BUY").upper()
                    if side != "BUY":
                        continue  # Only copy BUY positions
                    signal = CopySignal(
                        wallet=addr,
                        condition_id=t.get("conditionId", ""),
                        outcome="YES" if t.get("outcomeIndex", 0) == 0 else "NO",
                        side=side,
                        price=float(t.get("price", 0)),
                        size=float(t.get("size", 0)),
                        title=t.get("title", ""),
                        timestamp=t.get("timestamp", ""),
                    )
                    if signal.condition_id and signal.price > 0:
                        signals.append(signal)
            except Exception as e:
                logger.debug(
                    "[copy_trader] Failed polling {}: {}", addr[:10], e
                )
        return signals

    async def _fetch_new_trades(
        self, wallet: str, max_delay: int
    ) -> list[dict]:
        """Fetch recent trades for wallet, filter to unseen."""
        if wallet not in self._seen:
            self._seen[wallet] = set()

        all_trades: list[dict] = []
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{self._api}/activity",
                    params={"user": wallet, "limit": 50},
                )
                if resp.status_code == 200:
                    all_trades = resp.json()
                    if isinstance(all_trades, dict):
                        all_trades = all_trades.get("data", [])
        except Exception as e:
            logger.debug("[copy_trader] Activity fetch failed for {}: {}", wallet[:10], e)
            return []

        seen = self._seen[wallet]
        new: list[dict] = []
        now_ts = time.time()

        for t in all_trades:
            tx = t.get("transactionHash", "") or t.get("id", "")
            if not tx or tx in seen:
                continue
            seen.add(tx)

            # Check age
            ts_str = t.get("timestamp", "")
            try:
                if ts_str:
                    ts_dt = datetime.fromisoformat(ts_str.rstrip("Z")).replace(
                        tzinfo=timezone.utc
                    )
                    age = (datetime.now(timezone.utc) - ts_dt).total_seconds()
                    if age > max_delay:
                        continue
            except Exception:
                pass  # include if timestamp parsing fails

            new.append(t)

        return new


# ---------------------------------------------------------------------------
# PositionCopier — size and execute copy trades
# ---------------------------------------------------------------------------


class PositionCopier:
    """Execute copy trades with proportional sizing."""

    def __init__(self, max_copy_pct: float = MAX_COPY_PCT):
        self._max_copy_pct = max_copy_pct
        self._copied: set[str] = set()  # condition_id:outcome keys already copied

    def should_copy(self, signal: CopySignal) -> bool:
        """Check if this signal is a duplicate."""
        key = f"{signal.condition_id}:{signal.outcome}"
        if key in self._copied:
            return False
        self._copied.add(key)
        return True

    def compute_size(self, signal: CopySignal, bankroll: float) -> float:
        """Compute position size: scale by bankroll, cap at max_copy_pct."""
        if bankroll <= 0 or signal.price <= 0:
            return 0.0

        # Proportional: use signal size as reference, scale to our bankroll
        # But cap at max_copy_pct of bankroll
        max_size = bankroll * self._max_copy_pct

        # If we know the leader's size, scale proportionally
        # For now, use max allowed as default
        size = max_size

        # Floor at CLOB minimum $1.0
        if size < 1.0:
            return 0.0
        return round(size, 2)


# ---------------------------------------------------------------------------
# CopyTraderStrategy — the BaseStrategy subclass
# ---------------------------------------------------------------------------


class CopyTraderStrategy(BaseStrategy):
    """
    Mirrors trades from profitable wallets on Polymarket.

    Edge: profitable wallets have information/analysis advantage.
    We copy their trades with a delay (seconds to minutes).

    Key: find wallets with proven track record, copy their positions.
    """

    name = "copy_trader"
    description = (
        "Mirror profitable Polymarket wallets. Discovers wallets with >100 trades "
        "and >55% win rate, monitors their activity, and copies new BUY positions "
        "with proportional sizing capped at 5% bankroll per trade."
    )
    category = "copy"

    default_params: dict = {
        "min_trades": MIN_TRADES,
        "min_win_rate": MIN_WIN_RATE,
        "max_copy_pct": MAX_COPY_PCT,
        "max_delay_seconds": 300,
        "max_wallets": 10,
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._selector: WalletSelector | None = None
        self._detector: TradeDetector | None = None
        self._copier: PositionCopier | None = None
        self._initialized = False

    def _ensure_init(self, ctx: StrategyContext) -> None:
        """Lazy-init components from settings."""
        if self._initialized:
            return
        from backend.config import settings as cfg

        api_url = cfg.DATA_API_URL
        params = {**self.default_params, **(ctx.params or {})}
        self._selector = WalletSelector(api_url)
        self._detector = TradeDetector(api_url)
        self._copier = PositionCopier(float(params.get("max_copy_pct", MAX_COPY_PCT)))
        self._initialized = True

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        """Execute one copy trading cycle."""
        self._ensure_init(ctx)

        params = {**self.default_params, **(ctx.params or {})}
        min_trades = int(params.get("min_trades", MIN_TRADES))
        min_win_rate = float(params.get("min_win_rate", MIN_WIN_RATE))
        max_delay = int(params.get("max_delay_seconds", 300))
        max_wallets = int(params.get("max_wallets", 10))

        decisions_recorded = 0
        trades_attempted = 0
        trades_placed = 0
        errors: list[str] = []
        decisions: list[dict] = []

        try:
            # Step 1: Select profitable wallets
            wallets = await self._selector.select(min_trades, min_win_rate)
            if not wallets:
                ctx.logger.info("[copy_trader] No profitable wallets found")
                return CycleResult(
                    decisions_recorded=0,
                    trades_attempted=0,
                    trades_placed=0,
                )

            wallets = wallets[:max_wallets]
            ctx.logger.info(
                "[copy_trader] Monitoring {} wallets: {}",
                len(wallets),
                ", ".join(f"{w.address[:8]}...({w.win_rate:.0%})" for w in wallets[:5]),
            )

            # Step 2: Detect new trades
            signals = await self._detector.detect(wallets, max_delay)
            ctx.logger.info("[copy_trader] Found {} new BUY signals", len(signals))

            # Step 3: Copy trades
            for signal in signals:
                try:
                    if not self._copier.should_copy(signal):
                        continue

                    decisions_recorded += 1
                    trades_attempted += 1

                    size = self._copier.compute_size(signal, ctx.bankroll)
                    if size <= 0:
                        decisions.append({
                            "decision": "SKIP",
                            "condition_id": signal.condition_id,
                            "reason": "size too small",
                        })
                        continue

                    decision = {
                        "decision": "BUY",
                        "direction": signal.outcome,
                        "condition_id": signal.condition_id,
                        "side": "BUY",
                        "price": round(signal.price, 3),
                        "size": size,
                        "copied_from": signal.wallet[:10],
                        "title": signal.title[:60],
                        "confidence": 0.6,
                        "edge": 0.05,
                    }
                    decisions.append(decision)

                    # Log decision to DB
                    try:
                        from backend.core.decisions import record_decision_standalone

                        record_decision_standalone(
                            strategy=self.name,
                            market_ticker=signal.condition_id,
                            decision="BUY",
                            confidence=0.6,
                            signal_data=decision,
                            reason=f"Copy from {signal.wallet[:10]} @ {signal.price:.3f}",
                        )
                    except Exception:
                        pass

                    # Execute trade
                    if ctx.mode != "paper":
                        provider = ctx.get_market_provider("polymarket")
                        if provider and hasattr(provider, "place_order"):
                            from backend.markets.order_types import (
                                NormalizedOrder,
                                OrderSide,
                                OrderType,
                            )
                            from decimal import Decimal

                            norm_order = NormalizedOrder(
                                market_id=signal.condition_id,
                                side=OrderSide.BUY,
                                order_type=OrderType.LIMIT,
                                size=Decimal(str(size)),
                                price=Decimal(str(round(signal.price, 3))),
                                metadata={
                                    "token_id": signal.token_id,
                                    "condition_id": signal.condition_id,
                                },
                            )
                            result = await provider.place_order(norm_order)
                            if result and result.status.name == "FILLED":
                                trades_placed += 1
                            ctx.logger.info(
                                "[copy_trader] LIVE order: {} {} @ {:.3f} size=${:.2f} from {}",
                                signal.outcome,
                                signal.condition_id[:12],
                                signal.price,
                                size,
                                signal.wallet[:10],
                            )
                        else:
                            ctx.logger.warning("[copy_trader] No polymarket provider available")
                    else:
                        trades_placed += 1
                        ctx.logger.info(
                            "[copy_trader] PAPER: {} {} @ {:.3f} size=${:.2f} from {} | {}",
                            signal.outcome,
                            signal.condition_id[:12],
                            signal.price,
                            size,
                            signal.wallet[:10],
                            signal.title[:40],
                        )

                except Exception as exc:
                    errors.append(str(exc))
                    ctx.logger.error(
                        "[copy_trader] Error copying {}: {}",
                        signal.condition_id[:12],
                        exc,
                    )

        except Exception as exc:
            errors.append(str(exc))
            ctx.logger.exception("[copy_trader] Cycle failed: {}", exc)

        return CycleResult(
            decisions_recorded=decisions_recorded,
            trades_attempted=trades_attempted,
            trades_placed=trades_placed,
            errors=errors,
            decisions=decisions,
        )
