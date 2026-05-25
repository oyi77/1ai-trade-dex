"""Tests for MarketMakerStrategy."""

import pytest
from backend.strategies.market_maker import MarketMakerStrategy
from backend.strategies.registry import STRATEGY_REGISTRY

@pytest.fixture
def mm():
    return MarketMakerStrategy()

def test_spread_increases_with_volatility(mm):
    """Higher volatility should produce a wider spread."""
    low_spread = mm.calculate_spread(volatility=0.0, inventory_pct=0.0)
    high_spread = mm.calculate_spread(volatility=0.20, inventory_pct=0.0)
    assert high_spread > low_spread

def test_inventory_skew_reduces_overweight_side(mm):
    """When long (inventory_pct > 0), bid should be pushed below the neutral bid."""
    mid = 0.50
    spread = mm.default_params["base_spread"]

    neutral_quote = mm.calculate_quotes(mid, spread, inventory_pct=0.0)
    long_quote = mm.calculate_quotes(mid, spread, inventory_pct=0.8)

    # Being long skews prices down: bid and ask should be lower than neutral
    assert long_quote.bid_price < neutral_quote.bid_price
    assert long_quote.ask_price < neutral_quote.ask_price

def test_spread_clamped_to_bounds(mm):
    """Spread must never fall below min_spread or exceed max_spread."""
    min_spread = mm.default_params["min_spread"]
    max_spread = mm.default_params["max_spread"]

    # Extreme low volatility + flat inventory -> clamp at min
    spread_low = mm.calculate_spread(volatility=0.0, inventory_pct=0.0)
    assert spread_low >= min_spread

    # Extreme high volatility + extreme inventory -> clamp at max
    spread_high = mm.calculate_spread(volatility=100.0, inventory_pct=1.0)
    assert spread_high <= max_spread

def test_registered_in_strategy_registry():
    """MarketMakerStrategy must appear in STRATEGY_REGISTRY after import."""
    # Import triggers __init_subclass__ auto-registration
    import backend.strategies.market_maker  # noqa: F401

    assert "market_maker" in STRATEGY_REGISTRY
    assert STRATEGY_REGISTRY["market_maker"] is MarketMakerStrategy
