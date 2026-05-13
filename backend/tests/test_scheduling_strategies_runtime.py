import asyncio

import pytest


@pytest.mark.asyncio
async def test_strategy_cycle_job_treats_cancellation_as_clean_shutdown(monkeypatch):
    """Cancelled strategy jobs during PM2 restart should not log error stack traces."""
    from backend.core import scheduling_strategies as ss
    from backend.core import scheduler

    async def cancelled_to_thread(_func):
        raise asyncio.CancelledError()

    events: list[tuple[str, str]] = []

    monkeypatch.setattr(ss.asyncio, "to_thread", cancelled_to_thread)
    monkeypatch.setattr(scheduler, "log_event", lambda level, message: events.append((level, message)))

    await ss.strategy_cycle_job("line_movement_detector", mode="paper")

    assert events == []
