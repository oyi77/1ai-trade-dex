"""Tests for LearningPipeline — ADR-013 trade outcome feedback loop."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from backend.core.learning_pipeline import (
    LearningPipeline,
    LessonExtractor,
    PipelineMetrics,
    TradeLesson,
    get_learning_pipeline,
    set_learning_pipeline,
)
from backend.core.cognitive_core import MockCore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_core():
    return MockCore()


@pytest.fixture
def mock_forensics():
    forensics = MagicMock()
    forensics.analyze_losing_trade = AsyncMock(return_value={
        "root_cause": "low_confidence_signal",
        "confidence": 0.6,
        "contributing_factors": ["signal confidence 48%"],
        "suggestions": ["Raise AUTO_APPROVE_MIN_CONFIDENCE"],
    })
    return forensics


@pytest.fixture
def pipeline(mock_core, mock_forensics):
    return LearningPipeline(
        cognitive_core=mock_core,
        forensics=mock_forensics,
    )


# ---------------------------------------------------------------------------
# PipelineMetrics
# ---------------------------------------------------------------------------

class TestPipelineMetrics:
    def test_initial_state(self):
        m = PipelineMetrics()
        assert m.total_processed == 0
        assert m.lessons_stored == 0
        assert m.avg_processing_ms == 0.0

    def test_to_dict(self):
        m = PipelineMetrics(total_processed=5, lessons_stored=3, total_processing_ms=150.0)
        d = m.to_dict()
        assert d["total_processed"] == 5
        assert d["lessons_stored"] == 3
        assert d["avg_processing_ms"] == 30.0


# ---------------------------------------------------------------------------
# TradeLesson
# ---------------------------------------------------------------------------

class TestTradeLesson:
    def test_to_dict(self):
        lesson = TradeLesson(
            cause="low_confidence_signal: signal confidence 48%",
            effect="lost $25.00",
            confidence=0.6,
            applicability={"strategies": ["btc_oracle"], "root_cause": "low_confidence_signal"},
            source_trade_id=42,
            strategy_name="btc_oracle",
            outcome="loss",
            pnl=-25.0,
        )
        d = lesson.to_dict()
        assert d["source_trade_id"] == 42
        assert d["strategy_name"] == "btc_oracle"
        assert d["outcome"] == "loss"
        assert d["confidence"] == 0.6


# ---------------------------------------------------------------------------
# LessonExtractor
# ---------------------------------------------------------------------------

class TestLessonExtractor:
    def test_extract_from_forensics_loss(self):
        extractor = LessonExtractor()
        result = extractor.extract_from_forensics(
            forensics_result={
                "root_cause": "bad_entry_timing",
                "confidence": 0.7,
                "contributing_factors": ["slippage 3%"],
                "suggestions": ["Add confirmation filter"],
            },
            trade_id=10,
            strategy_name="momentum",
            outcome="loss",
            pnl=-15.0,
            regime="trending",
        )
        assert result is not None
        assert result.source_trade_id == 10
        assert result.outcome == "loss"
        assert "bad_entry_timing" in result.cause
        assert result.applicability["regimes"] == ["trending"]

    def test_extract_from_forensics_low_confidence_returns_none(self):
        extractor = LessonExtractor()
        result = extractor.extract_from_forensics(
            forensics_result={"root_cause": "unknown", "confidence": 0.1},
            trade_id=11,
            strategy_name="momentum",
            outcome="loss",
            pnl=-10.0,
        )
        assert result is None

    def test_extract_from_winning_trade(self):
        extractor = LessonExtractor()
        result = extractor.extract_from_winning_trade(
            trade_id=20,
            strategy_name="btc_oracle",
            pnl=50.0,
            regime="volatile",
            signal_confidence=0.85,
        )
        assert result is not None
        assert result.outcome == "win"
        assert result.pnl == 50.0
        assert result.confidence == 0.85
        assert "btc_oracle" in result.applicability["strategies"]


# ---------------------------------------------------------------------------
# LearningPipeline — full flow
# ---------------------------------------------------------------------------

class TestLearningPipeline:
    @pytest.mark.asyncio
    async def test_process_winning_trade(self, pipeline, mock_core):
        lesson = await pipeline.process_settlement(
            trade_id=1,
            strategy_name="btc_oracle",
            market_id="BTC-UP",
            outcome="win",
            pnl_usd=30.0,
            genome_id=None,
            regime_at_entry="trending",
            signal_confidence=0.8,
        )
        assert lesson is not None
        assert lesson.outcome == "win"
        assert lesson.pnl == 30.0

        # Verify brain storage
        stored = mock_core.recall("trade_1_win", namespace="trade_lessons")
        assert len(stored) == 1
        assert stored[0]["value"]["outcome"] == "win"

        # Verify metrics
        assert pipeline.metrics.total_processed == 1
        assert pipeline.metrics.lessons_stored == 1

    @pytest.mark.asyncio
    async def test_process_losing_trade_with_forensics(self, pipeline, mock_core, mock_forensics):
        lesson = await pipeline.process_settlement(
            trade_id=2,
            strategy_name="momentum",
            market_id="ETH-DOWN",
            outcome="loss",
            pnl_usd=-20.0,
            genome_id=None,
        )
        assert lesson is not None
        assert lesson.outcome == "loss"
        assert lesson.pnl == -20.0
        assert "low_confidence_signal" in lesson.cause

        # Verify forensics was called
        mock_forensics.analyze_losing_trade.assert_called_once_with(2)

        # Verify brain storage
        stored = mock_core.recall("trade_2_loss", namespace="trade_lessons")
        assert len(stored) == 1

    @pytest.mark.asyncio
    async def test_process_no_forensics_engine(self, mock_core):
        """Pipeline works without forensics (wins don't need it)."""
        pipeline = LearningPipeline(cognitive_core=mock_core, forensics=None)
        lesson = await pipeline.process_settlement(
            trade_id=3,
            strategy_name="copy_trader",
            market_id="TEST",
            outcome="win",
            pnl_usd=10.0,
        )
        assert lesson is not None
        assert pipeline.metrics.lessons_stored == 1

    @pytest.mark.asyncio
    async def test_process_no_cognitive_core(self, mock_forensics):
        """Pipeline works without brain (lessons just not stored)."""
        pipeline = LearningPipeline(cognitive_core=None, forensics=mock_forensics)
        lesson = await pipeline.process_settlement(
            trade_id=4,
            strategy_name="momentum",
            market_id="TEST",
            outcome="loss",
            pnl_usd=-15.0,
        )
        assert lesson is not None
        assert pipeline.metrics.lessons_stored == 1  # counted even if not persisted

    @pytest.mark.asyncio
    async def test_forensics_failure_graceful(self, mock_core):
        """Forensics failure doesn't crash the pipeline — still produces a lesson for wins."""
        forensics = MagicMock()
        forensics.analyze_losing_trade = AsyncMock(side_effect=Exception("DB down"))

        pipeline = LearningPipeline(cognitive_core=mock_core, forensics=forensics)
        await pipeline.process_settlement(
            trade_id=5,
            strategy_name="momentum",
            market_id="TEST",
            outcome="loss",
            pnl_usd=-10.0,
        )
        # Forensics failed, so no lesson from forensics extraction (loss without forensics result
        # hits the else branch — marginal/unknown handler)
        assert pipeline.metrics.forensics_errors == 1
        assert pipeline.metrics.total_processed == 1

    @pytest.mark.asyncio
    async def test_brain_failure_graceful(self, mock_forensics):
        """Brain failure doesn't crash the pipeline."""
        core = MagicMock()
        core.remember.side_effect = Exception("Brain offline")

        pipeline = LearningPipeline(cognitive_core=core, forensics=mock_forensics)
        lesson = await pipeline.process_settlement(
            trade_id=6,
            strategy_name="momentum",
            market_id="TEST",
            outcome="loss",
            pnl_usd=-10.0,
        )
        assert lesson is not None  # lesson extracted before brain failure
        assert pipeline.metrics.brain_errors == 1

    @pytest.mark.asyncio
    async def test_metrics_tracking(self, pipeline):
        for i in range(5):
            await pipeline.process_settlement(
                trade_id=100 + i,
                strategy_name="btc_oracle",
                market_id="TEST",
                outcome="win" if i % 2 == 0 else "loss",
                pnl_usd=10.0 if i % 2 == 0 else -5.0,
            )
        assert pipeline.metrics.total_processed == 5
        assert pipeline.metrics.lessons_stored == 5
        assert pipeline.metrics.total_processing_ms > 0

    @pytest.mark.asyncio
    async def test_process_marginal_outcome(self, pipeline, mock_core):
        lesson = await pipeline.process_settlement(
            trade_id=7,
            strategy_name="copy_trader",
            market_id="TEST",
            outcome="marginal",
            pnl_usd=1.0,
        )
        assert lesson is not None
        assert lesson.outcome == "marginal"

    @pytest.mark.asyncio
    async def test_genome_fitness_adjustment_win(self, pipeline):
        """Genome fitness increases on win (mocked DB)."""
        mock_mutex = AsyncMock()
        mock_mutex.__aenter__ = AsyncMock(return_value=None)
        mock_mutex.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.models.database.botstate_mutex", mock_mutex):
            with patch("backend.db.utils.get_db_session") as mock_session:
                mock_genome = MagicMock()
                mock_genome.trade_count = 10
                mock_genome.win_rate = 0.5
                mock_genome.fitness_score = 0.6
                mock_genome.total_pnl = 100.0

                mock_db = MagicMock()
                mock_db.query.return_value.filter.return_value.first.return_value = mock_genome
                mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
                mock_session.return_value.__exit__ = MagicMock(return_value=False)

                await pipeline._adjust_genome_fitness("genome-1", "win", 25.0)

                assert mock_genome.trade_count == 11
                assert mock_genome.fitness_score > 0.6
                assert mock_genome.total_pnl == 125.0

    @pytest.mark.asyncio
    async def test_genome_not_found(self, pipeline):
        """Missing genome is handled gracefully."""
        mock_mutex = AsyncMock()
        mock_mutex.__aenter__ = AsyncMock(return_value=None)
        mock_mutex.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.models.database.botstate_mutex", mock_mutex):
            with patch("backend.db.utils.get_db_session") as mock_session:
                mock_db = MagicMock()
                mock_db.query.return_value.filter.return_value.first.return_value = None
                mock_session.return_value.__enter__ = MagicMock(return_value=mock_db)
                mock_session.return_value.__exit__ = MagicMock(return_value=False)

                # Should not raise
                await pipeline._adjust_genome_fitness("nonexistent", "win", 10.0)
                assert pipeline.metrics.genome_errors == 0  # warning, not error


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

class TestSingleton:
    def test_get_creates_default(self):
        # Reset singleton
        set_learning_pipeline(LearningPipeline())
        p = get_learning_pipeline()
        assert isinstance(p, LearningPipeline)

    def test_set_replaces(self):
        custom = LearningPipeline(cognitive_core=MockCore())
        set_learning_pipeline(custom)
        assert get_learning_pipeline() is custom

    def teardown_method(self):
        # Reset singleton after each test
        set_learning_pipeline(LearningPipeline())
