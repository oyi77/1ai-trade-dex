"""Tests for fee and slippage tracking in Trade model and execution pipeline."""

import pytest
from backend.models.database import Trade, SessionLocal


@pytest.fixture
def test_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.query(Trade).delete()
        db.commit()
        db.close()


def test_trade_model_has_fee_and_slippage_fields(test_db):
    trade = Trade(
        market_ticker="BTC-UP-5M",
        platform="polymarket",
        direction="up",
        entry_price=0.65,
        size=100.0,
        model_probability=0.70,
        market_price_at_entry=0.65,
        edge_at_entry=0.05,
        trading_mode="paper",
        fee=2.0,
        slippage=0.002,
    )

    test_db.add(trade)
    test_db.commit()

    retrieved = test_db.query(Trade).filter_by(market_ticker="BTC-UP-5M").first()
    assert retrieved is not None
    assert retrieved.fee == 2.0
    assert retrieved.slippage == 0.002


def test_trade_model_nullable_fee_and_slippage(test_db):
    trade = Trade(
        market_ticker="BTC-DOWN-5M",
        platform="polymarket",
        direction="down",
        entry_price=0.35,
        size=50.0,
        model_probability=0.60,
        market_price_at_entry=0.35,
        edge_at_entry=0.25,
        trading_mode="paper",
    )

    test_db.add(trade)
    test_db.commit()

    retrieved = test_db.query(Trade).filter_by(market_ticker="BTC-DOWN-5M").first()
    assert retrieved is not None
    assert retrieved.fee is None
    assert retrieved.slippage is None


def test_slippage_calculation_positive():
    entry_price = 0.50
    fill_price = 0.52
    slippage = fill_price - entry_price
    assert abs(slippage - 0.02) < 1e-9


def test_slippage_calculation_negative():
    entry_price = 0.50
    fill_price = 0.48
    slippage = fill_price - entry_price
    assert abs(slippage - (-0.02)) < 1e-9


def test_slippage_calculation_zero():
    entry_price = 0.50
    fill_price = 0.50
    slippage = fill_price - entry_price
    assert slippage == 0.0


def test_fee_tracking_paper_mode(test_db):
    trade = Trade(
        market_ticker="WEATHER-TEMP-NYC",
        platform="polymarket",
        direction="yes",
        entry_price=0.75,
        size=25.0,
        model_probability=0.80,
        market_price_at_entry=0.75,
        edge_at_entry=0.05,
        trading_mode="paper",
        fee=None,
        slippage=None,
    )

    test_db.add(trade)
    test_db.commit()

    retrieved = test_db.query(Trade).filter_by(market_ticker="WEATHER-TEMP-NYC").first()
    assert retrieved.fee is None
    assert retrieved.slippage is None


def test_fee_tracking_live_mode(test_db):
    trade = Trade(
        market_ticker="BTC-UP-15M",
        platform="polymarket",
        direction="up",
        entry_price=0.60,
        size=100.0,
        model_probability=0.65,
        market_price_at_entry=0.60,
        edge_at_entry=0.05,
        trading_mode="live",
        clob_order_id="order_123",
        fee=2.0,
        slippage=0.005,
    )

    test_db.add(trade)
    test_db.commit()

    retrieved = test_db.query(Trade).filter_by(clob_order_id="order_123").first()
    assert retrieved.fee == 2.0
    assert retrieved.slippage == 0.005


def test_multiple_trades_with_different_fees(test_db):
    trades = [
        Trade(
            market_ticker=f"MARKET-{i}",
            platform="polymarket",
            direction="up",
            entry_price=0.50,
            size=10.0 * i,
            model_probability=0.60,
            market_price_at_entry=0.50,
            edge_at_entry=0.10,
            trading_mode="testnet",
            fee=0.2 * i,
            slippage=0.001 * i,
        )
        for i in range(1, 4)
    ]

    for trade in trades:
        test_db.add(trade)
    test_db.commit()

    all_trades = test_db.query(Trade).filter(Trade.market_ticker.like("MARKET-%")).order_by(Trade.id).all()
    assert len(all_trades) == 3
    assert abs(all_trades[0].fee - 0.2) < 1e-9
    assert abs(all_trades[1].fee - 0.4) < 1e-9
    assert abs(all_trades[2].fee - 0.6) < 1e-9


def test_query_trades_by_slippage_threshold(test_db):
    trades = [
        Trade(
            market_ticker="LOW-SLIP",
            platform="polymarket",
            direction="up",
            entry_price=0.50,
            size=100.0,
            model_probability=0.60,
            market_price_at_entry=0.50,
            edge_at_entry=0.10,
            trading_mode="live",
            slippage=0.001,
        ),
        Trade(
            market_ticker="HIGH-SLIP",
            platform="polymarket",
            direction="down",
            entry_price=0.50,
            size=100.0,
            model_probability=0.60,
            market_price_at_entry=0.50,
            edge_at_entry=0.10,
            trading_mode="live",
            slippage=0.05,
        ),
    ]

    for trade in trades:
        test_db.add(trade)
    test_db.commit()

    high_slippage = test_db.query(Trade).filter(Trade.slippage > 0.01).all()
    assert len(high_slippage) == 1
    assert high_slippage[0].market_ticker == "HIGH-SLIP"
