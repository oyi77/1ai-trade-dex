"""Tests for AGI scheduler job wiring (self-review, research pipeline)."""
import inspect
import json
from datetime import datetime, timezone
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.models.database import GenomeRegistry, ShadowTrade


class TestSelfReviewJob:
    @pytest.mark.asyncio
    async def test_self_review_job_calls_run_review_cycle(self):
        mock_reviewer = MagicMock()
        mock_reviewer.run_review_cycle = AsyncMock(
            return_value={
                "win_rates": [],
                "postmortems": [],
                "degradation_alerts": [],
                "diary_posted": False,
            }
        )

        with patch("backend.ai.self_review.SelfReview", return_value=mock_reviewer):
            from backend.core.agi_jobs import self_review_job

            await self_review_job()

        mock_reviewer.run_review_cycle.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_self_review_job_handles_errors_gracefully(self):
        with patch(
            "backend.ai.self_review.SelfReview",
            side_effect=RuntimeError("DB down"),
        ):
            from backend.core.agi_jobs import self_review_job

            await self_review_job()

    @pytest.mark.asyncio
    async def test_self_review_job_reports_alert_counts(self):
        mock_reviewer = MagicMock()
        mock_reviewer.run_review_cycle = AsyncMock(
            return_value={
                "win_rates": [{"factor": "strategy", "groups": {}}],
                "postmortems": [MagicMock(), MagicMock()],
                "degradation_alerts": [MagicMock()],
                "diary_posted": True,
            }
        )

        with patch("backend.ai.self_review.SelfReview", return_value=mock_reviewer):
            from backend.core.agi_jobs import self_review_job

            await self_review_job()

        mock_reviewer.run_review_cycle.assert_awaited_once()


class TestResearchPipelineJob:
    @pytest.mark.asyncio
    async def test_research_pipeline_job_calls_run_research_cycle(self):
        mock_pipeline = MagicMock()
        mock_pipeline.run_research_cycle = AsyncMock(return_value=[])

        with patch(
            "backend.research.pipeline.ResearchPipeline",
            return_value=mock_pipeline,
        ):
            from backend.core.agi_jobs import research_pipeline_job

            await research_pipeline_job()

        mock_pipeline.run_research_cycle.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_research_pipeline_job_handles_errors_gracefully(self):
        with patch(
            "backend.research.pipeline.ResearchPipeline",
            side_effect=RuntimeError("Feed down"),
        ):
            from backend.core.agi_jobs import research_pipeline_job

            await research_pipeline_job()

    @pytest.mark.asyncio
    async def test_research_pipeline_job_returns_items(self):
        mock_item = MagicMock()
        mock_pipeline = MagicMock()
        mock_pipeline.run_research_cycle = AsyncMock(
            return_value=[mock_item, mock_item, mock_item]
        )

        with patch(
            "backend.research.pipeline.ResearchPipeline",
            return_value=mock_pipeline,
        ):
            from backend.core.agi_jobs import research_pipeline_job

            await research_pipeline_job()

        mock_pipeline.run_research_cycle.assert_awaited_once()


class TestAGIJobConfigDefaults:
    def test_self_review_settings_exist(self):
        from backend.config import Settings

        s = Settings()
        assert hasattr(s, "SELF_REVIEW_ENABLED")
        assert hasattr(s, "SELF_REVIEW_INTERVAL_DAYS")
        assert s.SELF_REVIEW_ENABLED is True
        assert s.SELF_REVIEW_INTERVAL_DAYS >= 1

    def test_research_pipeline_settings_exist(self):
        from backend.config import Settings

        s = Settings()
        assert hasattr(s, "RESEARCH_PIPELINE_ENABLED")
        assert hasattr(s, "RESEARCH_PIPELINE_INTERVAL_HOURS")
        assert s.RESEARCH_PIPELINE_ENABLED is True
        assert s.RESEARCH_PIPELINE_INTERVAL_HOURS >= 1

    def test_evolution_scheduler_settings_exist(self):
        from backend.config import Settings

        s = Settings()
        assert s.AGI_MUTATION_INTERVAL_HOURS == 6
        assert s.AGI_CROSSOVER_INTERVAL_HOURS == 24
        assert s.AGI_POPULATION_SIZE == 20
        assert s.AGI_MUTATION_RATE == 0.10


