"""Self-review module — attribution engine, postmortems, signal degradation detection.

Provides deterministic win-rate attribution by factor, LLM-assisted compound
postmortems for clustered losses, rolling-window signal degradation detection,
and agent diary integration via BigBrainClient.
"""

from loguru import logger
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.ai.llm_router import LLMRouter
from backend.clients.bigbrain import BigBrainClient
from backend.models.database import SessionLocal, Trade
from backend.ai.rejection_learner import generate_rejection_proposals
from backend.models.database import StrategyProposal, StrategyConfig
from backend.models.outcome_tables import StrategyOutcome
from json import json

# ── Configuration defaults ────────────────────────────────────────────────

# Edge-size buckets (upper-exclusive boundaries)
EDGE_BUCKETS = [
    ("tiny", 0.0, 0.02),
    ("small", 0.02, 0.05),
    ("medium", 0.05, 0.10),
    ("large", 0.10, 0.20),
    ("huge", 0.20, float("inf")),
]

# Confidence buckets
CONFIDENCE_BUCKETS = [
    ("low", 0.0, 0.4),
    ("medium", 0.4, 0.7),
    ("high", 0.7, 1.01),
]

# Degradation detection
RECENT_WINDOW_WEEKS = 3
DEGRADATION_THRESHOLD = 0.10  # 10 pp drop flags degradation
MIN_TRADES_BASELINE = 10
MIN_TRADES_RECENT = 5

# Postmortem clustering
POSTMORTEM_TIME_WINDOW_DAYS = 7
POSTMORTEM_MAX_CLUSTER_SIZE = 50  # cap trades sent to LLM per cluster


# ── Data classes ──────────────────────────────────────────────────────────


@dataclass
class WinRateBreakdown:
    """Win rates grouped by a single factor."""

    factor: str  # e.g. "strategy", "market_type", "edge_bucket", "confidence_bucket"
    groups: dict[str, dict[str, Any]] = field(default_factory=dict)
    # groups[key] = {"wins": int, "losses": int, "total": int, "win_rate": float}


@dataclass
class Postmortem:
    """Compound postmortem for a cluster of losing trades."""

    cluster_key: str  # e.g. "strategy=btc_momentum" or "week=2026-W14"
    trade_count: int
    total_pnl: float
    llm_analysis: str  # qualitative synthesis from LLM
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class DegradationAlert:
    """Alert for a signal/strategy whose win rate has degraded."""

    signal_key: str  # e.g. "strategy=crypto_oracle"
    factor: str
    baseline_win_rate: float
    recent_win_rate: float
    drop: float
    baseline_trades: int
    recent_trades: int
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ── Helpers ───────────────────────────────────────────────────────────────


def _bucket_edge(edge: Optional[float]) -> str:
    """Classify edge_at_entry into a named bucket."""
    if edge is None:
        return "unknown"
    for name, lo, hi in EDGE_BUCKETS:
        if lo <= abs(edge) < hi:
            return name
    return "unknown"


def _bucket_confidence(conf: Optional[float]) -> str:
    """Classify confidence into a named bucket."""
    if conf is None:
        return "unknown"
    for name, lo, hi in CONFIDENCE_BUCKETS:
        if lo <= conf < hi:
            return name
    return "unknown"


def _settled_trades(db: Session) -> list[Trade]:
    """Return all settled (non-pending) trades from the database."""
    return (
        db.query(Trade)
        .filter(Trade.settled.is_(True), Trade.result.in_(["win", "loss"]))
        .all()
    )


def _format_trade_summary(trade: Trade) -> str:
    """One-line summary of a trade for LLM context."""
    ts = trade.timestamp.strftime("%Y-%m-%d %H:%M") if trade.timestamp else "?"
    return (
        f"[{ts}] {trade.strategy or '?'} | {trade.market_type or '?'} | "
        f"dir={trade.direction} edge={(trade.edge_at_entry or 0):.3f} "
        f"conf={trade.confidence or 0:.2f} pnl={trade.pnl or 0:.2f} → {trade.result}"
    )


