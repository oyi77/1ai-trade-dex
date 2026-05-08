"""Tests for Activity Timeline to Stats Pipeline Integration."""

import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models.database import Base, ActivityLog, Trade, Signal, StrategyProposal
from backend.core.stats_correlator import StatsCorrelator, TimelineCorrelation


@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def correlator():
    return StatsCorrelator(correlation_window_hours=24)


@pytest.fixture
def sample_activities(test_db):
    now = datetime.now(timezone.utc)

    activities = [
        ActivityLog(
            timestamp=now - timedelta(days=10),
            strategy_name="btc_momentum",
            decision_type="entry",
            data={"market": "BTC_UP", "price": 50000},
            confidence_score=0.75,
            mode="paper"
        ),
        ActivityLog(
            timestamp=now - timedelta(days=5),
            strategy_name="btc_oracle",
            decision_type="entry",
            data={"market": "BTC_DOWN", "price": 48000},
            confidence_score=0.85,
            mode="paper"
        ),
        ActivityLog(
            timestamp=now - timedelta(days=2),
            strategy_name="weather_emos",
            decision_type="hold",
            data={"market": "TEMP_NYC", "forecast": 72},
            confidence_score=0.60,
            mode="paper"
        )
    ]

    for activity in activities:
        test_db.add(activity)

    test_db.commit()
    return activities


@pytest.fixture
def sample_trades(test_db):
    now = datetime.now(timezone.utc)

    trades = [
        Trade(
            market_ticker="BTC_UP",
            platform="polymarket",
            direction="up",
            entry_price=0.55,
            size=100.0,
            timestamp=now - timedelta(days=12),
            settled=True,
            result="win",
            pnl=25.0,
            trading_mode="paper"
        ),
        Trade(
            market_ticker="BTC_UP",
            platform="polymarket",
            direction="up",
            entry_price=0.60,
            size=100.0,
            timestamp=now - timedelta(days=11),
            settled=True,
            result="loss",
            pnl=-15.0,
            trading_mode="paper"
        ),
        Trade(
            market_ticker="BTC_DOWN",
            platform="polymarket",
            direction="down",
            entry_price=0.45,
            size=150.0,
            timestamp=now - timedelta(days=4),
            settled=True,
            result="win",
            pnl=40.0,
            trading_mode="paper"
        ),
        Trade(
            market_ticker="BTC_DOWN",
            platform="polymarket",
            direction="down",
            entry_price=0.50,
            size=120.0,
            timestamp=now - timedelta(days=3),
            settled=True,
            result="win",
            pnl=30.0,
            trading_mode="paper"
        ),
        Trade(
            market_ticker="TEMP_NYC",
            platform="polymarket",
            direction="up",
            entry_price=0.65,
            size=80.0,
            timestamp=now - timedelta(days=1),
            settled=True,
            result="loss",
            pnl=-10.0,
            trading_mode="paper"
        )
    ]

    for trade in trades:
        test_db.add(trade)

    test_db.commit()
    return trades


@pytest.fixture
def sample_signals(test_db):
    now = datetime.now(timezone.utc)

    signals = [
        Signal(
            market_ticker="BTC_UP",
            platform="polymarket",
            timestamp=now - timedelta(days=12),
            direction="up",
            model_probability=0.65,
            market_price=0.55,
            edge=0.10,
            confidence=0.70,
            kelly_fraction=0.05,
            suggested_size=100.0,
            sources={"momentum": 0.65},
            reasoning="Strong upward momentum",
            executed=True,
            outcome_correct=True,
            settlement_value=1.0,
            settled_at=now - timedelta(days=11)
        ),
        Signal(
            market_ticker="BTC_DOWN",
            platform="polymarket",
            timestamp=now - timedelta(days=4),
            direction="down",
            model_probability=0.75,
            market_price=0.45,
            edge=0.30,
            confidence=0.85,
            kelly_fraction=0.08,
            suggested_size=150.0,
            sources={"debate": 0.75},
            reasoning="Debate consensus: bearish",
            executed=True,
            outcome_correct=True,
            settlement_value=1.0,
            settled_at=now - timedelta(days=3)
        )
    ]

    for signal in signals:
        test_db.add(signal)

    test_db.commit()
    return signals


@pytest.fixture
def sample_proposals(test_db):
    now = datetime.now(timezone.utc)

    proposals = [
        StrategyProposal(
            strategy_name="btc_momentum",
            change_details={"threshold": 0.05, "window": 15},
            expected_impact="Increase win rate by 5%",
            admin_decision="approved",
            executed_at=now - timedelta(days=8),
            created_at=now - timedelta(days=9)
        ),
        StrategyProposal(
            strategy_name="btc_oracle",
            change_details={"confidence_min": 0.75},
            expected_impact="Reduce false positives",
            admin_decision="approved",
            executed_at=now - timedelta(days=6),
            created_at=now - timedelta(days=7)
        )
    ]

    for proposal in proposals:
        test_db.add(proposal)

    test_db.commit()
    return proposals


def test_feature_2_activity_to_trade_correlation(test_db, correlator, sample_activities, sample_trades):
    impacts = correlator.get_feature_impact(db=test_db, feature_id="feature_2")

    assert len(impacts) == 1
    impact = impacts[0]

    assert impact.feature_id == "feature_2"
    assert impact.feature_name == "Activity Timeline"
    assert impact.event_count == 3
    assert impact.sample_size_before >= 0
    assert impact.sample_size_after >= 0
    assert impact.win_rate_before >= 0.0
    assert impact.win_rate_after >= 0.0
    assert impact.confidence_level > 0.0


