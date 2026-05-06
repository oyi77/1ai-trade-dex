"""Strategy ranker — rank strategies by risk-adjusted return, auto-allocate bankroll."""

import logging
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import func, case

from backend.config import settings

logger = logging.getLogger("trading_bot.ranker")


@dataclass
class RankedStrategy:
    """A strategy with its computed performance metrics."""
    name: str
    total_trades: int
    winning_trades: int
    win_rate: float
    total_pnl: float
    sharpe_ratio: float
    sortino_ratio: float
    profit_factor: float
    max_drawdown: float
    avg_return: float
    rank_score: float  # composite score for ranking


class StrategyRanker:
    """Rank strategies and auto-allocate bankroll based on performance."""

    def rank_all(
        self,
        db: Session,
        lookback_days: int = 30,
        min_trades: int = 5,
    ) -> list[RankedStrategy]:
        """Rank all strategies by risk-adjusted return over lookback period."""
        from backend.models.database import Trade

        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

        # Get all strategies with settled trades in the lookback period
        strategies = (
            db.query(Trade.strategy)
            .filter(
                Trade.settled.is_(True),
                Trade.result.in_(("win", "loss")),
                Trade.timestamp >= cutoff,
                Trade.strategy != None,
            )
            .distinct()
            .all()
        )

        ranked = []
        for (strategy_name,) in strategies:
            if not strategy_name:
                continue

            trades = (
                db.query(Trade)
                .filter(
                    Trade.strategy == strategy_name,
                    Trade.settled.is_(True),
                    Trade.result.in_(("win", "loss")),
                    Trade.timestamp >= cutoff,
                )
                .all()
            )

            if len(trades) < min_trades:
                continue

            wins = [t for t in trades if t.result == "win"]
            losses = [t for t in trades if t.result == "loss"]

            total_pnl = sum(t.pnl or 0 for t in trades)
            win_rate = len(wins) / len(trades) if trades else 0.0

            # Compute returns (pnl / size)
            returns = [
                (t.pnl or 0) / t.size
                for t in trades
                if t.size and t.size > 0
            ]

            avg_return = statistics.mean(returns) if returns else 0.0

            # Sharpe ratio
            sharpe = 0.0
            if len(returns) > 1:
                std = statistics.stdev(returns)
                if std > 0:
                    sharpe = (avg_return / std) * (len(returns) ** 0.5)

            # Sortino ratio
            sortino = 0.0
            downside = [r for r in returns if r < 0]
            if len(downside) > 1 and avg_return != 0:
                down_std = statistics.stdev(downside)
                if down_std > 0:
                    sortino = (avg_return / down_std) * (len(returns) ** 0.5)

            # Profit factor
            gross_wins = sum(t.pnl for t in wins if t.pnl)
            gross_losses = abs(sum(t.pnl for t in losses if t.pnl))
            pf = gross_wins / gross_losses if gross_losses > 0 else (
                float('inf') if gross_wins > 0 else 0.0
            )

            # Max drawdown from cumulative PnL
            max_dd = 0.0
            cumulative = 0.0
            peak = 0.0
            for t in sorted(trades, key=lambda x: x.timestamp or datetime.min):
                cumulative += t.pnl or 0
                if cumulative > peak:
                    peak = cumulative
                dd = (peak - cumulative) / max(peak, 1.0) if peak > 0 else 0.0
                if dd > max_dd:
                    max_dd = dd

            # Composite rank score: Sharpe weighted by trade count confidence
            confidence_weight = min(1.0, len(trades) / 30.0)
            rank_score = sharpe * confidence_weight

            ranked.append(RankedStrategy(
                name=strategy_name,
                total_trades=len(trades),
                winning_trades=len(wins),
                win_rate=round(win_rate, 4),
                total_pnl=round(total_pnl, 2),
                sharpe_ratio=round(sharpe, 4),
                sortino_ratio=round(sortino, 4),
                profit_factor=round(min(pf, 999.0), 4),
                max_drawdown=round(max_dd, 4),
                avg_return=round(avg_return, 4),
                rank_score=round(rank_score, 4),
            ))

        ranked.sort(key=lambda r: r.rank_score, reverse=True)
        return ranked

    RISK_TIER_MAX_PCT = {
        "safe": 0.50,
        "conservative": 0.30,
        "moderate": 0.20,
        "aggressive": 0.10,
        "extreme": 0.05,
        "crazy": 0.01,
    }

    def auto_allocate(
        self,
        db: Session,
        bankroll: float,
        lookback_days: int = 30,
    ) -> dict[str, float]:
        """Allocate bankroll across strategies proportional to risk-adjusted return.

        Returns dict of {strategy_name: allocation_dollars}.
        Max 50% to any single strategy. Caps reduced by risk_tier.
        Excess from caps is redistributed.
        """
        from backend.models.database import StrategyConfig

        ranked = self.rank_all(db, lookback_days)

        tier_map = {}
        for cfg in db.query(StrategyConfig).all():
            tier_map[cfg.strategy_name] = getattr(cfg, "risk_tier", None) or "moderate"

        positive = [r for r in ranked if r.rank_score > 0]
        if not positive:
            if ranked:
                per_strategy = bankroll / len(ranked)
                return {r.name: round(per_strategy, 2) for r in ranked}
            return {}

        total_score = sum(r.rank_score for r in positive)
        allocations = {}
        allocated = 0.0

        for r in positive:
            tier = tier_map.get(r.name, "moderate")
            cap_pct = self.RISK_TIER_MAX_PCT.get(tier, 0.20)
            cap = bankroll * cap_pct
            raw_alloc = (r.rank_score / total_score) * bankroll
            capped = min(raw_alloc, cap)
            allocations[r.name] = round(capped, 2)
            allocated += capped

        # Redistribute excess from capped strategies to uncapped ones
        if allocated < bankroll:
            uncapped = [r for r in positive if allocations[r.name] < bankroll * self.RISK_TIER_MAX_PCT.get(tier_map.get(r.name, "moderate"), 0.20)]
            if uncapped:
                remaining = bankroll - allocated
                uncapped_score = sum(r.rank_score for r in uncapped)
                if uncapped_score > 0:
                    for r in uncapped:
                        tier = tier_map.get(r.name, "moderate")
                        cap = bankroll * self.RISK_TIER_MAX_PCT.get(tier, 0.20)
                        extra = (r.rank_score / uncapped_score) * remaining
                        allocations[r.name] = round(
                            min(allocations[r.name] + extra, cap), 2
                        )

        return allocations

    def disable_underperformers(
        self,
        db: Session,
        min_sharpe: float = 0.0,
        min_trades: int = 30,
        lookback_days: int = 30,
        trading_mode: Optional[str] = None,
    ) -> list[str]:
        """Disable strategies with Sharpe below threshold after sufficient trades.

        Returns list of disabled strategy names.
        """
        from backend.models.database import StrategyConfig

        ranked = self.rank_all(db, lookback_days, min_trades=min_trades)
        disabled = []

        for r in ranked:
            if r.sharpe_ratio < min_sharpe and r.total_trades >= min_trades:
                config = (
                    db.query(StrategyConfig)
                    .filter(StrategyConfig.strategy_name == r.name)
                    .first()
                )
                if config and config.enabled:
                    config.enabled = False
                    disabled.append(r.name)
                    logger.warning(
                        f"Auto-disabled {r.name}: Sharpe={r.sharpe_ratio:.2f} < {min_sharpe} "
                        f"over {r.total_trades} trades"
                    )

        if disabled:
            db.commit()

        return disabled


