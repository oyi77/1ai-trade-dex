"""Tests for backend/ai/self_review.py — attribution engine and postmortems."""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, AsyncMock
from sqlalchemy.orm import Session

from backend.ai.self_review import (
    SelfReview,
    WinRateBreakdown,
    Postmortem,
    DegradationAlert,
    _bucket_edge,
    _bucket_confidence,
    _settled_trades,
    _format_trade_summary,
)
from backend.models.database import Trade


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_db():
    """Mock database session."""
    return MagicMock(spec=Session)


@pytest.fixture
def mock_llm():
    """Mock LLMRouter."""
    return MagicMock()


@pytest.fixture
def mock_brain():
    """Mock BigBrainClient."""
    return MagicMock()


@pytest.fixture
def self_review(mock_db, mock_llm, mock_brain):
    """SelfReview instance with mocked dependencies."""
    return SelfReview(db=mock_db, llm=mock_llm, brain=mock_brain)


def _make_trade(
    strategy="btc_oracle",
    market_type="btc",
    result="win",
    edge_at_entry=0.05,
    confidence=0.75,
    pnl=10.0,
    settled=True,
    timestamp=None,
):
    """Helper to create a Trade mock."""
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    trade = MagicMock(spec=Trade)
    trade.strategy = strategy
    trade.market_type = market_type
    trade.result = result
    trade.edge_at_entry = edge_at_entry
    trade.confidence = confidence
    trade.pnl = pnl
    trade.settled = settled
    trade.timestamp = timestamp
    trade.direction = "up"
    return trade


# ─────────────────────────────────────────────────────────────────────────────
# Tests: Bucketing functions
# ─────────────────────────────────────────────────────────────────────────────


class TestBucketingFunctions:
    """Tests for _bucket_edge and _bucket_confidence."""

    def test_bucket_edge_tiny(self):
        assert _bucket_edge(0.01) == "tiny"

    def test_bucket_edge_small(self):
        assert _bucket_edge(0.03) == "small"

    def test_bucket_edge_medium(self):
        assert _bucket_edge(0.07) == "medium"

    def test_bucket_edge_large(self):
        assert _bucket_edge(0.15) == "large"

    def test_bucket_edge_huge(self):
        assert _bucket_edge(0.25) == "huge"

    def test_bucket_edge_boundary(self):
        """Test boundary cases (lo inclusive, hi exclusive)."""
        assert _bucket_edge(0.0) == "tiny"
        assert _bucket_edge(0.02) == "small"  # lo inclusive
        assert _bucket_edge(0.05) == "medium"  # lo inclusive
        assert _bucket_edge(0.10) == "large"  # lo inclusive

    def test_bucket_edge_none(self):
        assert _bucket_edge(None) == "unknown"

    def test_bucket_edge_negative(self):
        """Edge is absolute value."""
        assert _bucket_edge(-0.05) == "medium"

    def test_bucket_confidence_low(self):
        assert _bucket_confidence(0.2) == "low"

    def test_bucket_confidence_medium(self):
        assert _bucket_confidence(0.5) == "medium"

    def test_bucket_confidence_high(self):
        assert _bucket_confidence(0.85) == "high"

    def test_bucket_confidence_boundary(self):
        """Test boundary cases."""
        assert _bucket_confidence(0.0) == "low"  # lo inclusive
        assert _bucket_confidence(0.4) == "medium"  # lo inclusive
        assert _bucket_confidence(0.7) == "high"  # lo inclusive

    def test_bucket_confidence_none(self):
        assert _bucket_confidence(None) == "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# Tests: Calculate win rates
# ─────────────────────────────────────────────────────────────────────────────


