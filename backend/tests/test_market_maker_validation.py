"""Tests for market maker inventory validation."""
from __future__ import annotations

import pytest

from backend.strategies.market_maker import MarketMakerStrategy


@pytest.fixture
def mm():
    return MarketMakerStrategy()


def test_inventory_clamped_high(mm):
    spread = mm.calculate_spread(volatility=0.1, inventory_pct=1.5)
    assert spread > 0


def test_inventory_clamped_low(mm):
    spread = mm.calculate_spread(volatility=0.1, inventory_pct=-0.5)
    assert spread > 0


def test_zero_quote_size_raises(mm):
    params = {**mm.default_params, "quote_size": 0}
    with pytest.raises(ValueError, match="quote_size must be > 0"):
        mm.calculate_quotes(mid_price=0.5, spread=0.04, inventory_pct=0.0, params=params)


def test_valid_inputs(mm):
    spread = mm.calculate_spread(volatility=0.1, inventory_pct=0.5)
    assert spread > 0
    quotes = mm.calculate_quotes(mid_price=0.5, spread=spread, inventory_pct=0.5)
    assert 0.01 <= quotes.bid_price <= 0.99
    assert 0.01 <= quotes.ask_price <= 0.99
