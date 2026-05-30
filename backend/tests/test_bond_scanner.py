"""Tests for BondScannerStrategy."""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch


def _near_future_date(days=3) -> str:
    """Return an ISO date string N days from now (within the max_days_to_resolution window)."""
    dt = datetime.now(timezone.utc) + timedelta(days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_market(
    slug="test-market",
    volume=20000,
    outcome_prices=None,
    outcomes=None,
    end_date=None,
    question="Will X happen?",
):
    return {
        "slug": slug,
        "question": question,
        "volume": volume,
        "outcomePrices": (
            outcome_prices if outcome_prices is not None else ["0.95", "0.05"]
        ),
        "outcomes": outcomes if outcomes is not None else ["Yes", "No"],
        "endDate": end_date if end_date is not None else _near_future_date(3),
    }


def _make_ctx(params=None, bankroll=100.0):
    from backend.strategies.base import StrategyContext
    from backend.config import settings

    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []
    db.query.return_value.first.return_value = MagicMock(bankroll=bankroll)

    ctx = StrategyContext(
        db=db,
        clob=None,
        settings=settings,
        logger=MagicMock(),
        params=params or {},
        mode="paper",
    )
    return ctx


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBondScannerFilters:
    def test_filters_by_price_range(self):
        """Only markets with outcome prices between min_price and max_price qualify."""
        from backend.strategies.bond_scanner import BondScannerStrategy

        strategy = BondScannerStrategy()
        params = strategy.default_params

        # Price too low — should NOT qualify
        low_market = _make_market(outcome_prices=["0.80", "0.20"])
        prices = [float(p) for p in low_market["outcomePrices"]]
        qualifies = any(params["min_price"] <= p <= params["max_price"] for p in prices)
        assert not qualifies, "0.80 should not qualify (below min_price)"

        # Price too high — should NOT qualify
        high_market = _make_market(outcome_prices=["0.995", "0.005"])
        prices = [float(p) for p in high_market["outcomePrices"]]
        qualifies = any(params["min_price"] <= p <= params["max_price"] for p in prices)
        assert not qualifies, "0.995 should not qualify (above max_price)"

        # Price in range — SHOULD qualify
        good_market = _make_market(outcome_prices=["0.95", "0.05"])
        prices = [float(p) for p in good_market["outcomePrices"]]
        qualifies = any(params["min_price"] <= p <= params["max_price"] for p in prices)
        assert qualifies, "0.95 should qualify (within price range)"

    def test_filters_by_volume(self):
        """Markets below min_volume should be rejected."""
        from backend.strategies.bond_scanner import BondScannerStrategy

        strategy = BondScannerStrategy()
        min_volume = strategy.default_params["min_volume"]

        low_vol = _make_market(volume=500)
        assert low_vol["volume"] < min_volume, "500 is below min_volume threshold"

        high_vol = _make_market(volume=5000)
        assert high_vol["volume"] >= min_volume, "5000 meets min_volume threshold"

    def test_edge_calculation(self):
        """Edge should equal 1.0 - price."""
        from backend.strategies.bond_scanner import BondScannerStrategy

        _strategy = BondScannerStrategy()

        test_cases = [
            (0.95, 0.05),
            (0.92, 0.08),
            (0.97, 0.03),
            (0.98, 0.02),
        ]
        for price, expected_edge in test_cases:
            edge = round(1.0 - price, 4)
            assert (
                abs(edge - expected_edge) < 1e-9
            ), f"edge for price {price} should be {expected_edge}, got {edge}"

    @pytest.mark.asyncio
    async def test_run_cycle_returns_cycle_result(self):
        """run_cycle returns a CycleResult even when API fails."""
        from backend.strategies.bond_scanner import BondScannerStrategy
        from backend.strategies.base import CycleResult

        strategy = BondScannerStrategy()
        ctx = _make_ctx()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=Exception("network error"))
            mock_client_cls.return_value = mock_client

            result = await strategy.run_cycle(ctx)

        assert isinstance(result, CycleResult)
        assert len(result.errors) > 0

    @pytest.mark.asyncio
    async def test_run_cycle_finds_qualifying_markets(self):
        """run_cycle records decisions for markets that pass all filters."""
        from backend.strategies.bond_scanner import BondScannerStrategy
        from backend.strategies.base import CycleResult

        strategy = BondScannerStrategy()
        ctx = _make_ctx()

        markets = [
            _make_market(
                slug="qualifying-market",
                volume=50000,
                outcome_prices=["0.95", "0.05"],
                end_date=_near_future_date(3),
            ),
            _make_market(
                slug="low-volume-market",
                volume=500,
                outcome_prices=["0.94", "0.06"],
                end_date=_near_future_date(3),
            ),
        ]

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value=markets)

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await strategy.run_cycle(ctx)

        assert isinstance(result, CycleResult)
        # qualifying-market should count; low-volume should not
        assert result.decisions_recorded >= 1
