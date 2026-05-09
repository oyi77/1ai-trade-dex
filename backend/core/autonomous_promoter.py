"""Autonomous Promoter — fully automatic experiment lifecycle management.

This daemon runs periodically (default every 6h) and:
- Evaluates all DRAFT experiments → promotes to SHADOW immediately
- Evaluates all SHADOW experiments → promotes to PAPER if criteria met
- Evaluates all PAPER experiments → promotes to LIVE if criteria met AND config allows
- Retires failed experiments (no activity, chronically poor metrics)
- Optionally auto-enables strategies in StrategyConfig upon LIVE promotion

Respects ADR-006 gate but can be overridden via AGI_AUTO_PROMOTE=true.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from backend.config import settings
from backend.models.database import StrategyConfig, Trade
from backend.models.kg_models import ExperimentRecord
from backend.core.experiment_runner import ExperimentRunner
from backend.core.agi_types import ExperimentStatus
from backend.core.strategy_health import StrategyHealthMonitor
from backend.core.event_bus import publish_event

logger = logging.getLogger("trading_bot.autonomous_promoter")


class AutonomousPromoter:
    """Daemon that evaluates and promotes experiments without human intervention."""

    @property
    def _s(self):
        from backend.config import settings as _s
        return _s

    @property
    def MIN_TRADES_SHADOW(self): return self._s.AGI_PROMOTER_SHADOW_MIN_TRADES
    @property
    def MIN_DAYS_SHADOW(self): return self._s.AGI_PROMOTER_SHADOW_MIN_DAYS
    @property
    def MIN_WIN_RATE_SHADOW(self): return self._s.AGI_PROMOTER_SHADOW_MIN_WIN_RATE
    @property
    def MAX_DRAWDOWN_SHADOW(self): return self._s.AGI_PROMOTER_SHADOW_MAX_DRAWDOWN
    @property
    def MIN_TRADES_PAPER(self): return self._s.AGI_PROMOTER_PAPER_MIN_TRADES
    @property
    def MIN_DAYS_PAPER(self): return self._s.AGI_PROMOTER_PAPER_MIN_DAYS
    @property
    def MIN_WIN_RATE_PAPER(self): return self._s.AGI_PROMOTER_PAPER_MIN_WIN_RATE
    @property
    def MIN_SHARPE_PAPER(self): return self._s.AGI_PROMOTER_PAPER_MIN_SHARPE
    @property
    def MAX_DRAWDOWN_PAPER(self): return self._s.AGI_PROMOTER_PAPER_MAX_DRAWDOWN

    def _check_paper_criteria_from_health(
        self, exp: ExperimentRecord, health: dict
    ) -> tuple[bool, list[str]]:
        """Evaluate paper→live promotion using current health metrics."""
        reasons = []
        trades = health.get("total_trades", 0)
        win_rate = health.get("win_rate", 0.0)
        sharpe = health.get("sharpe", 0.0)
        max_dd = health.get("max_drawdown", 0.0)

        if trades < self.MIN_TRADES_PAPER:
            reasons.append(f"trades {trades} < {self.MIN_TRADES_PAPER}")
        if win_rate < self.MIN_WIN_RATE_PAPER:
            reasons.append(f"win_rate {win_rate:.1%} < {self.MIN_WIN_RATE_PAPER:.1%}")
        if sharpe < self.MIN_SHARPE_PAPER:
            reasons.append(f"sharpe {sharpe:.2f} < {self.MIN_SHARPE_PAPER:.2f}")
        if max_dd > self.MAX_DRAWDOWN_PAPER:
            reasons.append(f"dd {max_dd:.1%} > {self.MAX_DRAWDOWN_PAPER:.1%}")

        # Age check (paper running time)
        ref_time = exp.promoted_at or exp.created_at
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - ref_time).days
        if age_days < self.MIN_DAYS_PAPER:
            reasons.append(f"paper age {age_days}d < {self.MIN_DAYS_PAPER}d")

        return (len(reasons) == 0, reasons)

    # Kill thresholds (applied to any mode)
    KILL_WIN_RATE = 0.05
    KILL_SHARPE = -2.0
    KILL_DRAWDOWN = 0.50
    MIN_WARMUP_TRADES = 30
    DEGRADATION_WR_THRESHOLD = 0.35
    DEGRADATION_SHARPE_THRESHOLD = -0.5
    MAX_DEGRADATIONS_BEFORE_REVIEW = 2

    def __init__(self, runner: Optional[ExperimentRunner] = None):
        self.runner = runner
        self._last_run: Optional[datetime] = None

    async def run_once(self) -> dict[str, int]:
        """Evaluate all experiments and apply promotion/retirement actions.

        Returns stats: {promoted_shadow→paper, promoted_paper→live, retired, errors}
        """
        stats = {"shadow_to_paper": 0, "paper_to_live": 0, "retired": 0, "errors": 0}
        from backend.db.utils import get_db_session

        with get_db_session() as db:
            health_mon = StrategyHealthMonitor() if getattr(settings, "AGI_STRATEGY_HEALTH_ENABLED", True) else None

            # -1. Bootstrap genome_registry genomes into experiment_records if missing
            self._bootstrap_genome_experiments(db)

            # 0. Evaluate REVIEW experiments → back to BACKTEST after improvement cycle
            reviews = (
                db.query(ExperimentRecord)
                .filter_by(status=ExperimentStatus.REVIEW.value)
                .all()
            )
            for exp in reviews:
                improved = self._check_review_completion(exp, db)
                if improved:
                    exp.status = ExperimentStatus.BACKTEST.value
                    exp.degradation_count = 0
                    exp.review_reason = None
                    db.add(exp)
                    logger.info(f"[AutonomousPromoter] REVIEW→BACKTEST '{exp.name}' (improvements applied)")
                elif self._is_review_expired(exp):
                    exp.status = ExperimentStatus.RETIRED.value
                    exp.retired_at = datetime.now(timezone.utc)
                    db.add(exp)
                    logger.warning(f"[AutonomousPromoter] RETIRED '{exp.name}' (review expired without improvement)")
                    stats["retired"] += 1
            if reviews:
                db.commit()

            # 1. Promote DRAFT → BACKTEST (requires backtest validation before shadow)
            drafts = (
                db.query(ExperimentRecord)
                .filter_by(status=ExperimentStatus.DRAFT.value)
                .all()
            )
            for exp in drafts:
                exp.status = ExperimentStatus.BACKTEST.value
                db.add(exp)
                logger.info(f"[AutonomousPromoter] Draft '{exp.name}' → BACKTEST (awaiting validation)")
            if drafts:
                db.commit()

            # 1b. Evaluate BACKTEST → SHADOW (must pass backtest gate)
            backtests = (
                db.query(ExperimentRecord)
                .filter_by(status=ExperimentStatus.BACKTEST.value)
                .all()
            )
            for exp in backtests:
                bt_result = self._check_backtest_gate(exp, db)
                if bt_result:
                    exp.status = ExperimentStatus.SHADOW.value
                    exp.shadow_trades = 0
                    exp.shadow_win_rate = 0.0
                    exp.shadow_pnl = 0.0
                    exp.backtest_passed = True
                    exp.created_at = datetime.now(timezone.utc)
                    db.add(exp)
                    bt_sharpe = f"{exp.backtest_sharpe:.2f}" if exp.backtest_sharpe is not None else "N/A"
                    bt_wr = f"{exp.backtest_win_rate:.1%}" if exp.backtest_win_rate is not None else "N/A"
                    logger.info(
                        f"[AutonomousPromoter] BACKTEST→SHADOW '{exp.name}': "
                        f"sharpe={bt_sharpe} wr={bt_wr}"
                    )
                else:
                    ref_time = exp.created_at
                    if ref_time and ref_time.tzinfo is None:
                        ref_time = ref_time.replace(tzinfo=timezone.utc)
                    age_days = (datetime.now(timezone.utc) - (ref_time or datetime.now(timezone.utc))).days
                    if age_days > 7:
                        exp.status = ExperimentStatus.RETIRED.value
                        exp.retired_at = datetime.now(timezone.utc)
                        db.add(exp)
                        logger.warning(f"[AutonomousPromoter] RETIRED '{exp.name}' (backtest failed after 7d)")
                        stats["retired"] += 1
            if backtests:
                db.commit()

            # 2. Evaluate SHADOW → PAPER
            shadows = (
                db.query(ExperimentRecord)
                .filter_by(status=ExperimentStatus.SHADOW.value)
                .all()
            )
            for exp in shadows:
                meets, reasons = self._check_shadow_criteria(exp, db)
                if meets:
                    exp.status = ExperimentStatus.PAPER.value
                    exp.promoted_at = datetime.now(timezone.utc)
                    db.add(exp)
                    try:
                        publish_event("experiment_promoted", {
                            "genome_id": exp.id,
                            "strategy_name": exp.strategy_name or exp.name,
                            "from_stage": "SHADOW",
                            "to_stage": "PAPER",
                            "shadow_trades": exp.shadow_trades,
                            "shadow_win_rate": exp.shadow_win_rate,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })
                    except Exception as e:
                        logger.warning(f"[AutonomousPromoter] publish_event failed (non-fatal): {e}")
                    logger.info(
                        f"[AutonomousPromoter] SHADOW→PAPER '{exp.name}': "
                        f"trades={exp.shadow_trades}, wr={exp.shadow_win_rate:.1%}"
                    )
                    stats["shadow_to_paper"] += 1
                else:
                    # If too old and not meeting criteria, retire
                    created_at = exp.created_at
                    if created_at.tzinfo is None:
                        created_at = created_at.replace(tzinfo=timezone.utc)
                    age_days = (datetime.now(timezone.utc) - created_at).days
                    if age_days > self.MIN_DAYS_SHADOW * 2:
                        exp.status = ExperimentStatus.RETIRED.value
                        exp.retired_at = datetime.now(timezone.utc)
                        db.add(exp)
                        logger.warning(
                            f"[AutonomousPromoter] RETIRED '{exp.name}' (shadow, age={age_days}d): "
                            f"{'; '.join(reasons)}"
                        )
                        stats["retired"] += 1
            if shadows:
                db.commit()

            # 3. Evaluate PAPER promotions + kills
            papers = (
                db.query(ExperimentRecord)
                .filter_by(status=ExperimentStatus.PAPER.value)
                .all()
            )
            for exp in papers:
                strategy_name = exp.strategy_name or exp.name

                health = health_mon.assess(strategy_name, db) if health_mon else {"status": "active", "total_trades": 0, "win_rate": 0.0, "sharpe": 0.0, "max_drawdown": 0.0, "brier_score": 1.0, "psi_score": 0.0}
                if health.get("status") == "killed":
                    exp.status = ExperimentStatus.PAPER.value
                    exp.promoted_at = None
                    retry_count = int(getattr(exp, "misc_data", None) or "0") if hasattr(exp, "misc_data") else 0
                    retry_count += 1
                    max_retries = getattr(settings, "AGI_DEMOTION_RETRY_LIMIT", 3)
                    if retry_count >= max_retries:
                        exp.status = ExperimentStatus.RETIRED.value
                        exp.retired_at = datetime.now(timezone.utc)
                        logger.warning(
                            f"[AutonomousPromoter] RETIRED (kill, {retry_count} retries) '{exp.name}': "
                            f"wr={health.get('win_rate', 0):.1%}, sharpe={health.get('sharpe', 0):.2f}"
                        )
                        stats["retired"] += 1
                    else:
                        db.add(exp)
                        logger.warning(
                            f"[AutonomousPromoter] DEMOTED LIVE→PAPER '{exp.name}' (retry {retry_count}/{max_retries}): "
                            f"wr={health.get('win_rate', 0):.1%}, sharpe={health.get('sharpe', 0):.2f}"
                        )
                        stats["demoted"] = stats.get("demoted", 0) + 1
                    db.add(exp)
                    continue

                meets, reasons = self._check_paper_criteria_from_health(exp, health)
                if meets:
                    if not settings.AGI_AUTO_PROMOTE:
                        logger.info(
                            f"[AutonomousPromoter] PAPER→LIVE_TRIAL SKIPPED '{exp.name}': "
                            f"AGI_AUTO_PROMOTE=false (manual intervention required)"
                        )
                        continue

                    exp.status = ExperimentStatus.LIVE_TRIAL.value
                    exp.promoted_at = datetime.now(timezone.utc)
                    db.add(exp)

                    logger.info(
                        f"[AutonomousPromoter] PAPER→LIVE_TRIAL '{exp.name}' promoted to trial "
                        f"(trades={health.get('total_trades', 0)}, wr={health.get('win_rate', 0):.1%})"
                    )
                    stats["paper_to_live_trial"] = stats.get("paper_to_live_trial", 0) + 1
                else:
                    ref_time = exp.promoted_at or exp.created_at
                    if ref_time.tzinfo is None:
                        ref_time = ref_time.replace(tzinfo=timezone.utc)
                    age_days = (datetime.now(timezone.utc) - ref_time).days
                    if age_days > self.MIN_DAYS_PAPER * 3:
                        exp.status = ExperimentStatus.RETIRED.value
                        exp.retired_at = datetime.now(timezone.utc)
                        db.add(exp)
                        logger.warning(
                            f"[AutonomousPromoter] RETIRED '{exp.name}' (paper, age={age_days}d): "
                            f"{'; '.join(reasons)}"
                        )
                        stats["retired"] += 1
            if papers:
                db.commit()

            # 4. Evaluate LIVE_TRIAL experiments — promote to LIVE_PROMOTED or demote to PAPER
            trials = (
                db.query(ExperimentRecord)
                .filter_by(status=ExperimentStatus.LIVE_TRIAL.value)
                .all()
            )
            for exp in trials:
                strategy_name = exp.strategy_name or exp.name
                promoted = exp.promoted_at or exp.created_at
                if promoted.tzinfo is None:
                    promoted = promoted.replace(tzinfo=timezone.utc)
                trial_days = (datetime.now(timezone.utc) - promoted).days
                min_trial_days = getattr(settings, "AGI_LIVE_TRIAL_DAYS", 7)
                min_trial_trades = getattr(settings, "AGI_LIVE_TRIAL_MIN_TRADES", 10)

                health = health_mon.assess(strategy_name, db, readonly=True) if health_mon else {"status": "active", "total_trades": 0, "win_rate": 0.0, "sharpe": 0.0}
                if health.get("status") == "killed":
                    exp.status = ExperimentStatus.PAPER.value
                    exp.promoted_at = None
                    db.add(exp)
                    logger.warning(f"[AutonomousPromoter] LIVE_TRIAL→PAPER (kill) '{exp.name}': wr={health.get('win_rate', 0):.1%}")
                    stats["demoted"] = stats.get("demoted", 0) + 1
                    # Trigger improvement loop on demotion
                    self._trigger_improvement_loop(strategy_name, db)
                    continue

                if trial_days >= min_trial_days and health.get("total_trades", 0) >= min_trial_trades:
                    wr = health.get("win_rate", 0.0)
                    sharpe = health.get("sharpe", 0.0)
                    if wr >= 0.45 and sharpe >= -0.5:
                        exp.status = ExperimentStatus.LIVE_PROMOTED.value
                        exp.promoted_at = datetime.now(timezone.utc)
                        if settings.AGI_AUTO_ENABLE:
                            await self._enable_strategy(strategy_name, db, experiment=exp)
                        db.add(exp)
                        try:
                            publish_event("experiment_promoted", {
                                "genome_id": exp.id,
                                "strategy_name": exp.strategy_name or exp.name,
                                "from_stage": "LIVE_TRIAL",
                                "to_stage": "LIVE_PROMOTED",
                                "win_rate": wr,
                                "sharpe": sharpe,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            })
                        except Exception as e:
                            logger.warning(f"[AutonomousPromoter] publish_event failed (non-fatal): {e}")
                        logger.info(f"[AutonomousPromoter] LIVE_TRIAL→LIVE_PROMOTED '{exp.name}': wr={wr:.1%} sharpe={sharpe:.2f}")
                        stats["trial_to_live"] = stats.get("trial_to_live", 0) + 1
                    else:
                        exp.status = ExperimentStatus.PAPER.value
                        exp.promoted_at = None
                        db.add(exp)
                        logger.warning(f"[AutonomousPromoter] LIVE_TRIAL→PAPER (degraded) '{exp.name}': wr={wr:.1%} sharpe={sharpe:.2f}")
                        stats["demoted"] = stats.get("demoted", 0) + 1
                        # Trigger improvement loop on degradation demotion
                        self._trigger_improvement_loop(strategy_name, db)
            if trials:
                db.commit()

            # 5. Evaluate LIVE_PROMOTED experiments for degradation → demote to PAPER
            lives = (
                db.query(ExperimentRecord)
                .filter_by(status=ExperimentStatus.LIVE_PROMOTED.value)
                .all()
            )
            for exp in lives:
                strategy_name = exp.strategy_name or exp.name
                health = health_mon.assess(strategy_name, db) if health_mon else {"status": "active", "total_trades": 0, "win_rate": 0.0, "sharpe": 0.0, "max_drawdown": 0.0}
                if health.get("status") == "killed":
                    exp.status = ExperimentStatus.PAPER.value
                    exp.promoted_at = None
                    db.add(exp)
                    logger.warning(
                        f"[AutonomousPromoter] LIVE_PROMOTED→PAPER (kill) '{exp.name}': "
                        f"wr={health.get('win_rate', 0):.1%}, sharpe={health.get('sharpe', 0):.2f}"
                    )
                    stats["demoted"] = stats.get("demoted", 0) + 1
                    # Trigger improvement loop: forensics + auto_improve + new DRAFT experiment
                    self._trigger_improvement_loop(strategy_name, db)
                    continue

                wr = health.get("win_rate", 0.0)
                sharpe = health.get("sharpe", 0.0)
                total_trades = health.get("total_trades", 0)
                if total_trades >= self.MIN_WARMUP_TRADES and (
                    wr < self.DEGRADATION_WR_THRESHOLD or sharpe < self.DEGRADATION_SHARPE_THRESHOLD
                ):
                    exp.degradation_count = (exp.degradation_count or 0) + 1
                    exp.last_degradation_at = datetime.now(timezone.utc)
                    if exp.degradation_count >= self.MAX_DEGRADATIONS_BEFORE_REVIEW:
                        exp.status = ExperimentStatus.REVIEW.value
                        exp.review_reason = (
                            f"Degraded: wr={wr:.1%} sharpe={sharpe:.2f} over {total_trades} trades "
                            f"({exp.degradation_count} degradation events)"
                        )
                        exp.degradation_count = 0
                        await self._disable_strategy(strategy_name, db)
                        logger.warning(
                            f"[AutonomousPromoter] LIVE→REVIEW '{exp.name}': {exp.review_reason}"
                        )
                    else:
                        logger.warning(
                            f"[AutonomousPromoter] DEGRADATION #{exp.degradation_count} '{exp.name}': "
                            f"wr={wr:.1%} sharpe={sharpe:.2f}"
                        )
                    db.add(exp)
            if lives:
                db.commit()

            self._last_run = datetime.now(timezone.utc)
            logger.info(
                f"[AutonomousPromoter] Run complete: "
                f"+{stats['shadow_to_paper']} shadow→paper, "
                f"+{stats['paper_to_live']} paper→live, "
                f"retired={stats['retired']}"
            )
            return stats


    def _check_shadow_criteria(self, exp: ExperimentRecord, db: Session) -> tuple[bool, list[str]]:
        """Check if experiment meets shadow→paper criteria."""
        reasons = []
        trades = exp.shadow_trades or 0
        win_rate = exp.shadow_win_rate or 0.0

        if trades < self.MIN_TRADES_SHADOW:
            reasons.append(f"trades {trades} < {self.MIN_TRADES_SHADOW}")
        if exp.shadow_win_rate < self.MIN_WIN_RATE_SHADOW:
            reasons.append(f"win_rate {win_rate:.1%} < {self.MIN_WIN_RATE_SHADOW:.1%}")

        # Age check (handle naive/aware)
        created_at = exp.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - created_at).days
        if age_days < self.MIN_DAYS_SHADOW:
            reasons.append(f"age {age_days}d < {self.MIN_DAYS_SHADOW}d")

        drawdown = self._compute_shadow_drawdown(exp, db)
        if drawdown > self.MAX_DRAWDOWN_SHADOW:
            reasons.append(f"drawdown {drawdown:.1%} > {self.MAX_DRAWDOWN_SHADOW:.1%}")

        return (len(reasons) == 0, reasons)

    def _compute_shadow_drawdown(self, exp: ExperimentRecord, db: Session) -> float:
        try:
            trades = (
                db.query(Trade)
                .filter(
                    Trade.strategy == exp.strategy_name,
                    Trade.trading_mode == "paper",
                    Trade.settled.is_(True),
                    Trade.result.in_(["win", "loss"]),
                )
                .order_by(Trade.timestamp.asc())
                .all()
            )
            if not trades:
                return 0.0
            peak = 0.0
            cumulative = 0.0
            max_dd = 0.0
            for t in trades:
                cumulative += t.pnl or 0.0
                if cumulative > peak:
                    peak = cumulative
                dd = (peak - cumulative) / peak if peak > 0 else 0.0
                if dd > max_dd:
                    max_dd = dd
            return max_dd
        except Exception:
            return 0.0

    def _check_paper_criteria(self, exp: ExperimentRecord) -> tuple[bool, list[str]]:
        reasons = []
        trades = exp.shadow_trades or 0
        win_rate = exp.shadow_win_rate or 0.0

        if trades < self.MIN_TRADES_PAPER:
            reasons.append(f"trades {trades} < {self.MIN_TRADES_PAPER}")
        if win_rate < self.MIN_WIN_RATE_PAPER:
            reasons.append(f"win_rate {win_rate:.1%} < {self.MIN_WIN_RATE_PAPER:.1%}")

        ref_time = exp.promoted_at or exp.created_at
        if ref_time is None:
            reasons.append("no reference time for paper age check")
        else:
            if ref_time.tzinfo is None:
                ref_time = ref_time.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - ref_time).days
            if age_days < self.MIN_DAYS_PAPER:
                reasons.append(f"paper age {age_days}d < {self.MIN_DAYS_PAPER}d")

        return (len(reasons) == 0, reasons)

    def _get_paper_trades(self, exp: ExperimentRecord) -> int:
        return exp.shadow_trades or 0  # Stub

    def _get_paper_win_rate(self, exp: ExperimentRecord) -> float:
        return exp.shadow_win_rate or 0.0  # Stub

    def _should_kill(self, exp: ExperimentRecord) -> bool:
        """Return True if experiment is catastrophically bad and should be retired."""
        trades = exp.shadow_trades or 0
        if trades < self.MIN_WARMUP_TRADES:
            return False
        win_rate = exp.shadow_win_rate or 0.0
        if win_rate < self.KILL_WIN_RATE:
            return True
        # Additional kill checks would require outcome metrics (sharpe, drawdown)
        return False

    async def _enable_strategy(self, strategy_name: str, db: Session, experiment: Optional[ExperimentRecord] = None) -> None:
        """Create/enable StrategyConfig for the promoted experiment and schedule it.

        If experiment carries evolved params (strategy_composition), merge them into
        the strategy's live config — this closes the RL loop: evolver generates variants,
        best variant promotes to live, params get applied.
        """
        import json as _json
        from backend.core.scheduler import schedule_strategy  # Lazy to avoid circular import

        config = (
            db.query(StrategyConfig)
            .filter_by(strategy_name=strategy_name)
            .first()
        )
        if config:
            config.enabled = True
            config.updated_at = datetime.now(timezone.utc)
            interval = config.interval_seconds or 60

            # Apply evolved params from experiment if available
            if experiment and experiment.strategy_composition:
                evolved_params = experiment.strategy_composition
                if isinstance(evolved_params, str):
                    try:
                        evolved_params = _json.loads(evolved_params)
                    except (_json.JSONDecodeError, TypeError):
                        evolved_params = {}
                # Strip internal evolver metadata
                evolved_params = {k: v for k, v in evolved_params.items() if not k.startswith("_")}

                current_params = config.params or {}
                if isinstance(current_params, str):
                    try:
                        current_params = _json.loads(current_params)
                    except (_json.JSONDecodeError, TypeError):
                        current_params = {}

                merged = {**current_params, **evolved_params}
                config.params = merged
                logger.info(
                    f"[AutonomousPromoter] Applied evolved params to '{strategy_name}': "
                    f"merged {len(evolved_params)} param(s) into live config"
                )

            logger.info(f"[AutonomousPromoter] Enabled existing StrategyConfig '{strategy_name}' (interval={interval}s)")
        else:
            # Infer interval from strategy registry
            from backend.strategies.registry import STRATEGY_REGISTRY
            strategy_cls = STRATEGY_REGISTRY.get(strategy_name)
            default_interval = 60
            if strategy_cls and hasattr(strategy_cls, "default_interval"):
                default_interval = getattr(strategy_cls, "default_interval", 60)

            initial_params = {}
            if experiment and experiment.strategy_composition:
                initial_params = experiment.strategy_composition
                if isinstance(initial_params, str):
                    try:
                        initial_params = _json.loads(initial_params)
                    except (_json.JSONDecodeError, TypeError):
                        initial_params = {}
                initial_params = {k: v for k, v in initial_params.items() if not k.startswith("_")}

            config = StrategyConfig(
                strategy_name=strategy_name,
                enabled=True,
                interval_seconds=default_interval,
                mode="live",
                params=initial_params if initial_params else None,
            )
            db.add(config)
            interval = default_interval
            logger.info(f"[AutonomousPromoter] Created & enabled StrategyConfig '{strategy_name}' (interval={interval}s)")
        db.commit()

        try:
            schedule_strategy(strategy_name, interval, mode="live")
        except Exception as e:
            logger.warning(f"[AutonomousPromoter] Failed to dynamically schedule '{strategy_name}': {e}")

    async def _disable_strategy(self, strategy_name: str, db: Session) -> None:
        from datetime import datetime, timezone
        config = db.query(StrategyConfig).filter_by(strategy_name=strategy_name).first()
        if config:
            config.enabled = False
            config.disabled_at = datetime.now(timezone.utc)
            db.commit()
            logger.info(f"[AutonomousPromoter] Disabled StrategyConfig '{strategy_name}' (degradation fallback)")

    def _trigger_improvement_loop(self, strategy_name: str, db: Session) -> None:
        """Trigger forensics analysis + auto_improve for a demoted strategy.

        Creates a new DRAFT ExperimentRecord so the strategy re-enters the
        DRAFT→SHADOW→PAPER→LIVE_TRIAL pipeline with improved params.
        Respects AGI_MAX_IMPROVEMENT_ATTEMPTS to avoid infinite retry loops.
        """
        max_attempts = getattr(settings, "AGI_MAX_IMPROVEMENT_ATTEMPTS", 3)

        # Count how many improvement attempts have already been made
        attempt_count = (
            db.query(ExperimentRecord)
            .filter(
                ExperimentRecord.strategy_name == strategy_name,
                ExperimentRecord.status.in_([
                    ExperimentStatus.RETIRED.value,
                    ExperimentStatus.PAPER.value,
                    ExperimentStatus.DRAFT.value,
                ]),
            )
            .count()
        )

        if attempt_count >= max_attempts:
            logger.warning(
                "[AutonomousPromoter] '%s' reached max improvement attempts (%d) — retiring",
                strategy_name, max_attempts,
            )
            # Mark all active experiments for this strategy as RETIRED
            db.query(ExperimentRecord).filter(
                ExperimentRecord.strategy_name == strategy_name,
                ExperimentRecord.status.notin_([ExperimentStatus.RETIRED.value]),
            ).update({"status": ExperimentStatus.RETIRED.value}, synchronize_session=False)
            db.commit()
            return

        # 1. Generate forensics proposals
        try:
            from backend.core.forensics_integration import generate_forensics_proposals
            generate_forensics_proposals(strategy_filter=strategy_name)
            logger.info("[AutonomousPromoter] Forensics proposals generated for '%s'", strategy_name)
        except Exception as e:
            logger.warning("[AutonomousPromoter] Forensics generation failed for '%s': %s", strategy_name, e)

        # 2. Create a new DRAFT experiment so the strategy re-enters the pipeline
        new_exp = ExperimentRecord(
            name=f"{strategy_name}_improve_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}",
            strategy_name=strategy_name,
            status=ExperimentStatus.DRAFT.value,
            created_at=datetime.now(timezone.utc),
        )
        db.add(new_exp)
        db.commit()
        logger.info(
            "[AutonomousPromoter] Created new DRAFT experiment '%s' for improvement cycle (attempt %d/%d)",
            new_exp.name, attempt_count + 1, max_attempts,
        )

    def _bootstrap_genome_experiments(self, db: Session) -> None:
        """Create ExperimentRecord rows for genome_registry genomes that lack them."""
        from backend.models.database import GenomeRegistry

        genomes = db.query(GenomeRegistry).filter(
            GenomeRegistry.stage.in_(["DRAFT", "SHADOW", "PAPER", "LIVE"])
        ).all()
        if not genomes:
            return

        for genome in genomes:
            existing = db.query(ExperimentRecord).filter_by(
                name=genome.strategy_name
            ).first()
            if existing:
                continue

            stage_map = {
                "DRAFT": ExperimentStatus.DRAFT.value,
                "SHADOW": ExperimentStatus.SHADOW.value,
                "PAPER": ExperimentStatus.PAPER.value,
                "LIVE": ExperimentStatus.LIVE_PROMOTED.value,
            }
            exp = ExperimentRecord(
                name=genome.strategy_name,
                strategy_name=genome.strategy_name,
                status=stage_map.get(genome.stage, ExperimentStatus.DRAFT.value),
                created_at=genome.created_at or datetime.now(timezone.utc),
            )
            db.add(exp)
            logger.info(
                f"[AutonomousPromoter] Bootstrapped ExperimentRecord "
                f"'{genome.strategy_name}' at stage={genome.stage}"
            )
        db.commit()

    def _check_backtest_gate(self, exp: ExperimentRecord, db: Session) -> bool:
        from backend.models.database import StrategyProposal
        proposal = (
            db.query(StrategyProposal)
            .filter_by(strategy_name=exp.strategy_name, status="pending")
            .order_by(StrategyProposal.created_at.desc())
            .first()
        )
        if proposal and proposal.backtest_passed:
            exp.backtest_sharpe = proposal.backtest_sharpe
            exp.backtest_win_rate = proposal.backtest_win_rate
            return True
        if exp.backtest_passed:
            return True

        # Seed-genome bypass: if no StrategyProposal exists at all, auto-pass
        # the gate. Initial population genomes were hand-crafted with predefined
        # chromosome configs — they don't need formal backtest validation, they
        # need shadow testing. Only apply this bypass when there are zero
        # proposals for this strategy (not when proposals exist but haven't
        # passed — that case should still wait for backtest completion).
        any_proposal = (
            db.query(StrategyProposal)
            .filter_by(strategy_name=exp.strategy_name)
            .first()
        )
        if not any_proposal:
            logger.info(
                f"[AutonomousPromoter] BACKTEST gate for '{exp.name}': "
                f"no StrategyProposal exists — requires manual validation"
            )
            return False

        return False

    def _check_review_completion(self, exp: ExperimentRecord, db: Session) -> bool:
        from backend.models.database import StrategyProposal
        new_proposals = (
            db.query(StrategyProposal)
            .filter(
                StrategyProposal.strategy_name == exp.strategy_name,
                StrategyProposal.status == "pending",
                StrategyProposal.backtest_passed.is_(True),
            )
            .order_by(StrategyProposal.created_at.desc())
            .first()
        )
        if new_proposals:
            exp.backtest_sharpe = new_proposals.backtest_sharpe
            exp.backtest_win_rate = new_proposals.backtest_win_rate
            return True
        return False

    def _is_review_expired(self, exp: ExperimentRecord) -> bool:
        ref = exp.last_degradation_at or exp.created_at
        if ref and ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)
        if not ref:
            return False
        return (datetime.now(timezone.utc) - ref).days > 14


# Module-level singleton
autonomous_promoter = AutonomousPromoter()


async def autonomous_promotion_job() -> None:
    """Scheduled job entrypoint for APScheduler."""
    try:
        stats = await autonomous_promoter.run_once()
        logger.info(f"[autonomous_promotion_job] Completed: {stats}")
    except Exception as e:
        logger.error(f"[autonomous_promotion_job] Fatal error: {e}", exc_info=True)
