import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from backend.core.arb_executor import execute_arb_decisions


def _make_fake_db_session(bankroll: float = 100.0, marks: list | None = None):
    bot_state = SimpleNamespace(bankroll=bankroll, paper_bankroll=bankroll)

    class Query:
        def filter_by(self, **kwargs):
            return self

        def filter(self, *args):
            return self

        def first(self):
            return bot_state

        def update(self, values, synchronize_session=False):
            if marks is not None:
                marks.append(values.get("execution_status"))
            return 1

    class DB:
        def query(self, model):
            return Query()

        def commit(self):
            pass

    @contextmanager
    def session():
        yield DB()

    return session


_fake_db_session = _make_fake_db_session()


def _decision(signal_data: dict, market_ticker: str = "arb-market"):
    return SimpleNamespace(
        id=1,
        strategy="arb_scanner",
        market_ticker=market_ticker,
        decision="ARB",
        confidence=0.9,
        signal_data=json.dumps(signal_data),
    )


def _verified_yes_no_signal(yes_price=0.42, no_price=0.48, yes_size=10.0, no_size=10.0):
    return {
        "kind": "yes_no_sum",
        "platform": "polymarket",
        "event_id": "condition-1",
        "net_profit": 0.08,
        "net_profit_pct": 0.088,
        "legs": [
            {
                "direction": "YES",
                "token_id": "yes-token",
                "price": yes_price,
                "size": yes_size,
                "market_ticker": "condition-1:YES",
            },
            {
                "direction": "NO",
                "token_id": "no-token",
                "price": no_price,
                "size": no_size,
                "market_ticker": "condition-1:NO",
            },
        ],
    }


def _patch_bundle_gate(monkeypatch, count=0):
    monkeypatch.setattr(
        "backend.core.bundle_reconciliation.count_open_incomplete_bundles",
        lambda db, mode="live": count,
    )


@pytest.mark.asyncio
async def test_legacy_arb_signal_without_verified_legs_is_not_executed(monkeypatch):
    monkeypatch.setattr("backend.core.arb_executor.get_db_session", _fake_db_session)
    calls = []

    async def fake_execute(payload, strategy_name, mode="paper"):
        calls.append(payload)
        return {"ok": True}

    row = _decision({
        "platform_a": "polymarket",
        "platform_b": "polymarket",
        "price_a": 0.5,
        "price_b": 0.5,
        "model_probability": 0.9,
        "net_profit": 0.1,
    })

    processed = await execute_arb_decisions(
        [row], mode="paper", execute_decision_factory=fake_execute
    )

    assert processed == []
    assert calls == []


@pytest.mark.asyncio
async def test_verified_yes_no_sum_arb_executes_both_legs(monkeypatch):
    monkeypatch.setattr("backend.core.arb_executor.get_db_session", _fake_db_session)
    _patch_bundle_gate(monkeypatch)
    calls = []

    async def fake_execute(payload, strategy_name, mode="paper"):
        calls.append(payload)
        return {"ok": True, "market_ticker": payload["market_ticker"]}

    async def quote_provider(leg):
        return {"price": 0.41 if leg["direction"] == "YES" else 0.47, "available_size": 10.0}

    row = _decision(_verified_yes_no_signal(), market_ticker="condition-1")

    processed = await execute_arb_decisions(
        [row], mode="live", execute_decision_factory=fake_execute, quote_provider=quote_provider
    )

    assert processed == ["1"]
    assert [call["direction"] for call in calls] == ["YES", "NO"]
    assert [call["price"] for call in calls] == [0.41, 0.47]
    assert all(call["arb_bundle_id"] == "arb-1-condition-1" for call in calls)
    assert all(call["decision"] == "BUY" for call in calls)
    assert all(call["strategy"] == "arb_scanner" for call in calls)


@pytest.mark.asyncio
async def test_live_arb_without_quote_provider_is_not_executed(monkeypatch):
    monkeypatch.setattr("backend.core.arb_executor.get_db_session", _fake_db_session)
    _patch_bundle_gate(monkeypatch)
    calls = []

    async def fake_execute(payload, strategy_name, mode="paper"):
        calls.append(payload)
        return {"ok": True}

    row = _decision(_verified_yes_no_signal(), market_ticker="condition-1")

    processed = await execute_arb_decisions(
        [row], mode="live", execute_decision_factory=fake_execute
    )

    assert processed == []
    assert calls == []


@pytest.mark.asyncio
async def test_live_arb_revalidates_fresh_quotes_and_skips_stale_edge(monkeypatch):
    monkeypatch.setattr("backend.core.arb_executor.get_db_session", _fake_db_session)
    _patch_bundle_gate(monkeypatch)
    calls = []

    async def fake_execute(payload, strategy_name, mode="paper"):
        calls.append(payload)
        return {"ok": True}

    async def quote_provider(leg):
        return {"price": 0.52 if leg["direction"] == "YES" else 0.50, "available_size": 10.0}

    row = _decision(_verified_yes_no_signal(), market_ticker="condition-1")

    processed = await execute_arb_decisions(
        [row], mode="live", execute_decision_factory=fake_execute, quote_provider=quote_provider
    )

    assert processed == []
    assert calls == []


