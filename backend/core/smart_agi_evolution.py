"""Smart AGI evolution — edge discovery, capital allocation, pattern mining.

Replaces the old parameter-mutation evolution with a data-driven approach:

1. EDGE DISCOVERY: Mine historical trade data to find profitable patterns
   - Which market categories have positive EV?
   - Which price ranges have positive EV?
   - Which time-of-day / day-of-week patterns correlate with profit?
   - Which signal characteristics (confidence, edge_pp) predict wins?

2. CAPITAL ALLOCATION: Dynamically allocate bankroll to strategies
   based on rolling Sharpe ratio and profit factor — not static weights.
   - Scale up proven winners (bond_scanner, longshot_bias)
   - Cut capital from strategies with negative EV
   - Kelly-optimal allocation across multiple strategies

3. AUTO-KILL WITHOUT MERCY: Strategies without edge are permanently
   disabled, not "aggressively evolved." 0% WR = broken edge detection,
   not suboptimal parameters.

4. PATTERN-BASED STRATEGY GENERATION: Instead of mutating parameters,
   discover what makes profitable strategies work and generate new
   strategies that exploit the same patterns in new market segments.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
from loguru import logger
from sqlalchemy import func, and_

from backend.config import settings
from backend.db.utils import get_db_session, utcnow


# ── Data structures ──────────────────────────────────────────────────────────

@dataclass
class StrategyEdgeProfile:
    """Quantified edge profile for a strategy — the truth, not hopes."""
    strategy: str
    total_trades: int
    win_rate: float
    total_pnl: float
    avg_win: float
    avg_loss: float
    profit_factor: float   # gross profit / gross loss (>1 = profitable)
    sharpe: float
    max_drawdown: float
    expected_value: float  # EV per trade in USD
    edge_confidence: float # 0-1, based on sample size
    has_edge: bool         # True if EV > 0 AND profit_factor > 1.2 AND sample >= 30


@dataclass
class MarketPattern:
    """A discovered profitable pattern from historical trade data."""
    pattern_type: str       # "category", "price_range", "time_window", "signal_char"
    pattern_value: str      # e.g. "crypto", "85-95c", "hour_14", "high_confidence"
    sample_size: int
    win_rate: float
    total_pnl: float
    profit_factor: float
    edge_pp: float          # observed edge in percentage points


@dataclass
class CapitalAllocation:
    """Recommended capital allocation across strategies."""
    strategy: str
    allocation_pct: float   # 0-1, fraction of bankroll
    kelly_fraction: float   # optimal Kelly fraction
    expected_return: float  # expected daily return at this allocation
    risk_contribution: float


# ── Edge Profiler ────────────────────────────────────────────────────────────

class EdgeProfiler:
    """Compute the true edge profile for each strategy from trade history.

    This is the foundation of smart AGI: know which strategies actually
    have edge before trying to improve them.
    """

    def profile_all(self, trading_mode: str = "paper") -> list[StrategyEdgeProfile]:
        """Profile all strategies that have settled trades."""
        from backend.models.database import Trade

        with get_db_session() as db:
            strategies = (
                db.query(Trade.strategy)
                .filter(
                    Trade.settled.is_(True),
                    Trade.pnl.isnot(None),
                    Trade.trading_mode == trading_mode,
                    Trade.strategy.isnot(None),
                )
                .distinct()
                .all()
            )

            profiles: list[StrategyEdgeProfile] = []
            for (strategy_name,) in strategies:
                if not strategy_name or strategy_name == "unknown":
                    continue
                profile = self._profile_strategy(strategy_name, trading_mode, db)
                if profile:
                    profiles.append(profile)

            profiles.sort(key=lambda p: p.expected_value, reverse=True)
            return profiles

    def _profile_strategy(
        self, strategy: str, trading_mode: str, db
    ) -> Optional[StrategyEdgeProfile]:
        """Compute edge profile for a single strategy."""
        from backend.models.database import Trade

        trades = (
            db.query(Trade)
            .filter(
                Trade.strategy == strategy,
                Trade.settled.is_(True),
                Trade.pnl.isnot(None),
                Trade.trading_mode == trading_mode,
            )
            .all()
        )

        total = len(trades)
        if total == 0:
            return None

        wins = [t for t in trades if t.pnl and t.pnl > 0]
        losses = [t for t in trades if t.pnl and t.pnl < 0]

        win_pnls = [t.pnl for t in wins]
        loss_pnls = [t.pnl for t in losses]

        total_pnl = sum(t.pnl or 0 for t in trades)
        avg_win = sum(win_pnls) / len(win_pnls) if win_pnls else 0.0
        avg_loss = sum(loss_pnls) / len(loss_pnls) if loss_pnls else 0.0

        gross_profit = sum(win_pnls)
        gross_loss = abs(sum(loss_pnls))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf') if gross_profit > 0 else 0.0

        win_rate = len(wins) / total
        ev_per_trade = total_pnl / total

        # Sharpe ratio (annualized approximation)
        pnls = [t.pnl or 0 for t in trades]
        if len(pnls) >= 2:
            mean_pnl = sum(pnls) / len(pnls)
            std_pnl = float(np.std(pnls))
            sharpe = (mean_pnl / std_pnl) * math.sqrt(365) if std_pnl > 0 else 0.0
        else:
            sharpe = 0.0

        # Max drawdown
        peak = 0.0
        equity = 0.0
        max_dd = 0.0
        for p in pnls:
            equity += p
            if equity > peak:
                peak = equity
            if peak > 0:
                dd = (peak - equity) / peak
                if dd > max_dd:
                    max_dd = dd

        # Edge confidence: based on sample size
        edge_confidence = min(1.0, total / 100.0)

        # Has edge: EV > 0, profit factor > 1.2, enough samples
        has_edge = (
            ev_per_trade > 0
            and profit_factor > 1.2
            and total >= 30
        )

        return StrategyEdgeProfile(
            strategy=strategy,
            total_trades=total,
            win_rate=win_rate,
            total_pnl=total_pnl,
            avg_win=avg_win,
            avg_loss=avg_loss,
            profit_factor=profit_factor,
            sharpe=sharpe,
            max_drawdown=max_dd,
            expected_value=ev_per_trade,
            edge_confidence=edge_confidence,
            has_edge=has_edge,
        )


# ── Pattern Miner ────────────────────────────────────────────────────────────

class PatternMiner:
    """Mine historical trade data for profitable patterns.

    Discovers which market characteristics correlate with profit —
    this is the data-driven edge discovery that the old AGI lacked.
    """

    def mine_all_patterns(self, trading_mode: str = "paper") -> list[MarketPattern]:
        """Mine all pattern types from historical trades."""
        patterns: list[MarketPattern] = []
        patterns.extend(self._mine_by_category(trading_mode))
        patterns.extend(self._mine_by_price_range(trading_mode))
        patterns.extend(self._mine_by_time_window(trading_mode))
        patterns.extend(self._mine_by_confidence(trading_mode))

        # Filter: only patterns with positive PnL and decent sample
        patterns = [
            p for p in patterns
            if p.total_pnl > 0 and p.sample_size >= 10 and p.win_rate > 0.5
        ]
        patterns.sort(key=lambda p: p.total_pnl, reverse=True)
        return patterns

    def _mine_by_category(self, trading_mode: str) -> list[MarketPattern]:
        """Find which market categories are profitable."""
        from backend.models.database import Trade

        with get_db_session() as db:
            rows = (
                db.query(
                    Trade.market_type,
                    func.count(Trade.id).label("total"),
                    func.sum(Trade.pnl).label("total_pnl"),
                )
                .filter(
                    Trade.settled.is_(True),
                    Trade.pnl.isnot(None),
                    Trade.trading_mode == trading_mode,
                    Trade.market_type.isnot(None),
                )
                .group_by(Trade.market_type)
                .all()
            )

        patterns: list[MarketPattern] = []
        for row in rows:
            if not row.market_type or row.total < 10:
                continue
            with get_db_session() as db2:
                wins = (
                    db2.query(func.count(Trade.id))
                    .filter(
                        Trade.market_type == row.market_type,
                        Trade.pnl > 0,
                        Trade.trading_mode == trading_mode,
                    )
                    .scalar() or 0
                )
            wr = wins / row.total if row.total > 0 else 0.0
            total_pnl = float(row.total_pnl or 0)
            patterns.append(MarketPattern(
                pattern_type="category",
                pattern_value=row.market_type,
                sample_size=row.total,
                win_rate=wr,
                total_pnl=total_pnl,
                profit_factor=0,
                edge_pp=abs(wr - 0.5) * 100,
            ))
        return patterns

    def _mine_by_price_range(self, trading_mode: str) -> list[MarketPattern]:
        """Find which entry price ranges are profitable."""
        from backend.models.database import Trade

        with get_db_session() as db:
            trades = (
                db.query(Trade.entry_price, Trade.pnl, Trade.result)
                .filter(
                    Trade.settled.is_(True),
                    Trade.pnl.isnot(None),
                    Trade.trading_mode == trading_mode,
                    Trade.entry_price.isnot(None),
                )
                .all()
            )

        buckets: dict[str, list] = {}
        for t in trades:
            if t.entry_price is None:
                continue
            bucket = self._price_bucket(t.entry_price)
            buckets.setdefault(bucket, []).append(t)

        patterns: list[MarketPattern] = []
        for bucket, bucket_trades in buckets.items():
            total = len(bucket_trades)
            if total < 10:
                continue
            wins = sum(1 for t in bucket_trades if t.pnl and t.pnl > 0)
            wr = wins / total
            total_pnl = sum(t.pnl or 0 for t in bucket_trades)
            patterns.append(MarketPattern(
                pattern_type="price_range",
                pattern_value=bucket,
                sample_size=total,
                win_rate=wr,
                total_pnl=total_pnl,
                profit_factor=0,
                edge_pp=abs(wr - 0.5) * 100,
            ))
        return patterns

    def _mine_by_time_window(self, trading_mode: str) -> list[MarketPattern]:
        """Find which hours/days correlate with profit."""
        from backend.models.database import Trade

        with get_db_session() as db:
            trades = (
                db.query(Trade.timestamp, Trade.pnl)
                .filter(
                    Trade.settled.is_(True),
                    Trade.pnl.isnot(None),
                    Trade.trading_mode == trading_mode,
                    Trade.timestamp.isnot(None),
                )
                .all()
            )

        hour_buckets: dict[str, list] = {}
        for t in trades:
            if t.timestamp is None or t.pnl is None:
                continue
            hour = t.timestamp.hour if hasattr(t.timestamp, 'hour') else None
            if hour is None:
                continue
            key = f"hour_{hour:02d}"
            hour_buckets.setdefault(key, []).append(t.pnl)

        patterns: list[MarketPattern] = []
        for key, pnls in hour_buckets.items():
            total = len(pnls)
            if total < 10:
                continue
            wins = sum(1 for p in pnls if p > 0)
            wr = wins / total
            total_pnl = sum(pnls)
            patterns.append(MarketPattern(
                pattern_type="time_window",
                pattern_value=key,
                sample_size=total,
                win_rate=wr,
                total_pnl=total_pnl,
                profit_factor=0,
                edge_pp=abs(wr - 0.5) * 100,
            ))
        return patterns

    def _mine_by_confidence(self, trading_mode: str) -> list[MarketPattern]:
        """Find which confidence levels correlate with profit."""
        from backend.models.database import Trade

        with get_db_session() as db:
            trades = (
                db.query(Trade.confidence, Trade.pnl, Trade.result)
                .filter(
                    Trade.settled.is_(True),
                    Trade.pnl.isnot(None),
                    Trade.trading_mode == trading_mode,
                    Trade.confidence.isnot(None),
                )
                .all()
            )

        buckets: dict[str, list] = {}
        for t in trades:
            if t.confidence is None:
                continue
            if t.confidence >= 0.9:
                key = "very_high_conf"
            elif t.confidence >= 0.7:
                key = "high_conf"
            elif t.confidence >= 0.5:
                key = "medium_conf"
            else:
                key = "low_conf"
            buckets.setdefault(key, []).append(t)

        patterns: list[MarketPattern] = []
        for key, bucket_trades in buckets.items():
            total = len(bucket_trades)
            if total < 10:
                continue
            wins = sum(1 for t in bucket_trades if t.pnl and t.pnl > 0)
            wr = wins / total
            total_pnl = sum(t.pnl or 0 for t in bucket_trades)
            patterns.append(MarketPattern(
                pattern_type="signal_char",
                pattern_value=key,
                sample_size=total,
                win_rate=wr,
                total_pnl=total_pnl,
                profit_factor=0,
                edge_pp=abs(wr - 0.5) * 100,
            ))
        return patterns

    @staticmethod
    def _price_bucket(price: float) -> str:
        if price < 0.05: return "0-5c"
        elif price < 0.10: return "5-10c"
        elif price < 0.20: return "10-20c"
        elif price < 0.40: return "20-40c"
        elif price < 0.60: return "40-60c"
        elif price < 0.80: return "60-80c"
        elif price < 0.90: return "80-90c"
        elif price < 0.95: return "90-95c"
        else: return "95c-1"


# ── Smart Capital Allocator ──────────────────────────────────────────────────

class SmartCapitalAllocator:
    """Dynamically allocate bankroll across strategies based on edge profiles.

    Uses fractional Kelly across multiple strategies — strategies with
    higher Sharpe get more capital, strategies with negative EV get zero.
    """

    def allocate(
        self, profiles: list[StrategyEdgeProfile], total_bankroll: float
    ) -> list[CapitalAllocation]:
        """Compute optimal capital allocation across strategies."""
        # Only allocate to strategies with edge
        edged = [p for p in profiles if p.has_edge]
        if not edged:
            logger.warning("[CapitalAllocator] No strategies with proven edge — holding cash")
            return []

        allocations: list[CapitalAllocation] = []

        # Compute Kelly fraction for each strategy
        # Kelly: f = (b*p - q) / b where b = avg_win/avg_loss, p = win_rate, q = 1-p
        kelly_fractions: dict[str, float] = {}
        for p in edged:
            if p.avg_loss == 0:
                # No losses — full Kelly (but cap at 25%)
                kelly = 0.25
            else:
                b = abs(p.avg_win / p.avg_loss) if p.avg_loss != 0 else 1.0
                win_prob = p.win_rate
                loss_prob = 1 - win_prob
                kelly = (b * win_prob - loss_prob) / b if b > 0 else 0
                kelly = max(0, min(0.25, kelly))  # fractional Kelly, cap at 25%

            # Scale by edge confidence (more trades = more confidence)
            kelly *= p.edge_confidence
            kelly_fractions[p.strategy] = kelly

        # Normalize so total allocation doesn't exceed 80% of bankroll (keep 20% cash)
        total_kelly = sum(kelly_fractions.values())
        max_allocation = 0.80
        if total_kelly > max_allocation:
            scale = max_allocation / total_kelly
            kelly_fractions = {k: v * scale for k, v in kelly_fractions.items()}

        for p in edged:
            kelly = kelly_fractions[p.strategy]
            allocation_pct = kelly
            expected_return = p.expected_value * (total_bankroll * allocation_pct / p.avg_win if p.avg_win > 0 else 0)
            risk_contribution = allocation_pct * p.max_drawdown

            allocations.append(CapitalAllocation(
                strategy=p.strategy,
                allocation_pct=allocation_pct,
                kelly_fraction=kelly,
                expected_return=expected_return,
                risk_contribution=risk_contribution,
            ))

        # Sort by allocation descending
        allocations.sort(key=lambda a: a.allocation_pct, reverse=True)

        logger.info(
            f"[CapitalAllocator] Allocated across {len(edged)} strategies: "
            + ", ".join(f"{a.strategy}={a.allocation_pct:.1%}" for a in allocations)
        )
        return allocations


# ── Smart AGI Evolution ──────────────────────────────────────────────────────

class SmartAGIEvolution:
    """The smart AGI evolution loop — replaces parameter mutation with
    edge-driven capital allocation and pattern-based discovery.

    Cycle:
    1. Profile all strategies (know the truth)
    2. Mine profitable patterns (discover edges)
    3. Allocate capital to proven winners (scale profit)
    4. Kill strategies without edge (stop bleeding)
    5. Report actionable insights (guide human/LLM strategy creation)
    """

    def __init__(self):
        self.profiler = EdgeProfiler()
        self.miner = PatternMiner()
        self.allocator = SmartCapitalAllocator()

    async def run_smart_cycle(self) -> dict:
        """Run one smart AGI evolution cycle. Returns actionable report."""
        report = {
            "timestamp": utcnow().isoformat(),
            "profiles": [],
            "patterns": [],
            "allocations": [],
            "killed": [],
            "actions": [],
        }

        # Stage 1: Profile all strategies
        try:
            profiles = self.profiler.profile_all(trading_mode="paper")
            report["profiles"] = [
                {
                    "strategy": p.strategy,
                    "trades": p.total_trades,
                    "win_rate": p.win_rate,
                    "total_pnl": p.total_pnl,
                    "profit_factor": p.profit_factor,
                    "sharpe": p.sharpe,
                    "ev_per_trade": p.expected_value,
                    "has_edge": p.has_edge,
                }
                for p in profiles
            ]
            edged = [p for p in profiles if p.has_edge]
            losing = [p for p in profiles if not p.has_edge and p.total_trades >= 30]

            logger.info(
                f"[SmartAGI] Profiles: {len(profiles)} total, "
                f"{len(edged)} with edge, {len(losing)} without edge"
            )
        except Exception as e:
            logger.error(f"[SmartAGI] Profile stage failed: {e}")
            return report

        # Stage 2: Mine profitable patterns
        try:
            patterns = self.miner.mine_all_patterns(trading_mode="paper")
            report["patterns"] = [
                {
                    "type": p.pattern_type,
                    "value": p.pattern_value,
                    "samples": p.sample_size,
                    "win_rate": p.win_rate,
                    "total_pnl": p.total_pnl,
                    "edge_pp": p.edge_pp,
                }
                for p in patterns[:20]  # top 20 patterns
            ]
            logger.info(f"[SmartAGI] Discovered {len(patterns)} profitable patterns")
        except Exception as e:
            logger.error(f"[SmartAGI] Pattern mining failed: {e}")

        # Stage 3: Allocate capital to proven winners
        try:
            bankroll = self._get_bankroll()
            allocations = self.allocator.allocate(profiles, bankroll)
            report["allocations"] = [
                {
                    "strategy": a.strategy,
                    "allocation_pct": a.allocation_pct,
                    "kelly_fraction": a.kelly_fraction,
                    "expected_return": a.expected_return,
                }
                for a in allocations
            ]

            # Apply allocations to strategy configs
            self._apply_allocations(allocations, bankroll)
            report["actions"].append(f"Allocated capital across {len(allocations)} strategies")
        except Exception as e:
            logger.error(f"[SmartAGI] Capital allocation failed: {e}")

        # Stage 4: Kill strategies without edge (no mercy)
        try:
            killed = self._kill_edgeless_strategies(losing)
            report["killed"] = killed
            if killed:
                report["actions"].append(f"Killed {len(killed)} edgeless strategies: {killed}")
                logger.info(f"[SmartAGI] Killed {len(killed)} edgeless strategies: {killed}")
        except Exception as e:
            logger.error(f"[SmartAGI] Kill stage failed: {e}")

        # Stage 5: Report actionable insights
        if edged:
            best = edged[0]
            report["actions"].append(
                f"Top strategy: {best.strategy} "
                f"(WR={best.win_rate:.1%}, PF={best.profit_factor:.2f}, "
                f"Sharpe={best.sharpe:.2f}, EV=${best.expected_value:.3f}/trade)"
            )
        if patterns:
            top_pattern = patterns[0]
            report["actions"].append(
                f"Top pattern: {top_pattern.pattern_type}={top_pattern.pattern_value} "
                f"(WR={top_pattern.win_rate:.1%}, PnL=${top_pattern.total_pnl:.2f}, "
                f"n={top_pattern.sample_size})"
            )

        logger.info(f"[SmartAGI] Cycle complete: {len(report['actions'])} actions")
        for action in report["actions"]:
            logger.info(f"[SmartAGI] → {action}")

        return report

    def _get_bankroll(self) -> float:
        """Get current live bankroll."""
        from backend.models.database import BotState
        try:
            with get_db_session() as db:
                state = db.query(BotState).filter(BotState.mode == "live").first()
                if state and state.bankroll is not None:
                    return float(state.bankroll)
        except Exception:
            pass
        return float(getattr(settings, "INITIAL_BANKROLL", 20.0))

    def _apply_allocations(self, allocations: list[CapitalAllocation], bankroll: float) -> None:
        """Apply capital allocations to strategy configs."""
        from backend.models.database import StrategyConfig

        with get_db_session() as db:
            for alloc in allocations:
                config = (
                    db.query(StrategyConfig)
                    .filter(StrategyConfig.strategy_name == alloc.strategy)
                    .first()
                )
                if config:
                    # Update bankroll_pct in params
                    import json
                    params = json.loads(config.params) if config.params else {}
                    params["bankroll_pct"] = round(alloc.allocation_pct, 4)
                    params["kelly_fraction"] = round(alloc.kelly_fraction, 4)
                    config.params = json.dumps(params)
                    config.updated_at = utcnow().isoformat()
            db.commit()

    def _kill_edgeless_strategies(self, losing: list[StrategyEdgeProfile]) -> list[str]:
        """Permanently disable strategies without edge. No mercy."""
        from backend.models.database import StrategyConfig

        killed: list[str] = []
        with get_db_session() as db:
            for p in losing:
                config = (
                    db.query(StrategyConfig)
                    .filter(StrategyConfig.strategy_name == p.strategy)
                    .first()
                )
                if config and config.enabled:
                    config.enabled = False
                    config.disabled_at = utcnow()
                    config.updated_at = utcnow().isoformat()
                    killed.append(p.strategy)
                    logger.warning(
                        f"[SmartAGI] KILLED '{p.strategy}' — "
                        f"EV=${p.expected_value:.3f}/trade, "
                        f"PF={p.profit_factor:.2f}, "
                        f"WR={p.win_rate:.1%} — NO EDGE"
                    )
            if killed:
                db.commit()
        return killed


# ── Module singleton ─────────────────────────────────────────────────────────

_smart_agi: SmartAGIEvolution | None = None


def get_smart_agi() -> SmartAGIEvolution:
    global _smart_agi
    if _smart_agi is None:
        _smart_agi = SmartAGIEvolution()
    return _smart_agi


def reset_smart_agi() -> None:
    global _smart_agi
    _smart_agi = None