class TestSchedulerImportsAGIJobs:
    def test_agi_jobs_importable(self):
        from backend.core.agi_jobs import self_review_job, research_pipeline_job

        assert inspect.iscoroutinefunction(self_review_job)
        assert inspect.iscoroutinefunction(research_pipeline_job)


def _chromosomes_payload():
    return {
        "perception": {},
        "cognition": {
            "entry_logic": {
                "trigger_type": "threshold_cross",
                "conditions": [{"indicator": "rsi", "operator": ">", "value": 70.0}],
            },
            "exit_logic": {"trigger_type": "time_based"},
            "market_selector": {},
        },
        "execution": {},
        "risk": {},
        "meta": {"mutation_rate": 0.1},
    }


def _add_genome(db, *, archetype: str, sharpe: float, strategy_name: str) -> GenomeRegistry:
    now = datetime.now(timezone.utc)
    genome = GenomeRegistry(
        genome_id=str(uuid4()),
        strategy_name=strategy_name,
        archetype=archetype,
        version="1.0.0",
        stage="DRAFT",
        lineage_json=json.dumps({"parent_genome_ids": [], "generation": 1, "creator": "human"}),
        chromosomes_json=json.dumps(_chromosomes_payload()),
        fitness_json=json.dumps(
            {
                "sharpe_ratio": sharpe,
                "win_rate": 0.6,
                "profit_factor": 1.7,
                "max_drawdown_pct": 0.1,
                "alpha_per_trade": 0.05,
                "capital_rotation_efficiency": 0.7,
                "total_trades": 20,
            }
        ),
        created_at=now,
        updated_at=now,
        stage_entered_at=now,
    )
    db.add(genome)
    db.commit()
    return genome


