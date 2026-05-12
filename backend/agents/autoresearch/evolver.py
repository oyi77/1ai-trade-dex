import json
import random
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from backend.models.database import SessionLocal, StrategyConfig
from backend.models.outcome_tables import StrategyOutcome
from backend.models.kg_models import ExperimentRecord
from backend.core.agi_types import ExperimentStatus

from loguru import logger

TUNABLE_PARAM_RANGES = {
    "min_edge": (0.01, 0.20),
    "max_position_usd": (5.0, 100.0),
    "interval_seconds": (15, 300),
    "max_minutes_to_resolution": (10, 120),
    "kelly_fraction": (0.01, 0.25),
    "slippage_buffer": (0.5, 2.0),
}

EVOLVABLE_WIN_RATE_FLOOR = 0.0
EVOLVABLE_WIN_RATE_CEIL = 0.45
MIN_OUTCOMES_TO_EVOLVE = 10
FUNDAMENTALLY_BROKEN_WIN_RATE = 0.0
FUNDAMENTALLY_BROKEN_MIN_TRADES = 30
VARIANTS_PER_STRATEGY = 3
PARAM_PERTURBATION = 0.25


class StrategyEvolver:
    def run_evolution_cycle(self, db: Optional[Session] = None) -> list[int]:
        _owned = db is None
        db = db or SessionLocal()
        created = []
        try:
            self._record_lineage_for_promoted(db)

            strategies = self._find_evolvable_strategies(db)
            for strategy_name, stats in strategies.items():
                if self._has_active_experiment(strategy_name, db):
                    continue
                is_broken = stats.get("win_rate", 1.0) <= FUNDAMENTALLY_BROKEN_WIN_RATE and stats.get("total", 0) >= FUNDAMENTALLY_BROKEN_MIN_TRADES

                best_parent = self._find_best_retired_parent(strategy_name, db)
                if best_parent:
                    variants = self._crossover_variants(strategy_name, db, best_parent, is_broken)
                else:
                    variants = self._generate_variants(strategy_name, db, aggressive=is_broken)

                for variant in variants:
                    clean = {k: v for k, v in variant.items() if not k.startswith("_")}
                    exp = ExperimentRecord(
                        name=f"{strategy_name}_evolve_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}_{random.randint(1000,9999)}",
                        strategy_name=strategy_name,
                        strategy_composition=clean,
                        status=ExperimentStatus.DRAFT.value,
                        created_at=datetime.now(timezone.utc),
                    )
                    db.add(exp)
                    db.flush()
                    created.append(exp.id)

                    parent_id = best_parent.id if best_parent else None
                    self._record_lineage(db, strategy_name, parent_id, exp.id, "perturbation", clean, stats.get("win_rate", 0.0))
                    self._create_proposal_for_variant(db, strategy_name, clean, exp.id, is_broken)

            if created:
                db.commit()
                logger.info(
                    "[StrategyEvolver] Created %d variant experiments for %d strategies",
                    len(created),
                    len(strategies),
                )
            return created
        except Exception as e:
            logger.error("[StrategyEvolver] Failed: %s", e)
            if _owned:
                try:
                    db.rollback()
                except Exception as rollback_err:
                    logger.error("[StrategyEvolver] Failed to rollback: %s", rollback_err)
            return created
        finally:
            if _owned:
                db.close()

    def _create_proposal_for_variant(
        self, db: Session, strategy_name: str, params: dict, experiment_id: int, is_broken: bool
    ) -> None:
        """Create a StrategyProposal for the variant so it passes through forward simulation gate."""
        from backend.models.database import StrategyProposal

        existing = db.query(StrategyProposal).filter(
            StrategyProposal.strategy_name == strategy_name,
            StrategyProposal.status == "pending",
            StrategyProposal.auto_promotable == True,
        ).count()

        if existing >= 5:
            return

        db.add(StrategyProposal(
            strategy_name=strategy_name,
            change_details=params,
            expected_impact=f"Evolver variant from experiment #{experiment_id}" + (" (priority: broken strategy)" if is_broken else ""),
            admin_decision="pending",
            status="pending",
            auto_promotable=True,
            backtest_passed=False,
            created_at=datetime.now(timezone.utc),
        ))

    def _find_evolvable_strategies(self, db: Session) -> dict:
        from sqlalchemy import func
        rows = (
            db.query(
                StrategyOutcome.strategy,
                func.count(StrategyOutcome.id).label("total"),
            )
            .group_by(StrategyOutcome.strategy)
            .all()
        )
        result = {}
        for row in rows:
            name = row.strategy
            total = row.total
            if total < MIN_OUTCOMES_TO_EVOLVE:
                continue
            outcomes = (
                db.query(StrategyOutcome)
                .filter(StrategyOutcome.strategy == name)
                .all()
            )
            wins = sum(1 for o in outcomes if o.result == "win")
            wr = wins / total if total > 0 else 0.0
            if total >= FUNDAMENTALLY_BROKEN_MIN_TRADES and wr <= FUNDAMENTALLY_BROKEN_WIN_RATE:
                logger.info(
                    "[StrategyEvolver] Priority evolve for '%s' — fundamentally broken (%d trades, 0%% WR)",
                    name, total,
                )
                result[name] = {"total": total, "wins": wins, "win_rate": wr}
                continue
            if EVOLVABLE_WIN_RATE_FLOOR <= wr < EVOLVABLE_WIN_RATE_CEIL:
                result[name] = {"total": total, "wins": wins, "win_rate": wr}
        return result

    def _has_active_experiment(self, strategy_name: str, db: Session) -> bool:
        active_statuses = [
            ExperimentStatus.DRAFT.value,
            ExperimentStatus.SHADOW.value,
            ExperimentStatus.PAPER.value,
        ]
        return (
            db.query(ExperimentRecord)
            .filter(
                ExperimentRecord.strategy_name == strategy_name,
                ExperimentRecord.status.in_(active_statuses),
            )
            .first()
            is not None
        )

    def _generate_variants(self, strategy_name: str, db: Session, aggressive: bool = False) -> list[dict]:
        config = (
            db.query(StrategyConfig)
            .filter(StrategyConfig.strategy_name == strategy_name)
            .first()
        )
        base_params = {}
        if config and config.params:
            try:
                base_params = json.loads(config.params) if isinstance(config.params, str) else config.params
            except (json.JSONDecodeError, TypeError):
                base_params = {}

        from backend.strategies.registry import STRATEGY_REGISTRY
        strategy_cls = STRATEGY_REGISTRY.get(strategy_name)
        if strategy_cls and hasattr(strategy_cls, "default_params"):
            for k, v in strategy_cls.default_params.items():
                base_params.setdefault(k, v)

        variants = []
        for i in range(VARIANTS_PER_STRATEGY):
            variant = dict(base_params)
            variant["_evolver_generation"] = i + 1
            variant["_evolver_created_at"] = datetime.now(timezone.utc).isoformat()
            for param_key, (lo, hi) in TUNABLE_PARAM_RANGES.items():
                if param_key in variant:
                    current = float(variant[param_key])
                    magnitude = PARAM_PERTURBATION * (3.0 if aggressive else 1.0)
                    perturbation = current * magnitude * random.choice([-1, 1])
                    new_val = max(lo, min(hi, current + perturbation))
                    if isinstance(variant[param_key], int):
                        new_val = int(round(new_val))
                    variant[param_key] = round(new_val, 4) if isinstance(new_val, float) else new_val
            variants.append(variant)
        return variants

    def _find_best_retired_parent(self, strategy_name: str, db: Session) -> Optional[object]:
        return (
            db.query(ExperimentRecord)
            .filter(
                ExperimentRecord.strategy_name == strategy_name,
                ExperimentRecord.status == ExperimentStatus.RETIRED.value,
                ExperimentRecord.shadow_win_rate > 0,
            )
            .order_by(ExperimentRecord.shadow_win_rate.desc())
            .first()
        )

    def _crossover_variants(
        self, strategy_name: str, db: Session, parent: ExperimentRecord, aggressive: bool
    ) -> list[dict]:
        parent_params = parent.strategy_composition or {}
        if isinstance(parent_params, str):
            try:
                parent_params = json.loads(parent_params)
            except (json.JSONDecodeError, TypeError):
                parent_params = {}

        config = (
            db.query(StrategyConfig)
            .filter(StrategyConfig.strategy_name == strategy_name)
            .first()
        )
        current_params = {}
        if config and config.params:
            try:
                current_params = json.loads(config.params) if isinstance(config.params, str) else config.params
            except (json.JSONDecodeError, TypeError):
                current_params = {}

        from backend.ai.meta_learner import MetaLearner
        biases = MetaLearner().get_biases(strategy_name, db=db)

        variants = []
        for i in range(VARIANTS_PER_STRATEGY):
            variant = {}
            all_keys = set(list(parent_params.keys()) + list(current_params.keys()))
            for key in all_keys:
                if key.startswith("_"):
                    continue
                parent_val = parent_params.get(key)
                current_val = current_params.get(key)

                if parent_val is not None and current_val is not None:
                    if random.random() < 0.5:
                        variant[key] = parent_val
                    else:
                        variant[key] = current_val
                elif parent_val is not None:
                    variant[key] = parent_val
                elif current_val is not None:
                    variant[key] = current_val

            for param_key, (lo, hi) in TUNABLE_PARAM_RANGES.items():
                if param_key in variant:
                    current = float(variant[param_key])
                    bias = biases.get(param_key)
                    if bias and bias["confidence"] > 0.6:
                        direction = 1.0 if bias["direction"] == "up" else -1.0
                        magnitude = PARAM_PERTURBATION * bias["confidence"] * direction
                    else:
                        magnitude = PARAM_PERTURBATION * (3.0 if aggressive else 1.0) * random.choice([-1, 1])
                    new_val = max(lo, min(hi, current + current * magnitude))
                    if isinstance(variant[param_key], int):
                        new_val = int(round(new_val))
                    variant[param_key] = round(new_val, 4) if isinstance(new_val, float) else new_val

            variant["_evolver_generation"] = i + 1
            variant["_evolver_parent"] = parent.id
            variants.append(variant)
        return variants

    def _record_lineage(
        self, db: Session, strategy_name: str, parent_id: Optional[int],
        child_id: int, mutation_type: str, params_diff: dict, fitness: float
    ) -> None:
        from backend.models.outcome_tables import EvolutionLineage

        parent_gen = 0
        if parent_id:
            parent_lin = db.query(EvolutionLineage).filter(
                EvolutionLineage.child_experiment_id == parent_id
            ).first()
            parent_gen = (parent_lin.generation or 0) if parent_lin else 0

        db.add(EvolutionLineage(
            parent_experiment_id=parent_id,
            child_experiment_id=child_id,
            strategy_name=strategy_name,
            generation=parent_gen + 1,
            mutation_type=mutation_type,
            child_fitness=fitness,
            params_diff=params_diff,
        ))

    def _record_lineage_for_promoted(self, db: Session) -> None:
        from backend.models.outcome_tables import EvolutionLineage

        promoted = db.query(ExperimentRecord).filter(
            ExperimentRecord.status == ExperimentStatus.LIVE_PROMOTED.value,
        ).all()
        if not promoted:
            return

        exp_ids = [exp.id for exp in promoted]
        lineages = db.query(EvolutionLineage).filter(
            EvolutionLineage.child_experiment_id.in_(exp_ids)
        ).all()
        lineage_map = {lin.child_experiment_id: lin for lin in lineages}

        for exp in promoted:
            existing = lineage_map.get(exp.id)
            if existing and existing.child_fitness is None:
                existing.child_fitness = exp.shadow_win_rate or 0.0