@pytest.mark.asyncio
async def test_incomplete_live_bundle_unwinds_filled_first_leg(monkeypatch):
    monkeypatch.setattr("backend.core.arb_executor.get_db_session", _fake_db_session)
    _patch_bundle_gate(monkeypatch)
    calls = []

    async def fake_execute(payload, strategy_name, mode="paper"):
        calls.append(payload)
        if payload["decision"] == "BUY" and payload["direction"] == "NO":
            return None
        return {"ok": True}

    async def quote_provider(leg):
        return {"price": 0.41 if leg["direction"] == "YES" else 0.47, "available_size": 10.0}

    row = _decision(_verified_yes_no_signal(), market_ticker="condition-1")

    processed = await execute_arb_decisions(
        [row], mode="live", execute_decision_factory=fake_execute, quote_provider=quote_provider
    )

    assert processed == []
    assert [(call["decision"], call["direction"]) for call in calls] == [
        ("BUY", "YES"),
        ("BUY", "NO"),
        ("SELL", "YES"),
    ]


@pytest.mark.asyncio
async def test_unprofitable_verified_legs_are_not_executed(monkeypatch):
    monkeypatch.setattr("backend.core.arb_executor.get_db_session", _fake_db_session)
    _patch_bundle_gate(monkeypatch)
    calls = []

    async def fake_execute(payload, strategy_name, mode="paper"):
        calls.append(payload)
        return {"ok": True}

    async def quote_provider(leg):
        return {"price": 0.51 if leg["direction"] == "YES" else 0.50, "available_size": 10.0}

    row = _decision(_verified_yes_no_signal(yes_price=0.51, no_price=0.50))

    processed = await execute_arb_decisions(
        [row], mode="live", execute_decision_factory=fake_execute, quote_provider=quote_provider
    )

    assert processed == []
    assert calls == []


@pytest.mark.asyncio
async def test_skipped_decision_is_marked_skipped(monkeypatch):
    marks: list = []
    monkeypatch.setattr(
        "backend.core.arb_executor.get_db_session",
        _make_fake_db_session(marks=marks),
    )

    async def fake_execute(payload, strategy_name, mode="paper"):
        return {"ok": True}

    row = _decision({"kind": "same_game_cross"})

    processed = await execute_arb_decisions(
        [row], mode="paper", execute_decision_factory=fake_execute
    )

    assert processed == []
    assert marks == ["SKIPPED"]


@pytest.mark.asyncio
async def test_executed_decision_is_marked_executed(monkeypatch):
    marks: list = []
    monkeypatch.setattr(
        "backend.core.arb_executor.get_db_session",
        _make_fake_db_session(marks=marks),
    )

    async def fake_execute(payload, strategy_name, mode="paper"):
        return {"ok": True}

    row = _decision(_verified_yes_no_signal(), market_ticker="condition-1")

    processed = await execute_arb_decisions(
        [row], mode="paper", execute_decision_factory=fake_execute
    )

    assert processed == ["1"]
    assert marks == ["EXECUTED"]


@pytest.mark.asyncio
async def test_failed_bundle_is_marked_failed(monkeypatch):
    marks: list = []
    monkeypatch.setattr(
        "backend.core.arb_executor.get_db_session",
        _make_fake_db_session(marks=marks),
    )
    _patch_bundle_gate(monkeypatch)

    async def fake_execute(payload, strategy_name, mode="paper"):
        if payload["decision"] == "BUY" and payload["direction"] == "NO":
            return None
        return {"ok": True}

    async def quote_provider(leg):
        return {"price": 0.41 if leg["direction"] == "YES" else 0.47, "available_size": 10.0}

    row = _decision(_verified_yes_no_signal(), market_ticker="condition-1")

    processed = await execute_arb_decisions(
        [row], mode="live", execute_decision_factory=fake_execute, quote_provider=quote_provider
    )

    assert processed == []
    assert marks == ["FAILED"]


@pytest.mark.asyncio
async def test_live_arb_blocked_when_incomplete_bundles_exist(monkeypatch):
    monkeypatch.setattr("backend.core.arb_executor.get_db_session", _fake_db_session)
    calls = []

    async def fake_execute(payload, strategy_name, mode="paper"):
        calls.append(payload)
        return {"ok": True}

    async def quote_provider(leg):
        return {"price": 0.41 if leg["direction"] == "YES" else 0.47, "available_size": 10.0}

    _patch_bundle_gate(monkeypatch, count=3)
    row = _decision(_verified_yes_no_signal(), market_ticker="condition-1")

    processed = await execute_arb_decisions(
        [row], mode="live", execute_decision_factory=fake_execute,
        quote_provider=quote_provider,
    )

    assert processed == []
    assert calls == []
