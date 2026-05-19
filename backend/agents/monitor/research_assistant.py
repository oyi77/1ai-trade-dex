"""
ResearchAssistant — Autonomous research & self-improvement suggestion engine.

Analyzes strategy performance data to generate actionable suggestions:
1. Strategy tuning (parameter adjustments)
2. Market opportunities (new categories to explore)
3. Risk adjustments (circuit breaker tuning)
4. Copy trade targets (new wallets to follow)
5. Backtest ideas (new strategy directions)

Runs periodically (every 4h) as part of the monitor cycle.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional, Dict, List

from loguru import logger

from backend.config import settings
from backend.agents.monitor.strategy_performance import StrategyReport


@dataclass
class ResearchSuggestion:
    """A single research/improvement suggestion."""

    category: str = ""  # strategy_tuning | market_opportunity | risk_adjustment | copy_target | backtest_idea
    title: str = ""
    description: str = ""
    priority: str = "medium"  # high | medium | low
    expected_impact: str = ""  # What improvement is expected
    implementation_complexity: str = "medium"  # easy | medium | hard
    data_supporting: str = ""  # What data supports this suggestion

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ResearchReport:
    """Complete research report from one cycle."""

    timestamp: str = ""
    suggestions: List[dict] = field(default_factory=list)
    anomalies_detected: List[str] = field(default_factory=list)
    market_observations: List[str] = field(default_factory=list)
    performance_trends: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class ResearchAssistant:
    """
    Analyzes strategy performance and generates research suggestions.

    This is a deterministic rule-based engine (no LLM dependency).
    Uses hard data from the trading database to generate actionable insights.
    """

    def __init__(self):
        self._last_research_time: float = 0.0
        self._cycle_count: int = 0

    async def generate_suggestions(
        self,
        account_summary: Dict[str, dict],
        strategy_reports: List[StrategyReport],
    ) -> ResearchReport:
        """
        Generate research suggestions based on current performance data.

        Args:
            account_summary: Dict of mode -> account_summary dict
            strategy_reports: List of StrategyReport objects

        Returns:
            ResearchReport with suggestions, anomalies, and observations
        """
        self._cycle_count += 1
        report = ResearchReport(
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        # ── Phase 1: Strategy Tuning Suggestions ──
        for sr in strategy_reports:
            tuning = self._analyze_strategy_for_tuning(sr)
            if tuning:
                report.suggestions.append(tuning.to_dict())

        # ── Phase 2: Risk Adjustment Suggestions ──
        risk_suggestions = self._analyze_risk(account_summary, strategy_reports)
        for s in risk_suggestions:
            report.suggestions.append(s.to_dict())

        # ── Phase 3: Anomaly Detection ──
        for sr in strategy_reports:
            anomalies = self._detect_anomalous_patterns(sr)
            report.anomalies_detected.extend(anomalies)

        # ── Phase 4: Performance Trends ──
        trends = self._extract_trends(strategy_reports)
        report.performance_trends = trends

        # ── Phase 5: Market Observations ──
        observations = self._market_observations(strategy_reports)
        report.market_observations = observations

        logger.info(
            f"[ResearchAssistant] Cycle {self._cycle_count}: "
            f"{len(report.suggestions)} suggestions, "
            f"{len(report.anomalies_detected)} anomalies"
        )

        return report

    # -----------------------------------------------------------------------
    # Strategy Tuning
    # -----------------------------------------------------------------------

    def _analyze_strategy_for_tuning(
        self, sr: StrategyReport
    ) -> Optional[ResearchSuggestion]:
        """Generate tuning suggestions for a single strategy."""
        if sr.total_trades < 5:
            return None  # Not enough data

        # ── Low WR but good PF (wins are big, losses small) → increase sizing ──
        if sr.win_rate < 0.40 and sr.profit_factor > 1.2:
            return ResearchSuggestion(
                category="strategy_tuning",
                title=f"📈 {sr.name}: Increase position size",
                description=(
                    f"Win rate is low ({sr.win_rate:.1%}) but profit factor is solid "
                    f"({sr.profit_factor:.2f}). This means wins are big even though "
                    f"they're less frequent. Try increasing position size by 25-50% "
                    f"to capture more value."
                ),
                priority="medium",
                expected_impact=f"+${abs(sr.avg_win) * 0.25:.2f} per winning trade avg",
                implementation_complexity="easy",
                data_supporting=(
                    f"WR={sr.win_rate:.1%}, PF={sr.profit_factor:.2f}, "
                    f"AvgWin=${sr.avg_win:.2f}, AvgLoss=${sr.avg_loss:.2f}"
                ),
            )

        # ── WR dropped recently → pause & review ──
        if (
            sr.recent_win_rate is not None
            and sr.historical_win_rate is not None
            and sr.recent_win_rate < sr.historical_win_rate - 0.15
        ):
            return ResearchSuggestion(
                category="strategy_tuning",
                title=f"⚠️ {sr.name}: WR degradation detected",
                description=(
                    f"Recent win rate ({sr.recent_win_rate:.1%}) is significantly "
                    f"below historical ({sr.historical_win_rate:.1%}). Consider "
                    f"pausing this strategy and reviewing market conditions."
                ),
                priority="high",
                expected_impact="Prevents further losses from degraded performance",
                implementation_complexity="easy",
                data_supporting=(
                    f"Recent WR={sr.recent_win_rate:.1%}, "
                    f"Historical WR={sr.historical_win_rate:.1%}, "
                    f"Consecutive losses={sr.consecutive_losses}"
                ),
            )

        # ── High WR but low trades → needs more data ──
        if sr.win_rate > 0.70 and sr.total_trades < 30:
            return ResearchSuggestion(
                category="strategy_tuning",
                title=f"🔬 {sr.name}: High WR but small sample",
                description=(
                    f"Win rate is {sr.win_rate:.1%} but only {sr.total_trades} trades. "
                    f"This may be a small-sample artifact. Continue monitoring — "
                    f"don't increase sizing yet."
                ),
                priority="low",
                expected_impact="Avoid overconfidence in small-sample performance",
                implementation_complexity="easy",
                data_supporting=f"WR={sr.win_rate:.1%}, Trades={sr.total_trades}",
            )

        # ── Consecutive losses → investigate ──
        if sr.consecutive_losses >= 4:
            return ResearchSuggestion(
                category="risk_adjustment",
                title=f"🚨 {sr.name}: {sr.consecutive_losses} consecutive losses",
                description=(
                    f"Strategy has {sr.consecutive_losses} consecutive losses "
                    f"(streak: {sr.current_streak}). This may indicate a regime "
                    f"change or strategy invalidation."
                ),
                priority="high",
                expected_impact="Stop further losses by pausing strategy",
                implementation_complexity="easy",
                data_supporting=f"Streak={sr.current_streak}, Recent PnL=${sr.pnl_7d:.2f}",
            )

        return None

    # -----------------------------------------------------------------------
    # Risk Analysis
    # -----------------------------------------------------------------------

    def _analyze_risk(
        self,
        account_summary: Dict[str, dict],
        strategy_reports: List[StrategyReport],
    ) -> List[ResearchSuggestion]:
        """Generate risk-related suggestions."""
        suggestions: List[ResearchSuggestion] = []

        # ── Daily loss approach limit ──
        for mode, acct in account_summary.items():
            daily_loss = abs(acct.get("pnl_daily", 0))
            max_loss = settings.RISK_DAILY_LOSS_LIMIT
            if daily_loss > 0 and daily_loss >= max_loss * 0.7:
                suggestions.append(ResearchSuggestion(
                    category="risk_adjustment",
                    title=f"⚡ {mode.upper()}: Daily loss approaching limit",
                    description=(
                        f"Daily loss ${daily_loss:.2f} is at "
                        f"{daily_loss / max_loss:.0%} of max (${max_loss}). "
                        f"Reduce position sizes or pause active strategies."
                    ),
                    priority="high",
                    expected_impact="Prevents hitting the hard daily loss limit",
                    implementation_complexity="medium",
                    data_supporting=(
                        f"Daily PnL=${acct.get('pnl_daily', 0):.2f}, "
                        f"Limit=${max_loss}"
                    ),
                ))

        # ── Not enough strategies active ──
        active_count = sum(
            1 for sr in strategy_reports if sr.enabled and sr.status == "healthy"
        )
        if active_count == 0 and any(sr.total_trades > 0 for sr in strategy_reports):
            suggestions.append(ResearchSuggestion(
                category="risk_adjustment",
                title="🔄 All strategies inactive",
                description=(
                    "All strategies are currently inactive or degraded. "
                    "This may indicate a systemic issue. Check API connectivity "
                    "and market availability."
                ),
                priority="high",
                expected_impact="Restore trading capability",
                implementation_complexity="medium",
                data_supporting=f"Active strategies: {active_count}/{len(strategy_reports)}",
            ))

        # ── Large unrealized PnL → review positions ──
        for mode, acct in account_summary.items():
            unrealized = acct.get("total_unrealized_pnl", 0)
            if abs(unrealized) > 200:
                suggestions.append(ResearchSuggestion(
                    category="risk_adjustment",
                    title=f"📊 {mode.upper()}: Large unrealized PnL (${unrealized:+.2f})",
                    description=(
                        f"Unrealized PnL of ${unrealized:.2f} indicates significant "
                        f"open positions. Review position management — consider "
                        f"taking profits or cutting losses."
                    ),
                    priority="medium" if unrealized > 0 else "high",
                    expected_impact="Lock in profits or prevent further losses",
                    implementation_complexity="medium",
                    data_supporting=f"Unrealized=${unrealized:.2f}, Open={acct.get('open_positions', 0)}",
                ))

        return suggestions

    # -----------------------------------------------------------------------
    # Anomaly Detection
    # -----------------------------------------------------------------------

    def _detect_anomalous_patterns(self, sr: StrategyReport) -> List[str]:
        """Detect unusual patterns that warrant investigation."""
        anomalies: List[str] = []

        # Strategy suddenly stopped trading
        if sr.enabled and sr.total_trades > 50 and sr.recent_trades_7d == 0:
            anomalies.append(
                f"{sr.name}: Stopped trading (0 trades in 7d) despite being enabled"
            )

        # Profit factor inverted
        if sr.profit_factor < 0.5 and sr.total_trades >= 10:
            anomalies.append(
                f"{sr.name}: Very low profit factor ({sr.profit_factor:.2f}) — "
                f"losses far exceed wins"
            )

        # Perfect WR with tiny sample → likely artifact
        if sr.win_rate >= 0.95 and sr.total_trades < 10:
            anomalies.append(
                f"{sr.name}: Suspiciously high WR ({sr.win_rate:.1%}) "
                f"with only {sr.total_trades} trades"
            )

        return anomalies

    # -----------------------------------------------------------------------
    # Trends
    # -----------------------------------------------------------------------

    def _extract_trends(
        self, strategy_reports: List[StrategyReport]
    ) -> List[str]:
        """Extract performance trends across strategies."""
        trends: List[str] = []

        profitable = [sr for sr in strategy_reports if sr.is_profitable]
        losing = [sr for sr in strategy_reports if not sr.is_profitable and sr.total_trades > 0]
        no_data = [sr for sr in strategy_reports if sr.total_trades == 0]

        if profitable:
            trends.append(
                f"🟢 {len(profitable)}/{len(strategy_reports)} strategies profitable"
            )
        if losing:
            trends.append(
                f"🔴 {len(losing)}/{len(strategy_reports)} strategies losing"
            )
        if no_data:
            trends.append(
                f"⚪ {len(no_data)}/{len(strategy_reports)} strategies inactive (no data)"
            )

        # Best & worst strategies
        if profitable:
            best = max(profitable, key=lambda s: s.pnl)
            trends.append(f"🏆 Best: {best.name} (${best.pnl:+.2f})")
        if losing:
            worst = min(losing, key=lambda s: s.pnl)
            trends.append(f"📉 Worst: {worst.name} (${worst.pnl:+.2f})")

        return trends

    # -----------------------------------------------------------------------
    # Market Observations
    # -----------------------------------------------------------------------

    def _market_observations(
        self, strategy_reports: List[StrategyReport]
    ) -> List[str]:
        """Generate observations about market conditions from strategy behavior."""
        observations: List[str] = []

        # Count strategies by status
        statuses = {}
        for sr in strategy_reports:
            statuses[sr.status] = statuses.get(sr.status, 0) + 1

        if statuses:
            parts = [f"{count} {s}" for s, count in statuses.items()]
            observations.append(f"Strategy distribution: {', '.join(parts)}")

        # If all are losing, market may be in a tough regime
        losing_all = all(
            not sr.is_profitable
            for sr in strategy_reports
            if sr.total_trades > 0
        )
        if losing_all and len(strategy_reports) > 1:
            observations.append(
                "⚠️ All strategies are losing — this may indicate unfavorable "
                "market-wide conditions rather than individual strategy issues."
            )

        return observations