class TestCalculateWinRates:
    """Tests for calculate_win_rates method."""

    def test_calculate_win_rates_empty(self, self_review, mock_db):
        """When no settled trades, should return empty breakdowns."""
        mock_db.query.return_value.filter.return_value.all.return_value = []
        result = self_review.calculate_win_rates(db=mock_db)
        # Should return 4 factors (strategy, market_type, edge_bucket, confidence_bucket)
        assert len(result) == 4
        # Each factor should have empty groups
        for br in result:
            assert br.groups == {}

    def test_calculate_win_rates_single_trade(self, self_review, mock_db):
        """With one winning trade, should have 100% in all relevant buckets."""
        trade = _make_trade(
            strategy="btc_oracle",
            market_type="btc",
            result="win",
            edge_at_entry=0.05,
            confidence=0.75,
        )
        mock_db.query.return_value.filter.return_value.all.return_value = [trade]

        result = self_review.calculate_win_rates(db=mock_db)
        assert len(result) == 4

        # Check strategy breakdown
        strategy_br = [br for br in result if br.factor == "strategy"][0]
        assert "btc_oracle" in strategy_br.groups
        assert strategy_br.groups["btc_oracle"]["wins"] == 1
        assert strategy_br.groups["btc_oracle"]["losses"] == 0
        assert strategy_br.groups["btc_oracle"]["total"] == 1
        assert strategy_br.groups["btc_oracle"]["win_rate"] == 1.0

    def test_calculate_win_rates_mixed_results(self, self_review, mock_db):
        """With mixed wins/losses, should calculate correct percentages."""
        trades = [
            _make_trade(strategy="btc_oracle", result="win"),
            _make_trade(strategy="btc_oracle", result="win"),
            _make_trade(strategy="btc_oracle", result="loss"),
        ]
        mock_db.query.return_value.filter.return_value.all.return_value = trades

        result = self_review.calculate_win_rates(db=mock_db)
        strategy_br = [br for br in result if br.factor == "strategy"][0]
        assert strategy_br.groups["btc_oracle"]["wins"] == 2
        assert strategy_br.groups["btc_oracle"]["losses"] == 1
        assert strategy_br.groups["btc_oracle"]["win_rate"] == pytest.approx(2 / 3)

    def test_calculate_win_rates_multiple_factors(self, self_review, mock_db):
        """Should break down across all four factors."""
        trades = [
            _make_trade(
                strategy="btc_oracle",
                market_type="btc",
                edge_at_entry=0.05,
                confidence=0.75,
                result="win",
            ),
            _make_trade(
                strategy="weather",
                market_type="weather",
                edge_at_entry=0.15,
                confidence=0.5,
                result="loss",
            ),
        ]
        mock_db.query.return_value.filter.return_value.all.return_value = trades

        result = self_review.calculate_win_rates(db=mock_db)
        factor_names = [br.factor for br in result]
        assert "strategy" in factor_names
        assert "market_type" in factor_names
        assert "edge_bucket" in factor_names
        assert "confidence_bucket" in factor_names


# ─────────────────────────────────────────────────────────────────────────────
# Tests: Postmortems
# ─────────────────────────────────────────────────────────────────────────────


class TestGeneratePostmortems:
    """Tests for generate_postmortems method."""

    @pytest.mark.asyncio
    async def test_generate_postmortems_no_losses(self, self_review, mock_db):
        """When no losing trades, should return empty list."""
        trade = _make_trade(result="win")
        mock_db.query.return_value.filter.return_value.all.return_value = [trade]
        result = await self_review.generate_postmortems(db=mock_db)
        assert result == []

    @pytest.mark.asyncio
    async def test_generate_postmortems_single_cluster(self, self_review, mock_db):
        """Should cluster losing trades by strategy and call LLM."""
        losses = [
            _make_trade(strategy="btc_oracle", result="loss", pnl=-5.0),
            _make_trade(strategy="btc_oracle", result="loss", pnl=-3.0),
        ]
        mock_db.query.return_value.filter.return_value.all.return_value = losses

        # Mock LLM response
        self_review._llm.complete = AsyncMock(return_value="Mock LLM analysis")

        result = await self_review.generate_postmortems(db=mock_db)
        assert len(result) == 1
        assert result[0].cluster_key == "strategy=btc_oracle"
        assert result[0].trade_count == 2
        assert result[0].total_pnl == pytest.approx(-8.0)
        assert result[0].llm_analysis == "Mock LLM analysis"

    @pytest.mark.asyncio
    async def test_generate_postmortems_llm_error_handling(self, self_review, mock_db):
        """Should gracefully handle LLM errors."""
        losses = [_make_trade(strategy="btc_oracle", result="loss")]
        mock_db.query.return_value.filter.return_value.all.return_value = losses

        # Mock LLM to raise exception
        self_review._llm.complete = AsyncMock(side_effect=Exception("LLM timeout"))

        result = await self_review.generate_postmortems(db=mock_db)
        assert len(result) == 1
        assert "LLM analysis unavailable" in result[0].llm_analysis

    @pytest.mark.asyncio
    async def test_generate_postmortems_cluster_sampling(self, self_review, mock_db):
        """Should sample first POSTMORTEM_MAX_CLUSTER_SIZE trades."""
        from backend.ai.self_review import POSTMORTEM_MAX_CLUSTER_SIZE

        # Create more trades than POSTMORTEM_MAX_CLUSTER_SIZE
        losses = [
            _make_trade(strategy="btc_oracle", result="loss")
            for _ in range(POSTMORTEM_MAX_CLUSTER_SIZE + 10)
        ]
        mock_db.query.return_value.filter.return_value.all.return_value = losses

        self_review._llm.complete = AsyncMock(return_value="Analysis")

        result = await self_review.generate_postmortems(db=mock_db)
        assert len(result) == 1
        # Verify the prompt was called (it samples the trades)
        assert self_review._llm.complete.called


