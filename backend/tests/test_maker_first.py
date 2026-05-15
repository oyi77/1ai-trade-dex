"""
RED phase TDD tests for `place_maker_first_order` on PolymarketCLOB — must FAIL
until T13 (maker-first execution: limit order → 15s wait → taker escalation) is
implemented.

Covers:
  * High-edge path: edge_pp > 20 → skip maker, taker fill immediately
  * Low-edge path:  edge_pp < 20 → maker limit order placed, then filled
  * Timeout path:   limit order unfilled within timeout → escalates to taker
  * Metrics:        `record_maker_fill_rate` invoked per attempt
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.fixture
def clob():
    """A real PolymarketCLOB instance in paper mode for deterministic fills."""
    from backend.data.polymarket_clob import PolymarketCLOB

    return PolymarketCLOB(mode="paper")


@pytest.mark.asyncio
async def test_method_exists(clob):
    """`place_maker_first_order` must exist on PolymarketCLOB."""
    assert hasattr(clob, "place_maker_first_order"), (
        "PolymarketCLOB must expose place_maker_first_order("
        "token_id, side, size, edge_pp, timeout)"
    )


@pytest.mark.asyncio
async def test_high_edge_skips_maker_uses_taker(clob):
    """edge_pp > 20 → bypass maker post, go straight to taker."""
    result = await clob.place_maker_first_order(
        token_id="0xtoken",
        side="BUY",
        size=10.0,
        edge_pp=25.0,
        timeout=5.0,
    )
    assert result.success is True
    assert getattr(result, "maker_filled", False) is False


@pytest.mark.asyncio
async def test_low_edge_posts_maker_and_fills(clob):
    """edge_pp < 20 → post limit (maker) order, paper mode reports maker fill."""
    result = await clob.place_maker_first_order(
        token_id="0xtoken",
        side="BUY",
        size=10.0,
        edge_pp=8.0,
        timeout=5.0,
    )
    assert result.success is True
    assert getattr(result, "maker_filled", False) is True


@pytest.mark.asyncio
async def test_unfilled_maker_escalates_to_taker(monkeypatch, clob):
    """Maker order resting past `timeout` → cancel + taker escalation."""

    async def _placed_limit(*args, **kwargs):
        return SimpleNamespace(
            success=True,
            order_id="MAKER123",
            fill_price=None,
            fill_size=0.0,
            error=None,
        )

    async def _open_orders(*args, **kwargs):
        return [{"id": "MAKER123"}]

    async def _cancel(order_id):
        return SimpleNamespace(success=True, error=None)

    taker_called = {"flag": False}

    async def _placed_taker(*args, **kwargs):
        taker_called["flag"] = True
        return SimpleNamespace(
            success=True,
            order_id="TAKER456",
            fill_price=0.55,
            fill_size=kwargs.get("size", 10.0),
            error=None,
        )

    monkeypatch.setattr(clob, "place_limit_order", _placed_limit, raising=False)
    monkeypatch.setattr(clob, "get_open_orders", _open_orders, raising=False)
    monkeypatch.setattr(clob, "cancel_order", _cancel, raising=False)
    monkeypatch.setattr(clob, "place_market_order", _placed_taker, raising=False)

    result = await clob.place_maker_first_order(
        token_id="0xtoken",
        side="BUY",
        size=10.0,
        edge_pp=8.0,
        timeout=0.2,
    )
    assert result.success is True
    assert taker_called["flag"] is True, (
        "Taker escalation must be attempted on unfilled maker"
    )
    assert not getattr(result, "maker_filled", False), (
        "maker_filled must be False when taker escalation was used"
    )


@pytest.mark.asyncio
async def test_maker_fill_rate_metric_incremented(clob):
    """Every maker-first attempt must invoke record_maker_fill_rate()."""
    from backend.monitoring.hft_metrics import record_maker_fill_rate  # noqa: F401
    from backend.data import polymarket_clob as clob_mod

    recorded: list[tuple[str, bool]] = []

    def _record(market_id: str, filled: bool) -> None:
        recorded.append((market_id, filled))

    assert hasattr(clob_mod, "record_maker_fill_rate"), (
        "record_maker_fill_rate(market_id, filled) must exist for Prometheus metric"
    )
    original = clob_mod.record_maker_fill_rate
    clob_mod.record_maker_fill_rate = _record  # type: ignore[assignment]
    try:
        await clob.place_maker_first_order(
            token_id="0xtoken",
            side="BUY",
            size=10.0,
            edge_pp=8.0,
            timeout=1.0,
        )
        assert recorded, "place_maker_first_order must invoke record_maker_fill_rate()"
    finally:
        clob_mod.record_maker_fill_rate = original  # type: ignore[assignment]