class TestEvolutionJobs:
    def test_mutation_cycle_creates_offspring(self, db, monkeypatch):
        from backend.application.agi import evolution_jobs as jobs

        parent = _add_genome(db, archetype="momentum_surfer", sharpe=0.9, strategy_name="parent-a")
        monkeypatch.setattr(jobs.settings, "EVOLUTION_ENGINE_ENABLED", True)
        monkeypatch.setattr(jobs.settings, "AGI_POPULATION_SIZE", 20)
        monkeypatch.setattr(jobs.settings, "AGI_MUTATION_RATE", 0.10)
        monkeypatch.setattr(jobs, "publish_event", lambda *_args, **_kwargs: None)

        counter = {"i": 0}

        def _fake_mutate(genome, **kwargs):
            counter["i"] += 1
            child = genome.model_copy(deep=True)
            child.genome_id = f"{genome.genome_id}-mut-{counter['i']}"
            return child, [{"type": "hyperparameter"}]

        monkeypatch.setattr(jobs, "mutate_genome", _fake_mutate)

        created = jobs.run_mutation_cycle()
        assert created == 2  # 20 * 0.10
        children = db.query(GenomeRegistry).filter(GenomeRegistry.genome_id.like(f"{parent.genome_id}-mut-%")).all()
        assert len(children) == 2

    def test_crossover_cycle_creates_hybrids(self, db, monkeypatch):
        from backend.application.agi import evolution_jobs as jobs

        _add_genome(db, archetype="momentum_surfer", sharpe=0.95, strategy_name="a")
        _add_genome(db, archetype="market_maker", sharpe=0.91, strategy_name="b")
        monkeypatch.setattr(jobs.settings, "EVOLUTION_ENGINE_ENABLED", True)
        monkeypatch.setattr(jobs.settings, "AGI_POPULATION_SIZE", 8)
        monkeypatch.setattr(jobs, "publish_event", lambda *_args, **_kwargs: None)

        def _fake_crossover(parent_a, parent_b):
            child = parent_a.model_copy(deep=True)
            child.genome_id = f"{parent_a.genome_id}-{parent_b.genome_id}-child"
            return child

        monkeypatch.setattr(jobs, "crossover_genomes", _fake_crossover)

        created = jobs.run_crossover_cycle()
        assert created == 1
        child = (
            db.query(GenomeRegistry)
            .filter(GenomeRegistry.strategy_name.like("cross-%"))
            .first()
        )
        assert child is not None
        assert child.archetype.startswith("hybrid_")

    def test_update_fitness_from_shadow_recalculates_metrics(self, db, monkeypatch):
        from backend.application.agi import evolution_jobs as jobs

        genome = _add_genome(db, archetype="market_maker", sharpe=0.2, strategy_name="fitness-target")
        monkeypatch.setattr(jobs.settings, "EVOLUTION_ENGINE_ENABLED", True)
        db.add_all(
            [
                ShadowTrade(
                    genome_id=genome.genome_id,
                    market_ticker="m1",
                    direction="up",
                    entry_price=0.4,
                    size=10,
                    pnl=4.0,
                    predicted_outcome=0.7,
                    actual_outcome=1.0,
                    accuracy_score=0.3,
                    settled=True,
                ),
                ShadowTrade(
                    genome_id=genome.genome_id,
                    market_ticker="m2",
                    direction="down",
                    entry_price=0.6,
                    size=10,
                    pnl=-2.0,
                    predicted_outcome=0.4,
                    actual_outcome=0.0,
                    accuracy_score=0.4,
                    settled=True,
                ),
            ]
        )
        db.commit()

        updated = jobs.update_fitness_from_shadow()
        assert updated == 1

        refreshed = db.query(GenomeRegistry).filter(GenomeRegistry.genome_id == genome.genome_id).first()
        metrics = json.loads(refreshed.fitness_json)
        assert metrics["total_trades"] == 2
        assert metrics["win_rate"] == 0.5

    def test_rebalance_population_adds_missing_archetypes(self, db, monkeypatch):
        from backend.application.agi import evolution_jobs as jobs

        _add_genome(db, archetype="market_maker", sharpe=0.9, strategy_name="donor")
        monkeypatch.setattr(jobs.settings, "EVOLUTION_ENGINE_ENABLED", True)
        monkeypatch.setattr(jobs.settings, "AGI_POPULATION_SIZE", 3)
        monkeypatch.setattr(jobs, "publish_event", lambda *_args, **_kwargs: None)

        counter = {"i": 0}

        def _fake_mutate(genome, **kwargs):
            counter["i"] += 1
            child = genome.model_copy(deep=True)
            child.genome_id = f"{genome.genome_id}-rebalance-{counter['i']}"
            return child, []

        monkeypatch.setattr(jobs, "mutate_genome", _fake_mutate)

        created = jobs.rebalance_population()
        assert created == 2
        rebalanced = db.query(GenomeRegistry).filter(GenomeRegistry.strategy_name.like("rebalance-%")).all()
        assert len(rebalanced) == 2
        assert all(g.archetype != "market_maker" for g in rebalanced)


class TestEvolutionSchedulerRegistration:
    def test_scheduler_uses_configured_evolution_intervals(self):
        import os
        workspace_root = os.environ.get("GITHUB_WORKSPACE", os.path.join(os.path.dirname(__file__), "../.."))
        scheduler_file = os.path.join(workspace_root, "backend", "core", "scheduling", "scheduler.py")
        if not os.path.exists(scheduler_file):
            scheduler_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../core/scheduler.py"))
        with open(scheduler_file, "r", encoding="utf-8") as f:
            source = f.read()

        assert "IntervalTrigger(hours=settings.AGI_MUTATION_INTERVAL_HOURS)" in source
        assert "IntervalTrigger(hours=settings.AGI_CROSSOVER_INTERVAL_HOURS)" in source
        assert "id=\"evolution_mutation_cycle\"" in source
        assert "id=\"evolution_crossover_cycle\"" in source
        assert "id=\"evolution_population_rebalance\"" in source