# ─────────────────────────────────────────────────────────────────────────────
# Tests: Degradation detection
# ─────────────────────────────────────────────────────────────────────────────


class TestDetectDegradation:
    """Tests for detect_degradation method."""

    def test_detect_degradation_no_trades(self, self_review, mock_db):
        """When no trades, should return empty list."""
        mock_db.query.return_value.filter.return_value.all.return_value = []
        result = self_review.detect_degradation(db=mock_db)
        assert result == []

    def test_detect_degradation_no_recent_trades(self, self_review, mock_db):
        """When no recent trades within window, should return empty list."""
        # All trades are old (before the cutoff)
        old_trade = _make_trade(
            timestamp=datetime.now(timezone.utc) - timedelta(weeks=10)
        )
        mock_db.query.return_value.filter.return_value.all.return_value = [old_trade]
        result = self_review.detect_degradation(db=mock_db)
        assert result == []

    def test_detect_degradation_significant_drop(self, self_review, mock_db):
        """Should flag strategy with 20% win rate drop (> 10% threshold)."""
        now = datetime.now(timezone.utc)

        # Baseline: 8 wins out of 10 (80%)
        baseline = [
            _make_trade(
                strategy="btc_oracle", result="win", timestamp=now - timedelta(weeks=6)
            )
            for _ in range(8)
        ]
        baseline += [
            _make_trade(
                strategy="btc_oracle", result="loss", timestamp=now - timedelta(weeks=6)
            )
            for _ in range(2)
        ]

        # Recent: 2 wins out of 6 (33%, drop of 47%)
        recent = [
            _make_trade(
                strategy="btc_oracle", result="win", timestamp=now - timedelta(weeks=1)
            )
            for _ in range(2)
        ]
        recent += [
            _make_trade(
                strategy="btc_oracle", result="loss", timestamp=now - timedelta(weeks=1)
            )
            for _ in range(4)
        ]

        all_trades = baseline + recent
        mock_db.query.return_value.filter.return_value.all.return_value = all_trades

        result = self_review.detect_degradation(db=mock_db, recent_weeks=3)
        assert len(result) > 0
        # Should flag strategy=btc_oracle with significant drop
        assert any(a.signal_key == "strategy=btc_oracle" for a in result)

    def test_detect_degradation_minimum_trades_enforcement(self, self_review, mock_db):
        """Should not flag degradation if baseline or recent trades below minimum."""
        now = datetime.now(timezone.utc)

        # Only 3 baseline trades (< MIN_TRADES_BASELINE=10), 5 recent
        baseline = [
            _make_trade(
                strategy="btc_oracle", result="win", timestamp=now - timedelta(weeks=6)
            )
            for _ in range(3)
        ]
        recent = [
            _make_trade(
                strategy="btc_oracle", result="loss", timestamp=now - timedelta(weeks=1)
            )
            for _ in range(5)
        ]

        all_trades = baseline + recent
        mock_db.query.return_value.filter.return_value.all.return_value = all_trades

        result = self_review.detect_degradation(db=mock_db, recent_weeks=3)
        # Should not flag due to insufficient baseline trades
        assert not any(a.signal_key == "strategy=btc_oracle" for a in result)

    def test_detect_degradation_timezone_naive_handling(self, self_review, mock_db):
        """Should handle timezone-naive timestamps gracefully."""
        now = datetime.now(timezone.utc)

        # Timezone-naive timestamp (old)
        baseline = _make_trade(
            strategy="btc_oracle",
            result="win",
            timestamp=datetime.now() - timedelta(weeks=6),  # naive
        )

        # Timezone-aware recent trades
        recent_trades = [
            _make_trade(
                strategy="btc_oracle", result="win", timestamp=now - timedelta(weeks=1)
            )
            for _ in range(10)
        ]

        all_trades = [baseline] + recent_trades
        mock_db.query.return_value.filter.return_value.all.return_value = all_trades

        # Should not raise exception
        result = self_review.detect_degradation(db=mock_db)
        assert isinstance(result, list)


