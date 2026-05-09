import json
from datetime import datetime, timezone

from backend.application.agi.evolution_jobs import shadow_validation_job
from backend.models.database import GenomeRegistry, ShadowTrade
from backend.models.genome_registry import GenomePerformance


def _make_genome(genome_id: str, stage: str) -> GenomeRegistry:
    return GenomeRegistry(
        genome_id=genome_id,
        strategy_name=f"strategy_{genome_id}",
        archetype="test",
        version="1.0.0",
        stage=stage,
        lineage_json="{}",
        chromosomes_json="{}",
        fitness_json="{}",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        stage_entered_at=datetime.now(timezone.utc),
    )


def _add_shadow_trades(db, genome_id: str, pnls: list[float], size: float = 100.0) -> None:
    for idx, pnl in enumerate(pnls):
        db.add(
            ShadowTrade(
                market_ticker=f"{genome_id}-MKT-{idx}",
                direction="up",
                entry_price=0.5,
                size=size,
                model_probability=0.6,
                strategy="test_strategy",
                settled=True,
                settlement_value=1.0 if pnl > 0 else 0.0,
                pnl=pnl,
                genome_id=genome_id,
                timestamp=datetime.now(timezone.utc),
            )
        )


def test_shadow_feedback_loop_promotes_shadow_to_paper_and_updates_fitness(db, monkeypatch):
    monkeypatch.setattr("backend.application.agi.evolution_jobs.settings.EVOLUTION_ENGINE_ENABLED", True)

    genome_id = "genome-shadow-pass"
    db.add(_make_genome(genome_id, "SHADOW"))
    _add_shadow_trades(db, genome_id, [12.0] * 15 + [-4.0] * 5)
    db.commit()

    shadow_validation_job()

    refreshed = db.query(GenomeRegistry).filter_by(genome_id=genome_id).first()
    assert refreshed is not None
    assert refreshed.stage == "PAPER"

    fitness = json.loads(refreshed.fitness_json)
    assert fitness["total_trades"] == 20
    assert fitness["win_rate"] == 0.75
    assert fitness["sharpe_ratio"] >= 0.5

    perf = db.query(GenomePerformance).filter_by(genome_id=genome_id).first()
    assert perf is not None
    assert perf.total_trades == 20
    assert perf.winning_trades == 15
    assert perf.losing_trades == 5


def test_shadow_feedback_loop_promotes_paper_to_live(db, monkeypatch):
    monkeypatch.setattr("backend.application.agi.evolution_jobs.settings.EVOLUTION_ENGINE_ENABLED", True)

    genome_id = "genome-paper-pass"
    db.add(_make_genome(genome_id, "PAPER"))
    _add_shadow_trades(db, genome_id, [10.0] * 40 + [-2.0] * 10)
    db.commit()

    shadow_validation_job()

    refreshed = db.query(GenomeRegistry).filter_by(genome_id=genome_id).first()
    assert refreshed is not None
    assert refreshed.stage == "LIVE"


def test_shadow_feedback_loop_auto_kills_bad_drawdown(db, monkeypatch):
    monkeypatch.setattr("backend.application.agi.evolution_jobs.settings.EVOLUTION_ENGINE_ENABLED", True)

    genome_id = "genome-kill-dd"
    db.add(_make_genome(genome_id, "SHADOW"))
    _add_shadow_trades(db, genome_id, [50.0, -100.0], size=100.0)
    db.commit()

    shadow_validation_job()

    refreshed = db.query(GenomeRegistry).filter_by(genome_id=genome_id).first()
    assert refreshed is not None
    assert refreshed.stage == "GRAVEYARD"
