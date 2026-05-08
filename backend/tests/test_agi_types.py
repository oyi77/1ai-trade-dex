"""Tests for AGI type system — enums, dataclasses, serialization.

TDD: RED phase — these tests define the expected interface before implementation.
"""
from datetime import datetime, timezone

import pytest

from backend.core.agi_types import (
    AGIGoal,
    DecisionAuditEntry,
    ExperimentStatus,
    KGEntity,
    KGRelation,
    MarketRegime,
    RegimeTransition,
    StrategyBlock,
)


# ── MarketRegime enum ──────────────────────────────────────────────────────

class TestMarketRegime:
    """MarketRegime enum must have exactly 6 members."""

    def test_has_all_six_members(self):
        expected = {"BULL", "BEAR", "SIDEWAYS", "SIDEWAYS_VOLATILE", "CRISIS", "UNKNOWN"}
        actual = {m.name for m in MarketRegime}
        assert actual == expected, f"Missing regimes: {expected - actual}"

    def test_string_values_are_lowercase(self):
        for member in MarketRegime:
            assert member.value == member.name.lower(), (
                f"MarketRegime.{member.name}.value should be '{member.name.lower()}', "
                f"got '{member.value}'"
            )

    def test_from_string(self):
        assert MarketRegime("bull") == MarketRegime.BULL
        assert MarketRegime("bear") == MarketRegime.BEAR
        assert MarketRegime("crisis") == MarketRegime.CRISIS


# ── AGIGoal enum ──────────────────────────────────────────────────────────

class TestAGIGoal:
    """AGIGoal enum must have exactly 4 members."""

    def test_has_all_four_members(self):
        expected = {"MAXIMIZE_PNL", "PRESERVE_CAPITAL", "GROW_ALLOCATION", "REDUCE_EXPOSURE"}
        actual = {m.name for m in AGIGoal}
        assert actual == expected, f"Missing goals: {expected - actual}"

    def test_string_values_are_lowercase(self):
        for member in AGIGoal:
            assert member.value == member.name.lower()


# ── ExperimentStatus enum ─────────────────────────────────────────────────

class TestExperimentStatus:
    """ExperimentStatus enum must have all lifecycle members."""

    def test_has_all_members(self):
        expected = {
            "DRAFT", "BACKTEST", "SHADOW", "PAPER",
            "LIVE_TRIAL", "LIVE_PROMOTED", "LIVE_FAILED",
            "REVIEW", "RETIRED",
        }
        actual = {m.name for m in ExperimentStatus}
        assert actual == expected, f"Missing: {expected - actual}, Extra: {actual - expected}"

    def test_string_values_are_lowercase(self):
        for member in ExperimentStatus:
            assert member.value == member.name.lower()


# ── StrategyBlock dataclass ───────────────────────────────────────────────

class TestStrategyBlock:
    """StrategyBlock must have 5 required string fields."""

    def test_create_with_all_fields(self):
        block = StrategyBlock(
            signal_source="whale_tracker",
            filter="min_volume_1000",
            position_sizer="kelly_half",
            risk_rule="max_1pct",
            exit_rule="take_profit_10pct",
        )
        assert block.signal_source == "whale_tracker"
        assert block.filter == "min_volume_1000"
        assert block.position_sizer == "kelly_half"
        assert block.risk_rule == "max_1pct"
        assert block.exit_rule == "take_profit_10pct"

    def test_to_dict_roundtrip(self):
        block = StrategyBlock(
            signal_source="btc_momentum",
            filter="rsi_filter",
            position_sizer="fixed_size",
            risk_rule="max_2pct",
            exit_rule="stop_loss_5pct",
        )
        d = block.to_dict()
        restored = StrategyBlock.from_dict(d)
        assert restored == block

    def test_missing_required_field_raises(self):
        with pytest.raises(TypeError):
            StrategyBlock(signal_source="test")  # missing filter, position_sizer, risk_rule, exit_rule


# ── DecisionAuditEntry dataclass ──────────────────────────────────────────