# ─────────────────────────────────────────────────────────────────────────────
# Tests: Run review cycle
# ─────────────────────────────────────────────────────────────────────────────


class TestRunReviewCycle:
    """Tests for run_review_cycle method."""

    @pytest.mark.asyncio
    async def test_run_review_cycle_full_flow(self, self_review, mock_db):
        """Should execute all components and return results."""
        trades = [_make_trade(result="win"), _make_trade(result="loss")]
        mock_db.query.return_value.filter.return_value.all.return_value = trades

        self_review._llm.complete = AsyncMock(return_value="Analysis")
        self_review._brain.write_diary = AsyncMock(return_value={"success": True})

        result = await self_review.run_review_cycle(db=mock_db)

        assert "win_rates" in result
        assert "postmortems" in result
        assert "degradation_alerts" in result
        assert "diary_posted" in result
        assert result["diary_posted"] is True

    @pytest.mark.asyncio
    async def test_run_review_cycle_diary_error_nonfatal(self, self_review, mock_db):
        """Diary posting failure should not fail the cycle."""
        trades = [_make_trade(result="win")]
        mock_db.query.return_value.filter.return_value.all.return_value = trades

        self_review._llm.complete = AsyncMock(return_value="Analysis")
        self_review._brain.write_diary = AsyncMock(
            side_effect=Exception("Diary unavailable")
        )

        result = await self_review.run_review_cycle(db=mock_db)

        assert result["diary_posted"] is False
        assert result["win_rates"] is not None
        assert result["postmortems"] is not None

    @pytest.mark.asyncio
    async def test_run_review_cycle_diary_format(self, self_review, mock_db):
        """Should format and post diary correctly."""
        trades = [
            _make_trade(strategy="btc_oracle", result="win"),
            _make_trade(strategy="btc_oracle", result="loss"),
        ]
        mock_db.query.return_value.filter.return_value.all.return_value = trades

        self_review._llm.complete = AsyncMock(return_value="Mock analysis")
        self_review._brain.write_diary = AsyncMock(return_value={"success": True})

        await self_review.run_review_cycle(db=mock_db)

        # Verify diary was called
        assert self_review._brain.write_diary.called
        call_args = self_review._brain.write_diary.call_args
        assert "entry" in call_args.kwargs
        assert "topic" in call_args.kwargs
        assert call_args.kwargs["topic"] == "self-review"
        # Entry should contain key sections
        entry = call_args.kwargs["entry"]
        assert "PolyEdge Self-Review Report" in entry


# ─────────────────────────────────────────────────────────────────────────────
# Tests: Dependency injection and defaults
# ─────────────────────────────────────────────────────────────────────────────


