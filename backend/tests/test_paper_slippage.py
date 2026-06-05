import pytest

from backend.core.paper_slippage import PaperSlippageSimulator


class TestPaperSlippageProfitabilityGuards:
    def test_rejects_trade_consuming_too_much_known_depth(self, monkeypatch):
        simulator = PaperSlippageSimulator()

        def fake_setting(key, default, db=None):
            overrides = {
                "PAPER_SLIPPAGE_BPS": 20.0,
                "PAPER_RANDOM_SLIPPAGE": False,
                "PAPER_MAX_DEPTH_CONSUMPTION_PCT": 0.20,
            }
            return overrides.get(key, default)

        monkeypatch.setattr(simulator, "_get_setting", fake_setting)

        result = simulator.simulate_fill(
            entry_price=0.05,
            size=30.0,
            direction="BUY",
            market_ticker="thin-longshot",
            orderbook_depth_usd=100.0,
        )

        assert result["rejected"] is True
        assert result["effective_size"] == 0.0
        assert result["rejection_reason"] == "DEPTH_CONSUMPTION_LIMIT"

    def test_longshot_prices_receive_extra_slippage_penalty(self, monkeypatch):
        simulator = PaperSlippageSimulator()

        def fake_setting(key, default, db=None):
            overrides = {
                "PAPER_SLIPPAGE_BPS": 20.0,
                "PAPER_MIN_SLIPPAGE_BPS": 5.0,
                "PAPER_SIZE_IMPACT_FACTOR": 0.0,
                "PAPER_RANDOM_SLIPPAGE": False,
                "PAPER_LONGSHOT_SLIPPAGE_MULTIPLIER": 3.0,
                "PAPER_LONGSHOT_PRICE_THRESHOLD": 0.10,
            }
            return overrides.get(key, default)

        monkeypatch.setattr(simulator, "_get_setting", fake_setting)

        normal = simulator.simulate_fill(
            entry_price=0.50,
            size=10.0,
            direction="BUY",
            market_ticker="normal-market",
            orderbook_depth_usd=1000.0,
        )
        longshot = simulator.simulate_fill(
            entry_price=0.02,
            size=10.0,
            direction="BUY",
            market_ticker="longshot-market",
            orderbook_depth_usd=1000.0,
        )

        assert normal["rejected"] is False
        assert longshot["rejected"] is False
        assert longshot["slippage_bps"] == pytest.approx(
            normal["slippage_bps"] * 3.0
        )
        assert longshot["fill_price"] == pytest.approx(0.026)
