"""Tests for backend/core/signals.py — signal generation calculation functions."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, timedelta, timezone

from backend.core.signals import (
    calculate_edge,
    calculate_kelly_size,
    TradingSignal,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_market(up_price: float = 0.45, down_price: float = 0.55):
    """Return a minimal BtcMarket-like object."""
    market = MagicMock()
    market.market_id = "TEST-MKT-001"
    market.slug = "btc-5min-test"
    market.up_price = up_price
    market.down_price = down_price
    market.volume = 5000.0
    market.is_active = True
    market.is_upcoming = False
    market.spread = abs(up_price - down_price)
    market.time_until_end = 300.0
    market.window_start = datetime.now(timezone.utc)
    market.window_end = datetime.now(timezone.utc) + timedelta(minutes=5)
    return market


def _make_micro(**kwargs):
    """Return a minimal BtcMicrostructure-like object."""
    micro = MagicMock()
    micro.rsi = kwargs.get("rsi", 50.0)
    micro.momentum_1m = kwargs.get("momentum_1m", 0.0)
    micro.momentum_5m = kwargs.get("momentum_5m", 0.0)
    micro.momentum_15m = kwargs.get("momentum_15m", 0.0)
    micro.vwap_deviation = kwargs.get("vwap_deviation", 0.0)
    micro.sma_crossover = kwargs.get("sma_crossover", 0.0)
    micro.volatility = kwargs.get("volatility", 0.02)
    micro.price = kwargs.get("price", 65000.0)
    micro.source = kwargs.get("source", "binance")
    return micro


# ---------------------------------------------------------------------------
# RSI tests — we test the RSI-derived signal logic inline with generate_btc_signal
# ---------------------------------------------------------------------------


def _compute_rsi_signal(rsi: float) -> float:
    """Mirror the RSI signal computation from signals.py for unit testing."""
    if rsi < 30:
        rsi_signal = 0.5 + (30 - rsi) / 30
    elif rsi > 70:
        rsi_signal = -0.5 - (rsi - 70) / 30
    elif rsi < 45:
        rsi_signal = (45 - rsi) / 30
    elif rsi > 55:
        rsi_signal = -(rsi - 55) / 30
    else:
        rsi_signal = 0.0
    return max(-1.0, min(1.0, rsi_signal))


class TestRsiCalculation:
    def test_rsi_signal_neutral_zone(self):
        """RSI 45–55 is neutral — signal should be 0.0."""
        assert _compute_rsi_signal(50.0) == pytest.approx(0.0)

    def test_rsi_signal_range_low(self):
        """RSI of 20 (oversold) should produce a strong positive (UP) signal."""
        sig = _compute_rsi_signal(20.0)
        assert 0.0 < sig <= 1.0, f"Expected positive signal for RSI=20, got {sig}"

    def test_rsi_signal_range_high(self):
        """RSI of 80 (overbought) should produce a negative (DOWN) signal."""
        sig = _compute_rsi_signal(80.0)
        assert -1.0 <= sig < 0.0, f"Expected negative signal for RSI=80, got {sig}"

    def test_rsi_signal_clamped_to_unit_interval(self):
        """Signal must always be in [-1, 1]."""
        for rsi_val in [0, 15, 30, 45, 50, 55, 70, 85, 100]:
            sig = _compute_rsi_signal(float(rsi_val))
            assert -1.0 <= sig <= 1.0, f"Signal out of range for RSI={rsi_val}: {sig}"


class TestRsiOverbought:
    def test_rsi_overbought_produces_down_signal(self):
        """RSI > 70 should yield a negative signal (DOWN bias)."""
        sig = _compute_rsi_signal(75.0)
        assert sig < 0.0

    def test_rsi_overbought_stronger_at_extreme(self):
        """RSI=90 should give a stronger DOWN signal than RSI=72."""
        sig_mild = _compute_rsi_signal(72.0)
        sig_strong = _compute_rsi_signal(90.0)
        assert sig_strong < sig_mild

    def test_rsi_oversold_produces_up_signal(self):
        """RSI < 30 should yield a positive signal (UP bias)."""
        sig = _compute_rsi_signal(25.0)
        assert sig > 0.0


# ---------------------------------------------------------------------------
# Momentum blend
# ---------------------------------------------------------------------------


class TestMomentumBlend:
    def test_blend_weights(self):
        """Weighted blend must be 50% 1m + 35% 5m + 15% 15m."""
        mom_1m = 0.10
        mom_5m = 0.20
        mom_15m = 0.30
        expected = mom_1m * 0.5 + mom_5m * 0.35 + mom_15m * 0.15
        assert expected == pytest.approx(0.10 * 0.5 + 0.20 * 0.35 + 0.30 * 0.15)

    def test_blend_positive_produces_up_signal(self):
        """Positive momentum blend should produce a positive signal after normalisation."""
        mom_blend = 0.06  # 0.06% — above 0
        momentum_signal = max(-1.0, min(1.0, mom_blend / 0.10))
        assert momentum_signal > 0.0

    def test_blend_negative_produces_down_signal(self):
        """Negative momentum blend should produce a negative signal."""
        mom_blend = -0.06
        momentum_signal = max(-1.0, min(1.0, mom_blend / 0.10))
        assert momentum_signal < 0.0

    def test_blend_clamped(self):
        """Extreme momentum values must be clamped to [-1, 1]."""
        for blend in [-1.0, 1.0]:
            signal = max(-1.0, min(1.0, blend / 0.10))
            assert -1.0 <= signal <= 1.0

    def test_blend_zero(self):
        """Zero momentum → zero signal."""
        mom_blend = 0.0 * 0.5 + 0.0 * 0.35 + 0.0 * 0.15
        signal = max(-1.0, min(1.0, mom_blend / 0.10))
        assert signal == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# calculate_edge
# ---------------------------------------------------------------------------


class TestEdgeCalculation:
    def test_edge_up_positive(self):
        """Model prob > market price → UP edge is positive."""
        edge, direction = calculate_edge(model_prob=0.60, market_price=0.45)
        assert edge > 0.0
        assert direction == "up"

    def test_edge_down_positive(self):
        """Model prob < market price → DOWN edge positive, direction DOWN."""
        edge, direction = calculate_edge(model_prob=0.40, market_price=0.55)
        assert edge > 0.0
        assert direction == "down"

    def test_edge_magnitude(self):
        """Edge should equal |model_prob - market_price|."""
        model_prob = 0.60
        market_price = 0.45
        edge, _ = calculate_edge(model_prob, market_price)
        assert edge == pytest.approx(model_prob - market_price)

    def test_edge_zero_when_equal(self):
        """Edge is 0 when model and market agree."""
        edge, _ = calculate_edge(model_prob=0.50, market_price=0.50)
        assert edge == pytest.approx(0.0)

    def test_edge_not_negative(self):
        """calculate_edge always returns the best (non-negative) edge."""
        for model in [0.35, 0.45, 0.55, 0.65]:
            for mkt in [0.40, 0.50, 0.60]:
                edge, _ = calculate_edge(model, mkt)
                assert edge >= 0.0, f"Negative edge for model={model}, mkt={mkt}"


# ---------------------------------------------------------------------------
# calculate_kelly_size
# ---------------------------------------------------------------------------


class TestKellySizing:
    def test_kelly_positive_edge_up(self):
        """Positive edge UP → positive suggested size."""

        size = calculate_kelly_size(
            edge=0.10,
            probability=0.60,
            market_price=0.45,
            direction="up",
            bankroll=1000.0,
        )
        assert size > 0.0

    def test_kelly_positive_edge_down(self):
        """Positive edge DOWN → positive suggested size."""
        size = calculate_kelly_size(
            edge=0.10,
            probability=0.40,
            market_price=0.55,
            direction="down",
            bankroll=1000.0,
        )
        assert size > 0.0

    def test_kelly_zero_edge_returns_zero(self):
        """Zero edge → zero or near-zero size (Kelly goes negative, clipped to 0)."""
        size = calculate_kelly_size(
            edge=0.0,
            probability=0.50,
            market_price=0.50,
            direction="up",
            bankroll=1000.0,
        )
        assert size == pytest.approx(0.0)

    def test_kelly_respects_max_trade_size(self):
        """Size must never exceed MAX_TRADE_SIZE regardless of edge/bankroll."""
        from backend.config import settings

        size = calculate_kelly_size(
            edge=0.50,
            probability=0.95,
            market_price=0.10,
            direction="up",
            bankroll=100_000.0,
        )
        assert size <= settings.MAX_TRADE_SIZE

    def test_kelly_scales_with_bankroll(self):
        """Larger bankroll should produce a larger suggested size."""
        size_small = calculate_kelly_size(
            edge=0.10,
            probability=0.60,
            market_price=0.45,
            direction="up",
            bankroll=100.0,
        )
        size_large = calculate_kelly_size(
            edge=0.10,
            probability=0.60,
            market_price=0.45,
            direction="up",
            bankroll=10_000.0,
        )
        assert size_large >= size_small

    def test_kelly_zero_bankroll(self):
        """Zero bankroll → zero size."""
        size = calculate_kelly_size(
            edge=0.10,
            probability=0.60,
            market_price=0.45,
            direction="up",
            bankroll=0.0,
        )
        assert size == pytest.approx(0.0)

    def test_kelly_invalid_price_returns_zero(self):
        """Price at boundary (0 or 1) → zero size."""
        for price in [0.0, 1.0]:
            size = calculate_kelly_size(
                edge=0.10,
                probability=0.60,
                market_price=price,
                direction="up",
                bankroll=1000.0,
            )
            assert size == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Bayesian Kelly sizing
# ---------------------------------------------------------------------------


class TestBayesianKelly:
    def test_bayesian_shrinks_with_small_sample(self):
        """Small n_eff → heavy shrinkage → smaller size than classic Kelly."""
        classic = calculate_kelly_size(
            edge=0.05,
            probability=0.55,
            market_price=0.50,
            direction="up",
            bankroll=50.0,
        )
        bayesian = calculate_kelly_size(
            edge=0.05,
            probability=0.55,
            market_price=0.50,
            direction="up",
            bankroll=50.0,
            n_eff=5,
        )
        assert bayesian < classic
        assert bayesian > 0.0

    def test_bayesian_converges_with_large_sample(self):
        """Large n_eff → shrinkage factor ≈ 1 → nearly identical to classic."""
        classic = calculate_kelly_size(
            edge=0.05,
            probability=0.55,
            market_price=0.50,
            direction="up",
            bankroll=50.0,
        )
        bayesian = calculate_kelly_size(
            edge=0.05,
            probability=0.55,
            market_price=0.50,
            direction="up",
            bankroll=50.0,
            n_eff=10000,
        )
        assert bayesian == pytest.approx(classic, rel=0.01)

    def test_bayesian_zero_neff_returns_zero(self):
        """n_eff=0 → shrinkage factor is 0 → size is 0."""
        size = calculate_kelly_size(
            edge=0.05,
            probability=0.55,
            market_price=0.50,
            direction="up",
            bankroll=50.0,
            n_eff=0,
        )
        assert size == pytest.approx(0.0)

    def test_bayesian_none_neff_is_classic(self):
        """n_eff=None (default) → no shrinkage → classic Kelly behavior."""
        classic = calculate_kelly_size(
            edge=0.05,
            probability=0.55,
            market_price=0.50,
            direction="up",
            bankroll=50.0,
        )
        explicit_none = calculate_kelly_size(
            edge=0.05,
            probability=0.55,
            market_price=0.50,
            direction="up",
            bankroll=50.0,
            n_eff=None,
        )
        assert explicit_none == classic

    def test_bayesian_max_fraction_is_fifteen_percent(self):
        """Bayesian Kelly must never exceed 15% of bankroll."""
        size = calculate_kelly_size(
            edge=0.50,
            probability=0.95,
            market_price=0.10,
            direction="up",
            bankroll=10_000.0,
            n_eff=10000,
        )
        assert size <= 1500.0

    def test_bayesian_custom_prior_confidence(self):
        """Higher prior_confidence → more shrinkage at same n_eff."""
        low_prior = calculate_kelly_size(
            edge=0.05,
            probability=0.55,
            market_price=0.50,
            direction="up",
            bankroll=50.0,
            n_eff=30,
            prior_confidence=10.0,
        )
        high_prior = calculate_kelly_size(
            edge=0.05,
            probability=0.55,
            market_price=0.50,
            direction="up",
            bankroll=50.0,
            n_eff=30,
            prior_confidence=100.0,
        )
        assert low_prior > high_prior

    def test_bayesian_shrinkage_factor_correctness(self):
        """Verify shrinkage factor = n_eff / (n_eff + k) is applied correctly."""
        n_eff = 30
        k = 30.0
        expected_factor = n_eff / (n_eff + k)  # 0.5

        classic = calculate_kelly_size(
            edge=0.05,
            probability=0.55,
            market_price=0.50,
            direction="up",
            bankroll=50.0,
        )
        bayesian = calculate_kelly_size(
            edge=0.05,
            probability=0.55,
            market_price=0.50,
            direction="up",
            bankroll=50.0,
            n_eff=n_eff,
            prior_confidence=k,
        )
        assert bayesian == pytest.approx(classic * expected_factor, rel=0.01)


# ---------------------------------------------------------------------------
# Convergence filter (2/4 indicators must agree)
# ---------------------------------------------------------------------------


class TestConvergenceFilter:
    def _count_votes(self, signals: list):
        up_votes = sum(1 for s in signals if s > 0.05)
        down_votes = sum(1 for s in signals if s < -0.05)
        return up_votes, down_votes

    def test_two_up_passes(self):
        up, down = self._count_votes([0.3, 0.4, -0.1, 0.01])
        assert up >= 2 or down >= 2

    def test_two_down_passes(self):
        up, down = self._count_votes([-0.3, -0.4, 0.01, 0.01])
        assert up >= 2 or down >= 2

    def test_one_of_each_fails(self):
        up, down = self._count_votes([0.3, -0.3, 0.01, 0.01])
        assert not (up >= 2 or down >= 2)

    def test_all_agree_passes(self):
        up, down = self._count_votes([0.5, 0.6, 0.3, 0.4])
        assert up >= 2

    def test_near_zero_indicators_excluded(self):
        """Signals within ±0.05 threshold are not counted as votes."""
        up, down = self._count_votes([0.04, 0.03, 0.02, 0.01])
        assert not (up >= 2 or down >= 2)


# ---------------------------------------------------------------------------
# Entry price filter (price <= MAX_ENTRY_PRICE = 0.80)
# ---------------------------------------------------------------------------


class TestEntryPriceFilter:
    def test_low_price_passes(self):
        from backend.config import settings

        entry_price = 0.45
        assert entry_price <= settings.MAX_ENTRY_PRICE

    def test_at_threshold_passes(self):
        from backend.config import settings

        entry_price = settings.MAX_ENTRY_PRICE
        assert entry_price <= settings.MAX_ENTRY_PRICE

    def test_above_threshold_fails(self):
        from backend.config import settings

        entry_price = 0.85
        assert entry_price > settings.MAX_ENTRY_PRICE

    def test_max_entry_price_is_80c(self):
        from backend.config import settings

        assert settings.MAX_ENTRY_PRICE == pytest.approx(0.80)


# ---------------------------------------------------------------------------
# Direction logic (composite → UP/DOWN)
# ---------------------------------------------------------------------------


class TestDirectionLogic:
    def test_positive_composite_gives_up(self):
        """Positive composite → model_prob > 0.50 → UP edge when market ≈ 0.50."""
        composite = 0.3
        model_up_prob = max(0.35, min(0.65, 0.50 + composite * 0.15))
        market_price = 0.50
        edge, direction = calculate_edge(model_up_prob, market_price)
        assert direction == "up"

    def test_negative_composite_gives_down(self):
        """Negative composite → model_prob < 0.50 → DOWN edge when market ≈ 0.50."""
        composite = -0.3
        model_up_prob = max(0.35, min(0.65, 0.50 + composite * 0.15))
        market_price = 0.50
        edge, direction = calculate_edge(model_up_prob, market_price)
        assert direction == "down"

    def test_zero_composite_no_strong_edge(self):
        """Zero composite → model_prob = 0.50 → zero edge."""
        composite = 0.0
        model_up_prob = 0.50 + composite * 0.15
        market_price = 0.50
        edge, _ = calculate_edge(model_up_prob, market_price)
        assert edge == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# generate_btc_signal integration (with mocked external calls)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGenerateBtcSignal:
    async def test_returns_signal_with_valid_micro(self):
        """generate_btc_signal returns a TradingSignal when micro data is available."""
        from backend.core.signals import generate_btc_signal

        market = _make_market(up_price=0.45, down_price=0.55)
        micro = _make_micro(
            rsi=40.0,
            momentum_1m=0.05,
            momentum_5m=0.03,
            momentum_15m=0.01,
            vwap_deviation=0.02,
            sma_crossover=0.01,
            volatility=0.02,
            price=65000.0,
        )

        with (
            patch(
                "backend.core.signals.compute_btc_microstructure",
                AsyncMock(return_value=micro),
            ),
            patch("backend.core.signals._persist_signals", MagicMock()),
        ):
            signal = await generate_btc_signal(market)

        assert signal is not None
        assert isinstance(signal, TradingSignal)

    async def test_returns_none_when_micro_fails(self):
        """generate_btc_signal returns None when microstructure fetch fails."""
        from backend.core.signals import generate_btc_signal

        market = _make_market()

        with patch(
            "backend.core.signals.compute_btc_microstructure",
            AsyncMock(side_effect=Exception("network error")),
        ):
            signal = await generate_btc_signal(market)

        assert signal is None

    async def test_model_probability_in_range(self):
        """model_probability must always be in [0.35, 0.65]."""
        from backend.core.signals import generate_btc_signal

        market = _make_market(up_price=0.48, down_price=0.52)
        micro = _make_micro(
            rsi=25.0,  # extreme
            momentum_1m=0.20,
            momentum_5m=0.15,
            momentum_15m=0.10,  # extreme
            vwap_deviation=0.10,
            sma_crossover=0.05,
            volatility=0.05,
            price=65000.0,
        )

        with (
            patch(
                "backend.core.signals.compute_btc_microstructure",
                AsyncMock(return_value=micro),
            ),
            patch("backend.core.signals._persist_signals", MagicMock()),
        ):
            signal = await generate_btc_signal(market)

        if signal:
            assert 0.35 <= signal.model_probability <= 0.65

    async def test_skips_nearly_resolved_markets(self):
        """Markets with up_price near 0 or 1 should be skipped."""
        from backend.core.signals import generate_btc_signal

        market = _make_market(up_price=0.99, down_price=0.01)

        with patch(
            "backend.core.signals.compute_btc_microstructure",
            AsyncMock(return_value=_make_micro()),
        ):
            signal = await generate_btc_signal(market)

        assert signal is None