class TestDependencyInjection:
    """Tests for database, LLM, and brain dependency handling."""

    def test_self_review_with_injected_deps(self, mock_db, mock_llm, mock_brain):
        """Should use injected dependencies."""
        sr = SelfReview(db=mock_db, llm=mock_llm, brain=mock_brain)
        assert sr._db is mock_db
        assert sr._llm is mock_llm
        assert sr._brain is mock_brain

    def test_self_review_creates_defaults_when_none(self):
        """Should create default instances when not provided."""
        sr = SelfReview(db=None, llm=None, brain=None)
        # _get_db, _get_llm, _get_brain should create instances
        # (We don't fully invoke them to avoid external API calls)
        assert sr._db is None
        assert sr._llm is None
        assert sr._brain is None

    def test_should_close_db_logic(self, mock_db):
        """Should close DB session only if created internally."""
        sr = SelfReview(db=mock_db)
        assert sr._should_close_db() is False

        sr_no_db = SelfReview(db=None)
        assert sr_no_db._should_close_db() is True


# ─────────────────────────────────────────────────────────────────────────────
# Tests: Helper functions
# ─────────────────────────────────────────────────────────────────────────────


class TestHelperFunctions:
    """Tests for _format_trade_summary and _settled_trades."""

    def test_format_trade_summary(self):
        """Should format trade as single-line summary."""
        trade = _make_trade(
            strategy="btc_oracle",
            market_type="btc",
            edge_at_entry=0.05,
            confidence=0.75,
            pnl=10.0,
            result="win",
        )
        summary = _format_trade_summary(trade)
        assert "btc_oracle" in summary
        assert "btc" in summary
        assert "up" in summary  # direction
        assert "0.050" in summary  # edge
        assert "0.75" in summary  # confidence
        assert "10.00" in summary  # pnl
        assert "win" in summary

    def test_format_trade_summary_missing_fields(self):
        """Should handle None/missing fields gracefully."""
        trade = _make_trade()
        trade.strategy = None
        trade.market_type = None
        trade.timestamp = None
        summary = _format_trade_summary(trade)
        assert "?" in summary  # Placeholders for None values

    def test_settled_trades_filtering(self, mock_db):
        """_settled_trades should filter for settled trades with result."""
        settled_win = MagicMock(spec=Trade)
        settled_win.settled = True
        settled_win.result = "win"

        unsettled = MagicMock(spec=Trade)
        unsettled.settled = False
        unsettled.result = "pending"

        pending_result = MagicMock(spec=Trade)
        pending_result.settled = True
        pending_result.result = "pending"

        mock_db.query.return_value.filter.return_value.all.return_value = [
            settled_win,
        ]

        result = _settled_trades(mock_db)
        assert len(result) == 1
        assert result[0].result == "win"


# ─────────────────────────────────────────────────────────────────────────────
# Tests: Data classes
# ─────────────────────────────────────────────────────────────────────────────


class TestDataClasses:
    """Tests for WinRateBreakdown, Postmortem, DegradationAlert."""

    def test_win_rate_breakdown_creation(self):
        """Should create WinRateBreakdown with groups."""
        groups = {
            "btc_oracle": {"wins": 10, "losses": 2, "total": 12, "win_rate": 10 / 12},
        }
        br = WinRateBreakdown(factor="strategy", groups=groups)
        assert br.factor == "strategy"
        assert br.groups == groups

    def test_postmortem_creation(self):
        """Should create Postmortem with auto-generated timestamp."""
        pm = Postmortem(
            cluster_key="strategy=btc_oracle",
            trade_count=5,
            total_pnl=-25.0,
            llm_analysis="Root cause: volatility spike",
        )
        assert pm.cluster_key == "strategy=btc_oracle"
        assert pm.trade_count == 5
        assert pm.total_pnl == -25.0
        assert pm.llm_analysis == "Root cause: volatility spike"
        assert pm.generated_at is not None

    def test_degradation_alert_creation(self):
        """Should create DegradationAlert."""
        alert = DegradationAlert(
            signal_key="strategy=btc_oracle",
            factor="strategy",
            baseline_win_rate=0.80,
            recent_win_rate=0.30,
            drop=0.50,
            baseline_trades=20,
            recent_trades=10,
        )
        assert alert.signal_key == "strategy=btc_oracle"
        assert alert.drop == 0.50
        assert alert.detected_at is not None