async def strategy_ranking_job() -> None:
    """Scheduled job: rank strategies and log results."""
    from backend.models.database import SessionLocal

    db = SessionLocal()
    try:
        ranker = StrategyRanker()
        ranked = ranker.rank_all(db, lookback_days=30, min_trades=5)

        if ranked:
            logger.info("=== Strategy Rankings ===")
            for i, r in enumerate(ranked, 1):
                logger.info(
                    f"  #{i} {r.name}: Sharpe={r.sharpe_ratio:.2f}, "
                    f"WR={r.win_rate:.0%}, PnL=${r.total_pnl:+.2f}, "
                    f"PF={r.profit_factor:.1f}, trades={r.total_trades}"
                )

            # Auto-disable underperformers with enough data
            all_disabled = []
            for mode in settings.active_modes_set:
                disabled = ranker.disable_underperformers(db, min_sharpe=0.0, min_trades=30, trading_mode=mode)
                if disabled:
                    all_disabled.extend(disabled)
            if all_disabled:
                logger.info(f"Auto-disabled underperformers: {all_disabled}")
        else:
            logger.info("No strategies with enough data for ranking")

    except Exception as e:
        logger.error(f"Strategy ranking job failed: {e}")
    finally:
        db.close()


# Module-level singleton
strategy_ranker = StrategyRanker()
