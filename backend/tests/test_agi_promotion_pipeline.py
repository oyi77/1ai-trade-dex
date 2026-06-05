"""Tests for AGI Promotion Pipeline — manual approval gate, promotion, retirement."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.core.agi_promotion_pipeline import AGIPromotionPipeline
from backend.core.experiment_runner import ExperimentRunner
from backend.models.database import Base as AppBase, Trade
from backend.models.kg_models import Base as KgBase, ExperimentRecord


def _runner_with_app_tables():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    KgBase.metadata.create_all(engine)
    AppBase.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return ExperimentRunner(session=Session())


def _add_paper_trade(session, strategy_name: str, index: int, pnl: float):
    session.add(
        Trade(
            market_ticker=f"promo-{index}",
            platform="polymarket",
            strategy=strategy_name,
            trading_mode="paper",
            direction="up",
            entry_price=0.5,
            size=10.0,
            timestamp=datetime.now(timezone.utc) + timedelta(minutes=index),
            settled=True,
            result="win" if pnl > 0 else "loss",
            pnl=pnl,
        )
    )


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
        result = pipeline.promote_to_live(
            str(experiment.experiment_id), manual_approval=True
        )
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

    def test_promote_to_live_blocks_outlier_dependent_paper_profit(self):
        runner = _runner_with_app_tables()
        session = runner._session
        experiment = ExperimentRecord(
            name="outlier_exp",
            strategy_name="outlier_strategy",
            strategy_composition={"name": "outlier_strategy"},
            status="shadow",
            shadow_trades=100,
            shadow_win_rate=0.60,
            created_at=datetime.now(timezone.utc) - timedelta(days=10),
        )
        session.add(experiment)
        session.flush()
        for index, pnl in enumerate([100.0] + [-1.0] * 50, start=1):
            _add_paper_trade(session, "outlier_strategy", index, pnl)
        session.commit()

        result = AGIPromotionPipeline(runner).promote_to_live(
            str(experiment.id), manual_approval=True
        )

        assert result.success is False
        assert "Profitability gate failed" in result.reason
        assert "top_trade_pnl_share" in result.reason

    def test_promote_to_live_allows_distributed_paper_edge_after_manual_approval(self):
        runner = _runner_with_app_tables()
        session = runner._session
        experiment = ExperimentRecord(
            name="distributed_exp",
            strategy_name="distributed_strategy",
            strategy_composition={"name": "distributed_strategy"},
            status="shadow",
            shadow_trades=100,
            shadow_win_rate=0.60,
            created_at=datetime.now(timezone.utc) - timedelta(days=10),
        )
        session.add(experiment)
        session.flush()
        for index in range(1, 61):
            pnl = 2.0 if index % 2 else -1.0
            _add_paper_trade(session, "distributed_strategy", index, pnl)
        session.commit()

        result = AGIPromotionPipeline(runner).promote_to_live(
            str(experiment.id), manual_approval=True
        )

        assert result.from_status == "paper"
        assert result.to_status == "live"
