"""Unit tests for Trade Analyzer (Wave 4a)."""

import pytest
from datetime import datetime, timezone
from backend.ai.trade_analyzer import TradeAnalyzer
from backend.models.database import Trade
import backend.models.database as _db_mod


@pytest.fixture
def analyzer():
    return TradeAnalyzer()


@pytest.fixture
def db_session():
    db = _db_mod.SessionLocal()
    yield db
    db.query(Trade).delete()
    db.commit()
    db.close()


def create_test_trade(
    db,
    entry_price=0.50,
    settlement_value=1.0,
    size=100.0,
    confidence=0.8,
    edge_at_entry=0.15,
    strategy="test_strategy",
    direction="up",
    **kwargs
):
    if settlement_value is not None and entry_price is not None:
        if direction == "up":
            result = "win" if settlement_value > entry_price else "loss"
        else:
            result = "win" if settlement_value < entry_price else "loss"
    else:
        result = "pending"

    trade = Trade(
        market_ticker="TEST-MARKET",
        platform="polymarket",
        direction=direction,
        entry_price=entry_price,
        size=size,
        timestamp=kwargs.get("timestamp", datetime.now(timezone.utc)),
        settled=settlement_value is not None,
        settlement_time=datetime.now(timezone.utc) if settlement_value is not None else None,
        settlement_value=settlement_value,
        result=result,
        model_probability=0.65,
        market_price_at_entry=entry_price,
        edge_at_entry=edge_at_entry,
        confidence=confidence,
        strategy=strategy,
        pnl=kwargs.get("pnl"),
        slippage=kwargs.get("slippage"),
        fee=kwargs.get("fee"),
    )
    db.add(trade)
    db.commit()
    db.refresh(trade)
    return trade


def test_analyze_profitable_trade(analyzer, db_session):
    trade = create_test_trade(
        db_session,
        entry_price=0.50,
        settlement_value=1.0,
        size=100.0,
        confidence=0.85,
        edge_at_entry=0.20,
        direction="up"
    )

    result = analyzer.analyze_trade(trade.id)

    assert result is not None
    assert result["trade_id"] == trade.id
    assert result["pnl"] == 50.0
    assert "why_profitable" in result
    assert "high_confidence_signal" in result["key_factors"]
    assert "strong_edge" in result["key_factors"]
    assert 0.0 <= result["edge"] <= 1.0
    assert 0.0 <= result["confidence"] <= 1.0
    assert result["confidence"] == 0.85


def test_analyze_unprofitable_trade(analyzer, db_session):
    trade = create_test_trade(
        db_session,
        entry_price=0.60,
        settlement_value=0.0,
        size=100.0,
        confidence=0.40,
        edge_at_entry=0.03,
        direction="up"
    )

    result = analyzer.analyze_trade(trade.id)

    assert result is not None
    assert result["trade_id"] == trade.id
    assert result["pnl"] == -60.0
    assert "why_unprofitable" in result
    assert "low_confidence_signal" in result["key_factors"]
    assert "weak_edge" in result["key_factors"]
    assert 0.0 <= result["edge"] <= 1.0
    assert 0.0 <= result["confidence"] <= 1.0


def test_analyze_neutral_trade(analyzer, db_session):
    trade = create_test_trade(
        db_session,
        entry_price=0.50,
        settlement_value=0.50,
        size=100.0,
        confidence=0.60,
        edge_at_entry=0.10,
        direction="up"
    )

    result = analyzer.analyze_trade(trade.id)

    assert result is not None
    assert result["pnl"] == 0.0
    assert "why_unprofitable" in result


def test_analyze_nonexistent_trade(analyzer):
    result = analyzer.analyze_trade(99999)
    assert result is None


def test_analyze_trade_missing_entry_price(analyzer, db_session):
    trade = create_test_trade(
        db_session,
        entry_price=None,
        settlement_value=1.0,
        size=100.0
    )

    result = analyzer.analyze_trade(trade.id)
    assert result is None


