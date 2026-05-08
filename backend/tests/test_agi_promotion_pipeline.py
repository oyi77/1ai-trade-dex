"""Tests for AGI Promotion Pipeline — manual approval gate, promotion, retirement."""
from backend.core.agi_promotion_pipeline import AGIPromotionPipeline
from backend.core.experiment_runner import ExperimentRunner


class TestAGIPromotionPipeline:
    def test_submit_experiment(self):
        pipeline = AGIPromotionPipeline()
        result = pipeline.submit_experiment("1")
        assert result.success is True
        assert result.to_status == "shadow"

    def test_promote_to_paper(self):
        runner = ExperimentRunner()
        experiment = runner.run_shadow_experiment("test_strategy", duration_days=1)
        pipeline = AGIPromotionPipeline(runner)
        result = pipeline.promote_to_paper(str(experiment.experiment_id))
        assert result.from_status == "shadow"
        assert result.to_status == "paper"

    def test_promote_to_live_without_manual_approval_rejected(self):
        pipeline = AGIPromotionPipeline()
        result = pipeline.promote_to_live("1", manual_approval=False)
        assert result.success is False
        assert "manual approval" in result.reason.lower() or "ADR-006" in result.reason

    def test_promote_to_live_with_manual_approval(self):
        runner = ExperimentRunner()
        experiment = runner.run_shadow_experiment("test_strategy", duration_days=1)
        pipeline = AGIPromotionPipeline(runner)
        result = pipeline.promote_to_live(str(experiment.experiment_id), manual_approval=True)
        assert result.from_status == "paper"
        assert result.to_status == "live"

    def test_retire_experiment(self):
        pipeline = AGIPromotionPipeline()
        result = pipeline.retire_experiment("1", reason="poor performance")
        assert result.success is True
        assert result.to_status == "retired"

    def test_promotion_log_tracks_all_promotions(self):
        runner = ExperimentRunner()
        experiment = runner.run_shadow_experiment("test_strategy", duration_days=1)
        pipeline = AGIPromotionPipeline(runner)
        pipeline.promote_to_paper(str(experiment.experiment_id))
        pipeline.promote_to_live(str(experiment.experiment_id), manual_approval=True)
        log = pipeline.get_promotion_log()
        assert len(log) == 2

    def test_evaluate_experiment(self):
        runner = ExperimentRunner()
        experiment = runner.run_shadow_experiment("test_strategy", duration_days=1)
        pipeline = AGIPromotionPipeline(runner)
        result = pipeline.evaluate_experiment(str(experiment.experiment_id))
        assert result is not None
        assert result.experiment_id == str(experiment.experiment_id)

    def test_submit_nonexistent_experiment(self):
        pipeline = AGIPromotionPipeline()
        result = pipeline.submit_experiment("nonexistent")
        assert result.success is True

    def test_promotion_criteria_constants(self):
        assert AGIPromotionPipeline.MIN_TRADES_SHADOW == 100
        assert AGIPromotionPipeline.MIN_DAYS_SHADOW == 7
        assert AGIPromotionPipeline.MIN_WIN_RATE_SHADOW == 0.45
        assert AGIPromotionPipeline.MAX_DRAWDOWN_SHADOW == 0.25
        assert AGIPromotionPipeline.MIN_TRADES_PAPER == 50
        assert AGIPromotionPipeline.MIN_DAYS_PAPER == 3
        assert AGIPromotionPipeline.MIN_WIN_RATE_PAPER == 0.50