class TestDecisionAuditEntry:
    """DecisionAuditEntry must capture regime, goal, strategy, reasoning."""

    def test_create_with_all_fields(self):
        entry = DecisionAuditEntry(
            timestamp=datetime(2026, 4, 29, tzinfo=timezone.utc),
            regime=MarketRegime.BULL,
            goal=AGIGoal.MAXIMIZE_PNL,
            strategy="btc_momentum",
            signal={"edge": 0.15, "confidence": 0.8},
            reasoning="Strong momentum signal in bull regime",
            outcome="executed",
        )
        assert entry.regime == MarketRegime.BULL
        assert entry.goal == AGIGoal.MAXIMIZE_PNL
        assert entry.strategy == "btc_momentum"
        assert entry.signal["edge"] == 0.15
        assert entry.reasoning.startswith("Strong")
        assert entry.outcome == "executed"

    def test_to_dict_roundtrip(self):
        entry = DecisionAuditEntry(
            timestamp=datetime(2026, 4, 29, tzinfo=timezone.utc),
            regime=MarketRegime.BEAR,
            goal=AGIGoal.PRESERVE_CAPITAL,
            strategy="copy_trader",
            signal={"whale_pnl": 0.3},
            reasoning="Whale PnL declining",
            outcome="skipped",
        )
        d = entry.to_dict()
        restored = DecisionAuditEntry.from_dict(d)
        assert restored.regime == entry.regime
        assert restored.goal == entry.goal
        assert restored.strategy == entry.strategy


# ── KGEntity dataclass ─────────────────────────────────────────────────────

class TestKGEntity:
    """KGEntity must have entity_type, entity_id, and properties."""

    def test_create_with_required_fields(self):
        entity = KGEntity(
            entity_type="strategy",
            entity_id="btc_momentum",
            properties={"win_rate": 0.65, "sharpe": 1.2},
        )
        assert entity.entity_type == "strategy"
        assert entity.entity_id == "btc_momentum"
        assert entity.properties["win_rate"] == 0.65

    def test_to_dict_roundtrip(self):
        entity = KGEntity(
            entity_type="market",
            entity_id="btc_usd",
            properties={"volatility": 0.03},
        )
        d = entity.to_dict()
        restored = KGEntity.from_dict(d)
        assert restored.entity_type == entity.entity_type
        assert restored.entity_id == entity.entity_id
        assert restored.properties == entity.properties

    def test_empty_properties(self):
        entity = KGEntity(
            entity_type="regime",
            entity_id="bull_2026_q1",
            properties={},
        )
        assert entity.properties == {}


# ── KGRelation dataclass ──────────────────────────────────────────────────

class TestKGRelation:
    """KGRelation must have from/to entities, relation type, weight, confidence."""

    def test_create_with_all_fields(self):
        rel = KGRelation(
            from_entity="btc_momentum",
            to_entity="bull_regime",
            relation_type="performs_well_in",
            weight=0.85,
            confidence=0.72,
            timestamp=datetime(2026, 4, 29, tzinfo=timezone.utc),
        )
        assert rel.from_entity == "btc_momentum"
        assert rel.to_entity == "bull_regime"
        assert rel.relation_type == "performs_well_in"
        assert rel.weight == 0.85
        assert rel.confidence == 0.72

    def test_to_dict_roundtrip(self):
        rel = KGRelation(
            from_entity="weather_emos",
            to_entity="sideways_regime",
            relation_type="performs_poorly_in",
            weight=0.3,
            confidence=0.5,
            timestamp=datetime(2026, 4, 29, tzinfo=timezone.utc),
        )
        d = rel.to_dict()
        restored = KGRelation.from_dict(d)
        assert restored.from_entity == rel.from_entity
        assert restored.to_entity == rel.to_entity
        assert restored.relation_type == rel.relation_type
        assert restored.weight == rel.weight
        assert restored.confidence == rel.confidence

    def test_weight_and_confidence_bounds(self):
        """Weight and confidence must be between 0 and 1."""
        # Valid values
        KGRelation(from_entity="a", to_entity="b", relation_type="test", weight=0.0, confidence=0.0, timestamp=datetime.now(timezone.utc))
        KGRelation(from_entity="a", to_entity="b", relation_type="test", weight=1.0, confidence=1.0, timestamp=datetime.now(timezone.utc))


# ── RegimeTransition dataclass ─────────────────────────────────────────────

class TestRegimeTransition:
    """RegimeTransition must capture from/to regime with confidence."""

    def test_create_with_all_fields(self):
        transition = RegimeTransition(
            from_regime=MarketRegime.BULL,
            to_regime=MarketRegime.BEAR,
            confidence=0.87,
            timestamp=datetime(2026, 4, 29, tzinfo=timezone.utc),
        )
        assert transition.from_regime == MarketRegime.BULL
        assert transition.to_regime == MarketRegime.BEAR
        assert transition.confidence == 0.87

    def test_to_dict_roundtrip(self):
        transition = RegimeTransition(
            from_regime=MarketRegime.SIDEWAYS,
            to_regime=MarketRegime.SIDEWAYS_VOLATILE,
            confidence=0.65,
            timestamp=datetime(2026, 4, 29, tzinfo=timezone.utc),
        )
        d = transition.to_dict()
        restored = RegimeTransition.from_dict(d)
        assert restored.from_regime == transition.from_regime
        assert restored.to_regime == transition.to_regime
        assert restored.confidence == transition.confidence