def test_feature_3_debate_to_signal_accuracy(test_db, correlator, sample_activities, sample_signals, sample_trades):
    impacts = correlator.get_feature_impact(db=test_db, feature_id="feature_3")

    assert len(impacts) == 1
    impact = impacts[0]

    assert impact.feature_id == "feature_3"
    assert impact.feature_name == "Debate Engine"
    assert impact.event_count >= 0
    assert impact.win_rate_before >= 0.0
    assert impact.win_rate_after >= 0.0


def test_feature_4_proposal_to_strategy_pnl(test_db, correlator, sample_proposals, sample_trades):
    impacts = correlator.get_feature_impact(db=test_db, feature_id="feature_4")

    assert len(impacts) == 1
    impact = impacts[0]

    assert impact.feature_id == "feature_4"
    assert impact.feature_name == "Proposal System"
    assert impact.event_count == 2
    assert impact.pnl_before is not None
    assert impact.pnl_after is not None
    assert impact.pnl_delta is not None


def test_win_rate_delta_calculation(test_db, correlator, sample_activities, sample_trades):
    impacts = correlator.get_feature_impact(db=test_db, feature_id="feature_2")

    if impacts:
        impact = impacts[0]
        expected_delta = impact.win_rate_after - impact.win_rate_before
        assert abs(impact.win_rate_delta - expected_delta) < 0.001


def test_sharpe_ratio_calculation(test_db, correlator, sample_activities, sample_trades):
    impacts = correlator.get_feature_impact(db=test_db, feature_id="feature_2")

    if impacts:
        impact = impacts[0]
        if impact.sharpe_ratio_before is not None and impact.sharpe_ratio_after is not None:
            assert impact.sharpe_ratio_delta is not None
        else:
            assert impact.sample_size_before < 2 or impact.sample_size_after < 2


def test_pnl_impact_timeline(test_db, correlator, sample_activities, sample_trades):
    impacts = correlator.get_feature_impact(db=test_db, feature_id="feature_2")

    if impacts:
        impact = impacts[0]
        assert impact.pnl_before is not None
        assert impact.pnl_after is not None
        assert impact.pnl_delta == impact.pnl_after - impact.pnl_before


def test_date_range_filtering(test_db, correlator, sample_activities, sample_trades):
    now = datetime.now(timezone.utc)
    start_date = now - timedelta(days=7)
    end_date = now - timedelta(days=3)

    impacts = correlator.get_feature_impact(
        db=test_db,
        feature_id="feature_2",
        date_range=(start_date, end_date)
    )

    assert isinstance(impacts, list)


def test_metric_type_filtering(test_db, correlator, sample_activities, sample_trades):
    impacts = correlator.get_feature_impact(
        db=test_db,
        feature_id="feature_2",
        metric_type="win_rate"
    )

    assert isinstance(impacts, list)


def test_activity_correlations_basic(test_db, correlator, sample_activities, sample_trades):
    correlations = correlator.get_activity_correlations(db=test_db)

    assert isinstance(correlations, list)

    for corr in correlations:
        assert isinstance(corr, TimelineCorrelation)
        assert corr.activity_id > 0
        assert corr.activity_timestamp is not None
        assert corr.activity_type in ["entry", "exit", "hold", "adjustment"]
        assert corr.strategy_name is not None
        assert corr.trades_after >= 0
        assert corr.wins_after >= 0
        assert 0.0 <= corr.win_rate_after <= 1.0
        assert 0.0 <= corr.correlation_score <= 1.0


def test_activity_correlations_strategy_filter(test_db, correlator, sample_activities, sample_trades):
    correlations = correlator.get_activity_correlations(
        db=test_db,
        strategy_name="btc_momentum"
    )

    assert isinstance(correlations, list)

    for corr in correlations:
        assert corr.strategy_name == "btc_momentum"


def test_activity_correlations_limit(test_db, correlator, sample_activities, sample_trades):
    correlations = correlator.get_activity_correlations(db=test_db, limit=2)

    assert len(correlations) <= 2


def test_correlation_score_range(test_db, correlator, sample_activities, sample_trades):
    correlations = correlator.get_activity_correlations(db=test_db)

    for corr in correlations:
        assert 0.0 <= corr.correlation_score <= 1.0


def test_empty_database(test_db, correlator):
    impacts = correlator.get_feature_impact(db=test_db)
    assert impacts == []

    correlations = correlator.get_activity_correlations(db=test_db)
    assert correlations == []


def test_confidence_level_calculation(test_db, correlator, sample_activities, sample_trades):
    impacts = correlator.get_feature_impact(db=test_db, feature_id="feature_2")

    if impacts:
        impact = impacts[0]
        assert 0.0 <= impact.confidence_level <= 1.0

        total_samples = impact.sample_size_before + impact.sample_size_after
        if total_samples < 10:
            assert impact.confidence_level <= 0.5
        elif total_samples >= 100:
            assert impact.confidence_level >= 0.7


def test_all_features_impact(test_db, correlator, sample_activities, sample_trades, sample_signals, sample_proposals):
    impacts = correlator.get_feature_impact(db=test_db)

    assert isinstance(impacts, list)
    assert len(impacts) <= 3

    feature_ids = [impact.feature_id for impact in impacts]
    for fid in feature_ids:
        assert fid in ["feature_2", "feature_3", "feature_4"]