def test_analyze_trade_zero_quantity(analyzer, db_session):
    trade = create_test_trade(
        db_session,
        entry_price=0.50,
        settlement_value=1.0,
        size=0.0
    )

    result = analyzer.analyze_trade(trade.id)

    assert result is not None
    assert result["pnl"] == 0.0
    assert "zero_quantity" in result["key_factors"]
    assert "Zero quantity trade" in result["why_unprofitable"]


def test_analyze_trade_null_quantity(analyzer, db_session):
    trade = create_test_trade(
        db_session,
        entry_price=0.50,
        settlement_value=1.0,
        size=None
    )

    result = analyzer.analyze_trade(trade.id)

    assert result is not None
    assert result["pnl"] == 0.0
    assert "zero_quantity" in result["key_factors"]


def test_analyze_trade_history_empty_list(analyzer):
    result = analyzer.analyze_trade_history([])
    assert result == {}


def test_analyze_trade_history_single_trade(analyzer, db_session):
    trade = create_test_trade(
        db_session,
        entry_price=0.50,
        settlement_value=1.0,
        size=100.0
    )

    result = analyzer.analyze_trade_history([trade])

    assert result["total_trades"] == 1
    assert result["winning_trades"] == 1
    assert result["losing_trades"] == 0
    assert result["win_rate"] == 1.0
    assert result["avg_win"] == 50.0
    assert result["avg_loss"] == 0.0


def test_analyze_trade_history_all_losing_trades(analyzer, db_session):
    trades = [
        create_test_trade(
            db_session,
            entry_price=0.60,
            settlement_value=0.0,
            size=100.0,
            confidence=0.30,
            edge_at_entry=0.02,
            direction="up"
        )
        for _ in range(3)
    ]

    result = analyzer.analyze_trade_history(trades)

    assert result["total_trades"] == 3
    assert result["winning_trades"] == 0
    assert result["losing_trades"] == 3
    assert result["win_rate"] == 0.0
    assert result["avg_win"] == 0.0
    assert result["avg_loss"] == -60.0
    assert len(result["common_loss_factors"]) > 0
    assert result["common_win_factors"] == []


def test_analyze_trade_history_mixed_trades(analyzer, db_session):
    winning_trade = create_test_trade(
        db_session,
        entry_price=0.50,
        settlement_value=1.0,
        size=100.0,
        confidence=0.85,
        direction="up"
    )

    losing_trade = create_test_trade(
        db_session,
        entry_price=0.60,
        settlement_value=0.0,
        size=100.0,
        confidence=0.40,
        direction="up"
    )

    neutral_trade = create_test_trade(
        db_session,
        entry_price=0.50,
        settlement_value=0.50,
        size=100.0,
        confidence=0.60,
        direction="up"
    )

    trades = [winning_trade, losing_trade, neutral_trade]
    result = analyzer.analyze_trade_history(trades)

    assert result["total_trades"] == 3
    assert result["winning_trades"] == 1
    assert result["losing_trades"] == 2
    assert 0.0 <= result["win_rate"] <= 1.0
    assert 0.0 <= result["edge_score"] <= 1.0


def test_analyze_trade_history_with_outlier(analyzer, db_session):
    normal_trades = [
        create_test_trade(
            db_session,
            entry_price=0.50,
            settlement_value=0.51,
            size=100.0
        )
        for _ in range(5)
    ]

    outlier_trade = create_test_trade(
        db_session,
        entry_price=0.50,
        settlement_value=1.0,
        size=1000.0
    )

    trades = normal_trades + [outlier_trade]
    result = analyzer.analyze_trade_history(trades)

    assert result["total_trades"] == 6
    assert result["winning_trades"] == 6


def test_analyze_trade_history_identical_timestamps(analyzer, db_session):
    timestamp = datetime.now(timezone.utc)

    trades = [
        create_test_trade(
            db_session,
            entry_price=0.50,
            settlement_value=0.55,
            size=100.0,
            timestamp=timestamp
        )
        for _ in range(3)
    ]

    result = analyzer.analyze_trade_history(trades)

    assert result["total_trades"] == 3
    assert result["winning_trades"] == 3


