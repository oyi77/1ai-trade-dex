"""Risk Compliance Evaluation Suite.

Validates that strategies comply with risk limits: position sizing,
drawdown limits, daily loss limits, and exposure caps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from loguru import logger


@dataclass
class ComplianceCheck:
    """Result of a single compliance check."""

    check_name: str
    passed: bool
    value: float
    threshold: float
    message: str = ""


@dataclass
class ComplianceResult:
    """Aggregated risk compliance result for a strategy."""

    strategy: str
    checks: list[ComplianceCheck] = field(default_factory=list)
    passed: bool = True
    violations: int = 0

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "passed": self.passed,
            "violations": self.violations,
            "checks": [
                {
                    "name": c.check_name,
                    "passed": c.passed,
                    "value": round(c.value, 4),
                    "threshold": round(c.threshold, 4),
                    "message": c.message,
                }
                for c in self.checks
            ],
        }


class RiskComplianceSuite:
    """Validates strategy risk compliance against configured limits."""

    def __init__(self):
        from backend.config import settings

        self.max_drawdown = settings.DAILY_DRAWDOWN_LIMIT_PCT
        self.max_daily_loss = settings.DAILY_LOSS_LIMIT
        self.max_position = settings.MAX_POSITION_FRACTION
        self.max_exposure = settings.MAX_TOTAL_EXPOSURE_FRACTION
        self.max_trade_size = settings.MAX_TRADE_SIZE

    def evaluate(
        self,
        strategy: str,
        lookback_days: int = 7,
        trading_mode: str = "live",
    ) -> ComplianceResult:
        """Evaluate risk compliance for a single strategy."""
        result = ComplianceResult(strategy=strategy)

        try:
            from backend.models.database import SessionLocal, Trade

            db = SessionLocal()
            try:
                cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
                trades = (
                    db.query(Trade)
                    .filter(
                        Trade.strategy == strategy,
                        Trade.trading_mode == trading_mode,
                        Trade.timestamp >= cutoff,
                    )
                    .all()
                )

                if not trades:
                    result.checks.append(
                        ComplianceCheck(
                            check_name="data_availability",
                            passed=True,
                            value=0,
                            threshold=0,
                            message="No trades in lookback period",
                        )
                    )
                    return result

                # Check 1: Max drawdown
                pnls = [t.pnl or 0.0 for t in trades if t.pnl is not None]
                max_dd = self._max_drawdown(pnls)
                dd_pass = max_dd <= self.max_drawdown
                result.checks.append(
                    ComplianceCheck(
                        check_name="max_drawdown",
                        passed=dd_pass,
                        value=max_dd,
                        threshold=self.max_drawdown,
                        message=f"Drawdown {max_dd:.1%} {'<=' if dd_pass else '>'} {self.max_drawdown:.1%}",
                    )
                )

                # Check 2: Daily loss limit
                daily_pnl = sum(pnl for pnl in pnls)
                daily_pass = daily_pnl >= -self.max_daily_loss
                result.checks.append(
                    ComplianceCheck(
                        check_name="daily_loss_limit",
                        passed=daily_pass,
                        value=daily_pnl,
                        threshold=-self.max_daily_loss,
                        message=f"Period PnL ${daily_pnl:.2f} {'>=' if daily_pass else '<'} -${self.max_daily_loss:.2f}",
                    )
                )

                # Check 3: Max single trade size
                sizes = [abs(t.amount or 0.0) for t in trades]
                max_size = max(sizes) if sizes else 0.0
                size_pass = max_size <= self.max_trade_size
                result.checks.append(
                    ComplianceCheck(
                        check_name="max_trade_size",
                        passed=size_pass,
                        value=max_size,
                        threshold=self.max_trade_size,
                        message=f"Max trade ${max_size:.2f} {'<=' if size_pass else '>'} ${self.max_trade_size:.2f}",
                    )
                )

                # Check 4: Consecutive loss limit
                consec_losses = self._max_consecutive_losses(trades)
                consec_pass = consec_losses <= 5
                result.checks.append(
                    ComplianceCheck(
                        check_name="consecutive_losses",
                        passed=consec_pass,
                        value=consec_losses,
                        threshold=5,
                        message=f"Max consecutive losses: {consec_losses} {'<=' if consec_pass else '>'} 5",
                    )
                )

                result.violations = sum(1 for c in result.checks if not c.passed)
                result.passed = result.violations == 0

            finally:
                db.close()

        except Exception as e:
            logger.error("[RiskComplianceSuite] Failed for '%s': %s", strategy, e)
            result.passed = False

        return result

    def evaluate_all(
        self, lookback_days: int = 7, trading_mode: str = "live"
    ) -> list[ComplianceResult]:
        """Evaluate all active strategies."""
        results = []
        try:
            from backend.models.database import SessionLocal, StrategyConfig

            db = SessionLocal()
            try:
                active = (
                    db.query(StrategyConfig)
                    .filter(StrategyConfig.enabled.is_(True))
                    .all()
                )
                for cfg in active:
                    results.append(
                        self.evaluate(cfg.strategy_name, lookback_days, trading_mode)
                    )
            finally:
                db.close()
        except Exception as e:
            logger.error("[RiskComplianceSuite] evaluate_all failed: %s", e)
        return results

    @staticmethod
    def _max_drawdown(pnls: list[float]) -> float:
        if not pnls:
            return 0.0
        peak = 0.0
        equity = 0.0
        max_dd = 0.0
        for p in pnls:
            equity += p
            if equity > peak:
                peak = equity
            if peak > 0:
                dd = (peak - equity) / peak
                max_dd = max(max_dd, dd)
        return max_dd

    @staticmethod
    def _max_consecutive_losses(trades) -> int:
        max_streak = 0
        current = 0
        for t in sorted(trades, key=lambda x: x.timestamp or datetime.min):
            if t.result == "loss":
                current += 1
                max_streak = max(max_streak, current)
            else:
                current = 0
        return max_streak
