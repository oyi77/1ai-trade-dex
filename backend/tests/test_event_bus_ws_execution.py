import pytest

from backend.core.event_bus import EventBus
from backend.models.database import StrategyConfig


@pytest.mark.asyncio
async def test_event_bus_executes_buy_decision_for_strategy_config_modes(monkeypatch, db):
    db.add(
        StrategyConfig(
            strategy_name="ws_strategy",
            enabled=True,
            trading_mode="live",
            interval_seconds=60,
        )
    )
    db.commit()
    calls = []

    async def fake_execute_decision(decision, strategy_name, mode="paper", db=None):
        calls.append((decision, strategy_name, mode))
        return {"trade_id": len(calls)}

    monkeypatch.setattr(
        "backend.core.strategy_executor.execute_decision",
        fake_execute_decision,
    )

    bus = EventBus()
    await bus._execute_strategy_decision(
        "ws_strategy",
        {
            "decision": "BUY",
            "token_id": "token_1",
            "direction": "yes",
            "confidence": 0.9,
            "edge": 0.05,
            "size": 5.0,
        },
    )

    assert [(strategy_name, mode) for _decision, strategy_name, mode in calls] == [
        ("ws_strategy", "paper"),
        ("ws_strategy", "live"),
    ]
    assert all(call[0]["market_ticker"] == "token_1" for call in calls)


@pytest.mark.asyncio
async def test_event_bus_ignores_non_buy_decision(monkeypatch):
    calls = []

    async def fake_execute_decision(decision, strategy_name, mode="paper", db=None):
        calls.append((decision, strategy_name, mode))

    monkeypatch.setattr(
        "backend.core.strategy_executor.execute_decision",
        fake_execute_decision,
    )

    bus = EventBus()
    await bus._execute_strategy_decision("ws_strategy", {"decision": "SKIP", "token_id": "token_1"})

    assert calls == []