# ── Main class ────────────────────────────────────────────────────────────


class SelfReview:
    """Attribution engine & self-review module.

    Orchestrates:
      1. calculate_win_rates()  — deterministic factor attribution
      2. generate_postmortems() — LLM-assisted cluster analysis
      3. detect_degradation()   — rolling-window signal decay detection
      4. run_review_cycle()     — master runner with diary integration
    """

    def __init__(
        self,
        db: Optional[Session] = None,
        llm: Optional[LLMRouter] = None,
        brain: Optional[BigBrainClient] = None,
    ):
        self._db = db
        self._llm = llm
        self._brain = brain

    def _get_db(self) -> Session:
        if self._db is not None:
            return self._db
        return SessionLocal()

    def _should_close_db(self) -> bool:
        return self._db is None

    def _get_llm(self) -> LLMRouter:
        if self._llm is not None:
            return self._llm
        return LLMRouter()

    def _get_brain(self) -> BigBrainClient:
        if self._brain is not None:
            return self._brain
        return BigBrainClient()

    # ── T20: Win rate attribution ─────────────────────────────────────

    def calculate_win_rates(
        self, db: Optional[Session] = None
    ) -> list[WinRateBreakdown]:
        """Deterministically calculate win rates grouped by four factors.

        Factors: strategy, market_type, edge_bucket, confidence_bucket.
        Only considers settled trades with result in ("win", "loss").
        Returns a list of WinRateBreakdown objects.
        """
        session = db or self._get_db()
        close = db is None and self._should_close_db()
        try:
            trades = _settled_trades(session)
            return self._compute_breakdowns(trades)
        finally:
            if close:
                session.close()

    def _compute_breakdowns(self, trades: list[Trade]) -> list[WinRateBreakdown]:
        """Pure computation — group trades by four factors and tally results."""
        factors = {
            "strategy": lambda t: t.strategy or "unknown",
            "market_type": lambda t: t.market_type or "unknown",
            "edge_bucket": lambda t: _bucket_edge(t.edge_at_entry),
            "confidence_bucket": lambda t: _bucket_confidence(t.confidence),
        }
        breakdowns = []
        for factor_name, key_fn in factors.items():
            groups: dict[str, dict] = defaultdict(
                lambda: {"wins": 0, "losses": 0, "total": 0, "win_rate": 0.0}
            )
            for trade in trades:
                k = key_fn(trade)
                g = groups[k]
                g["total"] += 1
                if trade.result == "win":
                    g["wins"] += 1
                else:
                    g["losses"] += 1

            for g in groups.values():
                if g["total"] > 0:
                    g["win_rate"] = g["wins"] / g["total"]

            breakdowns.append(WinRateBreakdown(factor=factor_name, groups=dict(groups)))
        return breakdowns

    # ── T21: Compound postmortems ─────────────────────────────────────

    async def generate_postmortems(
        self,
        db: Optional[Session] = None,
        window_days: int = POSTMORTEM_TIME_WINDOW_DAYS,
    ) -> list[Postmortem]:
        """Generate compound postmortems for clusters of losing trades.

        Clusters losses by strategy, then asks the LLM for a qualitative
        synthesis of common traits / root causes.
        """
        session = db or self._get_db()
        close = db is None and self._should_close_db()
        try:
            trades = _settled_trades(session)
            losing_trades = [t for t in trades if t.result == "loss"]
            if not losing_trades:
                return []

            clusters: dict[str, list] = defaultdict(list)
            for t in losing_trades:
                key = t.strategy or "unknown"
                clusters[key].append(t)

            postmortems: list[Postmortem] = []
            llm = self._get_llm()

            for strategy_key, cluster_trades in clusters.items():
                if not cluster_trades:
                    continue

                total_pnl = sum(t.pnl or 0.0 for t in cluster_trades)

                sample = cluster_trades[:POSTMORTEM_MAX_CLUSTER_SIZE]
                trade_summaries = "\n".join(_format_trade_summary(t) for t in sample)

                prompt = (
                    f"You are a quantitative trading analyst. Analyze these {len(sample)} "
                    f"losing trades from strategy '{strategy_key}' and identify common "
                    f"root causes, patterns, and actionable recommendations.\n\n"
                    f"LOSING TRADES:\n{trade_summaries}\n\n"
                    f"Total cluster PnL: {total_pnl:.2f}\n\n"
                    f"Provide a concise postmortem (3-5 bullet points) covering:\n"
                    f"1. Common patterns in these losses\n"
                    f"2. Market conditions that led to failures\n"
                    f"3. Actionable recommendations to reduce future losses"
                )

                try:
                    analysis = await llm.complete(
                        prompt=prompt,
                        system="You are a concise quantitative trading analyst.",
                        role="default",
                    )
                except Exception as e:
                    logger.warning(
                        "LLM postmortem failed for cluster %s: %s", strategy_key, e
                    )
                    analysis = f"LLM analysis unavailable: {e}"

                postmortems.append(
                    Postmortem(
                        cluster_key=f"strategy={strategy_key}",
                        trade_count=len(cluster_trades),
                        total_pnl=total_pnl,
                        llm_analysis=analysis,
                    )
                )

            return postmortems
        finally:
            if close:
                session.close()

    # ── T22: Signal degradation detection ─────────────────────────────

    def detect_degradation(
        self,
        db: Optional[Session] = None,
        recent_weeks: int = RECENT_WINDOW_WEEKS,
        threshold: float = DEGRADATION_THRESHOLD,
        min_baseline: int = MIN_TRADES_BASELINE,
        min_recent: int = MIN_TRADES_RECENT,
    ) -> list[DegradationAlert]:
        """Detect signals/strategies whose win rate has degraded.

        Compares a recent rolling window (default 3 weeks) against the
        historical baseline. Flags any factor group where the win rate
        dropped by more than `threshold` (default 10 pp).

        Requires minimum trade counts in both windows to avoid false positives.
        """
        session = db or self._get_db()
        close = db is None and self._should_close_db()
        try:
            trades = _settled_trades(session)
            if not trades:
                return []

            now = datetime.now(timezone.utc)
            cutoff = now - timedelta(weeks=recent_weeks)

            recent_trades = []
            baseline_trades = []
            for t in trades:
                ts = t.timestamp
                if ts and ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts and ts >= cutoff:
                    recent_trades.append(t)
                else:
                    baseline_trades.append(t)

            if not recent_trades or not baseline_trades:
                return []

            alerts: list[DegradationAlert] = []

            factors = {
                "strategy": lambda t: t.strategy or "unknown",
                "market_type": lambda t: t.market_type or "unknown",
                "edge_bucket": lambda t: _bucket_edge(t.edge_at_entry),
                "confidence_bucket": lambda t: _bucket_confidence(t.confidence),
            }

            for factor_name, key_fn in factors.items():
                baseline_stats: dict[str, dict] = defaultdict(
                    lambda: {"wins": 0, "total": 0}
                )
                for t in baseline_trades:
                    k = key_fn(t)
                    baseline_stats[k]["total"] += 1
                    if t.result == "win":
                        baseline_stats[k]["wins"] += 1

                recent_stats: dict[str, dict] = defaultdict(
                    lambda: {"wins": 0, "total": 0}
                )
                for t in recent_trades:
                    k = key_fn(t)
                    recent_stats[k]["total"] += 1
                    if t.result == "win":
                        recent_stats[k]["wins"] += 1

                # Compare
                for key in set(baseline_stats.keys()) | set(recent_stats.keys()):
                    b = baseline_stats.get(key, {"wins": 0, "total": 0})
                    r = recent_stats.get(key, {"wins": 0, "total": 0})

                    if b["total"] < min_baseline or r["total"] < min_recent:
                        continue

                    baseline_wr = b["wins"] / b["total"]
                    recent_wr = r["wins"] / r["total"]
                    drop = baseline_wr - recent_wr

                    if drop >= threshold:
                        alerts.append(
                            DegradationAlert(
                                signal_key=f"{factor_name}={key}",
                                factor=factor_name,
                                baseline_win_rate=baseline_wr,
                                recent_win_rate=recent_wr,
                                drop=drop,
                                baseline_trades=b["total"],
                                recent_trades=r["total"],
                            )
                        )

            return alerts
        finally:
            if close:
                session.close()

    # ── T23: Master review cycle with diary integration ───────────────

    async def run_review_cycle(self, db: Optional[Session] = None) -> dict:
        """Master review cycle — runs all analyses and posts to diary.

        Returns a summary dict with keys: win_rates, postmortems,
        degradation_alerts, diary_posted.
        """
        session = db or self._get_db()
        close = db is None and self._should_close_db()
        try:
            # 1. Win rate attribution (deterministic)
            win_rates = self.calculate_win_rates(db=session)

            # 2. Postmortems (LLM-assisted)
            postmortems = await self.generate_postmortems(db=session)

            # 3. Degradation detection
            degradation_alerts = self.detect_degradation(db=session)

            # 4. Send alerts for critical issues
            brain = self._get_brain()
            try:
                await self._send_critical_alerts(postmortems, degradation_alerts, brain)
            except Exception as e:
                logger.debug("Failed to send critical alerts: %s", e)

            # 5. Agent diary integration — do NOT fail the cycle if this errors
            diary_posted = False
            try:
                diary_posted = await self._post_diary(
                    win_rates, postmortems, degradation_alerts
                )
            except Exception as e:
                logger.warning("Diary posting failed (non-fatal): %s", e)

            # 6. Auto-generate proposals for bleeding strategies
            proposals_generated = 0
            try:
                proposals_generated = self._generate_proposals_for_bleeders(db=session)
            except Exception as e:
                logger.debug("Proposal generation skipped: %s", e)

            # 7. Rejection learning — feed blocked/rejected patterns back into proposals
            rejection_proposals = []
            try:

                rejection_proposals = generate_rejection_proposals()
            except Exception as e:
                logger.debug("Rejection learning skipped: %s", e)

            return {
                "win_rates": win_rates,
                "postmortems": postmortems,
                "degradation_alerts": degradation_alerts,
                "diary_posted": diary_posted,
                "proposals_generated": proposals_generated,
                "rejection_proposals": rejection_proposals,
            }
        finally:
            if close:
                session.close()

    def _generate_proposals_for_bleeders(self, db=None):
        session = db or self._get_db()
        close = db is None
        try:

            strategies = session.query(StrategyOutcome.strategy).distinct().all()
            generated = 0
            for (strategy_name,) in strategies:
                if strategy_name in ("unknown", "?"):
                    continue
                outcomes = (
                    session.query(StrategyOutcome)
                    .filter(StrategyOutcome.strategy == strategy_name)
                    .order_by(StrategyOutcome.settled_at.desc())
                    .limit(20)
                    .all()
                )
                if len(outcomes) < 10:
                    continue
                wins = sum(1 for o in outcomes if o.result == "win")
                win_rate = wins / len(outcomes)
                if win_rate < 0.40:
                    cfg = (
                        session.query(StrategyConfig)
                        .filter(StrategyConfig.strategy_name == strategy_name)
                        .first()
                    )
                    current_params = (cfg.params if cfg and cfg.params else None) or {
                        "kelly_fraction": 0.2,
                        "min_edge": 0.05,
                        "confidence_threshold": 0.5,
                    }
                    if isinstance(current_params, str):
                        try:

                            current_params = json.loads(current_params)
                        except Exception:
                            logger.exception("Failed to parse strategy params JSON")
                            current_params = {
                                "kelly_fraction": 0.2,
                                "min_edge": 0.05,
                                "confidence_threshold": 0.5,
                            }
                    proposed = {}
                    for k, v in current_params.items():
                        if isinstance(v, (int, float)) and not isinstance(v, bool):
                            deviation = 0.15
                            proposed[k] = round(
                                v
                                * (1 + deviation if win_rate < 0.5 else 1 - deviation),
                                4,
                            )
                    if proposed:
                        proposal = StrategyProposal(
                            strategy_name=strategy_name,
                            change_details=proposed,
                            expected_impact=f"Win rate {win_rate:.1%} over last {len(outcomes)} trades",
                            admin_decision="pending",
                            status="pending",
                            auto_promotable=True,
                            proposed_params=proposed,
                        )
                        session.add(proposal)
                        generated += 1
            if generated:
                session.commit()
                logger.info(
                    f"Self-review: generated {generated} auto-proposals for bleeders"
                )
        except Exception as e:
            logger.warning(f"Self-review proposal generation failed: {e}")
            if close:
                try:
                    session.rollback()
                except Exception as e:
                    logger.warning(f"self-review rollback failed: {e}")
        finally:
            if close:
                session.close()
        return generated

    async def _send_critical_alerts(
        self,
        postmortems: list[Postmortem],
        degradation_alerts: list[DegradationAlert],
        brain: BigBrainClient,
    ) -> None:
        """Send alerts for critical issues: postmortems and degradation."""
        if postmortems:
            for pm in postmortems:
                msg = (
                    f"⚠️ POSTMORTEM: {pm.cluster_key} - {pm.trade_count} trades, "
                    f"PnL={pm.total_pnl:.2f}. Key insight: {pm.llm_analysis[:100]}"
                )
                try:
                    await brain.send_alert(msg, level="warning")
                except Exception as e:
                    logger.debug("Failed to send postmortem alert: %s", e)

        if degradation_alerts:
            for alert in degradation_alerts:
                msg = (
                    f"📉 DEGRADATION: {alert.signal_key} - "
                    f"win rate {alert.baseline_win_rate:.1%} → {alert.recent_win_rate:.1%} "
                    f"(dropped {alert.drop:.1%})"
                )
                try:
                    await brain.send_alert(msg, level="warning")
                except Exception as e:
                    logger.debug("Failed to send degradation alert: %s", e)

    async def _post_diary(
        self,
        win_rates: list[WinRateBreakdown],
        postmortems: list[Postmortem],
        alerts: list[DegradationAlert],
    ) -> bool:
        """Format and post review results to the agent diary."""
        brain = self._get_brain()

        lines = ["## PolyEdge Self-Review Report\n"]

        # Win rate summary
        lines.append("### Win Rates by Factor")
        for br in win_rates:
            lines.append(f"\n**{br.factor}**:")
            for key, stats in br.groups.items():
                wr_pct = stats["win_rate"] * 100
                lines.append(
                    f"  - {key}: {wr_pct:.1f}% "
                    f"({stats['wins']}W/{stats['losses']}L, n={stats['total']})"
                )

        # Postmortems
        if postmortems:
            lines.append("\n### Postmortems")
            for pm in postmortems:
                lines.append(
                    f"\n**{pm.cluster_key}** ({pm.trade_count} trades, "
                    f"PnL={pm.total_pnl:.2f}):"
                )
                lines.append(pm.llm_analysis)

        # Degradation alerts
        if alerts:
            lines.append("\n### ⚠ Degradation Alerts")
            for a in alerts:
                lines.append(
                    f"  - **{a.signal_key}**: {a.baseline_win_rate:.1%} → "
                    f"{a.recent_win_rate:.1%} (dropped {a.drop:.1%}, "
                    f"baseline={a.baseline_trades}, recent={a.recent_trades})"
                )

        entry = "\n".join(lines)
        result = await brain.write_diary(entry=entry, topic="self-review")
        return result.get("success", False) if isinstance(result, dict) else False
