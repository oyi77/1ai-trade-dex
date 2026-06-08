import pytest

from backend.bot.bnb_hack import BnbHackBot
from backend.config import settings
from backend.signals.technical import compute_sma, compute_sma_series


class FakeFeed:
    def __init__(self):
        self.price = 650.0

    async def get_price(self, symbol="BNBUSDT"):
        return self.price

    async def close(self):
        return None


class FakeSignalEngine:
    async def evaluate(self):
        return {
            "action": "buy",
            "confidence": 0.70,
            "price": 650.0,
            "reason": "golden_cross",
            "indicators": {"sma_fast": 651.0, "sma_slow": 649.0},
        }


class FakeExchange:
    def __init__(self):
        self.swaps = []

    async def balance(self):
        return {"tokens": [{"symbol": "USDC", "balance": "34"}]}

    async def swap(self, amount, from_token, to_token, quote_only=False):
        self.swaps.append((amount, from_token, to_token, quote_only))
        return {"success": True, "toAmount": 0.0391}


def test_settings_exposes_bnb_hack_group():
    cfg = settings.bnb_hack

    assert cfg.sma_fast == settings.BNB_HACK_SMA_FAST
    assert cfg.sma_slow == settings.BNB_HACK_SMA_SLOW
    assert cfg.timeframe == settings.BNB_HACK_TIMEFRAME
    assert cfg.wallet_address == settings.TWAK_WALLET_ADDRESS


def test_shared_technical_indicators_validate_inputs():
    assert compute_sma([1.0, 2.0, 3.0], 2) == 2.5
    assert compute_sma_series([1.0, 2.0, 3.0], 2) == [1.0, 1.5, 2.5]

    with pytest.raises(ValueError, match="period must be >= 1"):
        compute_sma([1.0], 0)

    with pytest.raises(ValueError, match="closes must not be empty"):
        compute_sma([], 1)


@pytest.mark.asyncio
async def test_bnb_hack_bot_buys_with_injected_dependencies():
    exchange = FakeExchange()
    bot = BnbHackBot(FakeFeed(), FakeSignalEngine(), exchange)

    result = await bot.tick()

    assert result == "buy (conf: 0.7)"
    assert exchange.swaps == [("25.5", "USDC", "BNB", False)]
    assert "BNB" in bot.state.positions
    assert bot.state.positions["BNB"].amount_usdc == 25.5


@pytest.mark.asyncio
async def test_bnb_hack_bot_respects_daily_loss_limit():
    exchange = FakeExchange()
    bot = BnbHackBot(FakeFeed(), FakeSignalEngine(), exchange)
    bot.state.daily_pnl_usd = -settings.bnb_hack.max_daily_loss_usd

    result = await bot.tick()

    assert result == "daily_loss_limit"
    assert exchange.swaps == []
