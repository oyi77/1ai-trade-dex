"""Tests for exposure_limits — pre-trade validation checklist."""


from backend.core.risk.exposure_limits import PortfolioState, TradeConfig, validate_trade


def _trade(size: float = 20.0, **kwargs) -> TradeConfig:
    defaults = dict(market_id="m1", category="politics", size_usd=size, side="BUY", outcome="YES")
    defaults.update(kwargs)
    return TradeConfig(**defaults)


def _portfolio(**kwargs) -> PortfolioState:
    return PortfolioState(**kwargs)


# 1. Valid trade
def test_valid_trade():
    ok, reason = validate_trade(_trade(20), _portfolio(free_capital=100))
    assert ok is True
    assert reason == "OK"


# 2. Insufficient capital
def test_insufficient_capital():
    ok, reason = validate_trade(_trade(50), _portfolio(free_capital=30))
    assert ok is False
    assert "Insufficient capital" in reason


# 3. Max open positions
def test_max_open_positions():
    ok, reason = validate_trade(_trade(20), _portfolio(free_capital=100, open_positions=5, max_open_positions=5))
    assert ok is False
    assert "Max open positions" in reason


# 4. Max positions in market
def test_max_positions_in_market():
    ok, reason = validate_trade(
        _trade(20),
        _portfolio(free_capital=100, positions_in_market=2, max_per_market=2),
    )
    assert ok is False
    assert "Max positions in market" in reason


# 5. Category exposure limit
def test_category_exposure_limit():
    ok, reason = validate_trade(
        _trade(20),
        _portfolio(free_capital=100, category_exposure_pct=60.0, max_category_pct=0.60),
    )
    assert ok is False
    assert "Category exposure" in reason


# 6. Daily loss limit
def test_daily_loss_limit():
    ok, reason = validate_trade(
        _trade(20),
        _portfolio(free_capital=100, daily_loss_usd=-100, max_daily_loss_usd=100),
    )
    assert ok is False
    assert "Daily loss limit" in reason


# 7. Outside trading hours
def test_outside_trading_hours():
    ok, reason = validate_trade(_trade(20), _portfolio(free_capital=100, trading_hours_allowed=False))
    assert ok is False
    assert "trading hours" in reason


# 8. Position too small
def test_position_too_small():
    ok, reason = validate_trade(_trade(2), _portfolio(free_capital=100, min_position_usd=5))
    assert ok is False
    assert "too small" in reason


# 9. Position too large
def test_position_too_large():
    ok, reason = validate_trade(_trade(100), _portfolio(free_capital=200, max_position_usd=50))
    assert ok is False
    assert "too large" in reason
