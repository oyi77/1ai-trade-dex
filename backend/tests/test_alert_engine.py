"""Tests for backend.core.alert_engine."""

import pytest

from backend.core.alert_engine import AlertCondition, AlertEngine, AlertRule


@pytest.fixture()
def engine():
    return AlertEngine()


def _price_rule(**kwargs) -> AlertRule:
    defaults = dict(
        id="r1",
        name="Test Rule",
        condition=AlertCondition.PRICE_ABOVE,
        threshold=0.60,
        cooldown_seconds=300,
    )
    defaults.update(kwargs)
    return AlertRule(**defaults)


# ---------------------------------------------------------------------------
# 1. Price-above condition triggers when price exceeds threshold
# ---------------------------------------------------------------------------
def test_price_above_triggers(engine):
    rule = _price_rule(threshold=0.60)
    engine.add_rule(rule)

    triggered = engine.evaluate("price_update", {"price": 0.75})

    assert len(triggered) == 1
    assert triggered[0].id == "r1"
    assert triggered[0].triggered_count == 1


# ---------------------------------------------------------------------------
# 2. Cooldown prevents re-triggering within the cooldown window
# ---------------------------------------------------------------------------
def test_cooldown_prevents_retrigger(engine):
    rule = _price_rule(id="r2", cooldown_seconds=300)
    engine.add_rule(rule)

    data = {"price": 0.80}
    first = engine.evaluate("price_update", data)
    assert len(first) == 1

    # Immediately evaluate again — should be blocked by cooldown
    second = engine.evaluate("price_update", data)
    assert len(second) == 0
    assert rule.triggered_count == 1  # only incremented once


# ---------------------------------------------------------------------------
# 3. Disabled rules are never triggered
# ---------------------------------------------------------------------------
def test_disabled_rule_skipped(engine):
    rule = _price_rule(id="r3", enabled=False)
    engine.add_rule(rule)

    triggered = engine.evaluate("price_update", {"price": 0.99})
    assert triggered == []
    assert rule.triggered_count == 0