def test_analyze_trade_history_skip_invalid_trades(analyzer, db_session):
    valid_trade = create_test_trade(
        db_session,
        entry_price=0.50,
        settlement_value=1.0,
        size=100.0
    )

    invalid_trade_no_entry = create_test_trade(
        db_session,
        entry_price=None,
        settlement_value=1.0,
        size=100.0
    )

    invalid_trade_zero_size = create_test_trade(
        db_session,
        entry_price=0.50,
        settlement_value=1.0,
        size=0.0
    )

    trades = [valid_trade, invalid_trade_no_entry, invalid_trade_zero_size]
    result = analyzer.analyze_trade_history(trades)

    assert result["total_trades"] == 1
    assert result["winning_trades"] == 1


def test_analyze_trade_with_stored_pnl(analyzer, db_session):
    trade = create_test_trade(
        db_session,
        entry_price=0.50,
        settlement_value=1.0,
        size=100.0,
        pnl=15.0
    )

    result = analyzer.analyze_trade(trade.id)

    assert result["pnl"] == 15.0


def test_analyze_trade_with_slippage(analyzer, db_session):
    trade = create_test_trade(
        db_session,
        entry_price=0.60,
        settlement_value=0.0,
        size=100.0,
        slippage=0.05,
        confidence=0.40,
        direction="up"
    )

    result = analyzer.analyze_trade(trade.id)

    assert "high_slippage" in result["key_factors"]


def test_analyze_trade_with_high_fees(analyzer, db_session):
    trade = create_test_trade(
        db_session,
        entry_price=0.60,
        settlement_value=0.0,
        size=100.0,
        fee=50.0,
        confidence=0.40,
        direction="up"
    )

    result = analyzer.analyze_trade(trade.id)

    assert "high_fees" in result["key_factors"]


def test_common_factors_extraction(analyzer):
    factors = [
        "high_confidence_signal",
        "strong_edge",
        "high_confidence_signal",
        "good_entry_price",
        "strong_edge",
        "strong_edge",
    ]

    common = analyzer._get_common_factors(factors)

    assert "strong_edge" in common
    assert "high_confidence_signal" in common
    assert len(common) <= 5


def test_outlier_detection(analyzer):
    pnls = [1.0, 1.5, 2.0, 1.8, 100.0]

    outliers = analyzer._detect_outliers(pnls)

    assert len(outliers) > 0
    assert 4 in outliers


def test_outlier_detection_no_outliers(analyzer):
    pnls = [1.0, 1.5, 2.0, 1.8, 2.2]

    outliers = analyzer._detect_outliers(pnls)

    assert len(outliers) == 0


def test_outlier_detection_small_sample(analyzer):
    pnls = [1.0, 2.0]

    outliers = analyzer._detect_outliers(pnls)

    assert len(outliers) == 0


def test_analyze_trade_history_common_win_factors(analyzer, db_session):
    trades = [
        create_test_trade(
            db_session,
            entry_price=0.50,
            settlement_value=1.0,
            size=100.0,
            confidence=0.85,
            edge_at_entry=0.20,
            strategy="momentum",
            direction="up"
        )
        for _ in range(5)
    ]

    result = analyzer.analyze_trade_history(trades)

    assert "high_confidence_signal" in result["common_win_factors"]
    assert "strong_edge" in result["common_win_factors"]


def test_edge_score_calculation(analyzer, db_session):
    trades = [
        create_test_trade(
            db_session,
            entry_price=0.50,
            settlement_value=1.0,
            size=100.0,
            edge_at_entry=0.80,
            direction="up"
        ),
        create_test_trade(
            db_session,
            entry_price=0.50,
            settlement_value=1.0,
            size=100.0,
            edge_at_entry=0.60,
            direction="up"
        ),
    ]

    result = analyzer.analyze_trade_history(trades)

    assert 0.0 <= result["edge_score"] <= 1.0
    assert result["edge_score"] > 0.5
