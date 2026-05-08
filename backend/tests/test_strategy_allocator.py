"""Tests for RegimeAwareAllocator — regime-dependent allocation, bounds, rebalancing."""
from datetime import datetime, timezone

from backend.core.agi_types import MarketRegime, RegimeTransition
from backend.core.knowledge_graph import KnowledgeGraph
from backend.core.strategy_allocator import RegimeAwareAllocator


def _kg_with_regime_data():
    kg = KnowledgeGraph()
    kg.add_entity("strategy", "btc_momentum", {"win_rate": 0.65})
    kg.add_entity("strategy", "weather_emos", {"win_rate": 0.55})
    kg.add_entity("strategy", "copy_trader", {"win_rate": 0.50})
    kg.add_entity("regime", "bull")
    kg.add_entity("regime", "bear")
    kg.add_relation("btc_momentum", "bull", "performs_well_in", 0.85, 0.72)
    kg.add_relation("weather_emos", "bull", "performs_well_in", 0.4, 0.3)
    kg.add_relation("copy_trader", "bear", "performs_well_in", 0.7, 0.6)
    kg.add_relation("btc_momentum", "bear", "performs_poorly_in", 0.2, 0.3)
    return kg


class TestAllocation:
    def test_bull_regime_allocates_more_to_momentum(self):
        kg = _kg_with_regime_data()
        allocator = RegimeAwareAllocator(kg, max_per_strategy=0.8)
        result = allocator.allocate(["btc_momentum", "weather_emos"], MarketRegime.BULL, 10000)
        assert result["btc_momentum"] > result["weather_emos"]

    def test_bear_regime_allocates_more_to_defensive(self):
        kg = _kg_with_regime_data()
        allocator = RegimeAwareAllocator(kg)
        result = allocator.allocate(["btc_momentum", "copy_trader"], MarketRegime.BEAR, 10000)
        assert result["copy_trader"] > result["btc_momentum"]

    def test_unknown_regime_equal_weight(self):
        kg = KnowledgeGraph()
        allocator = RegimeAwareAllocator(kg)
        result = allocator.allocate(["btc_momentum", "weather_emos", "copy_trader"], MarketRegime.UNKNOWN, 9000)
        assert abs(result["btc_momentum"] - result["weather_emos"]) < 1.0
        assert abs(result["weather_emos"] - result["copy_trader"]) < 1.0

    def test_allocations_sum_to_at_most_capital(self):
        kg = _kg_with_regime_data()
        allocator = RegimeAwareAllocator(kg)
        result = allocator.allocate(["btc_momentum", "weather_emos"], MarketRegime.BULL, 10000)
        assert sum(result.values()) <= 10000

    def test_empty_strategies_returns_empty(self):
        kg = KnowledgeGraph()
        allocator = RegimeAwareAllocator(kg)
        result = allocator.allocate([], MarketRegime.BULL, 10000)
        assert result == {}

    def test_zero_capital_returns_zeros(self):
        kg = KnowledgeGraph()
        allocator = RegimeAwareAllocator(kg)
        result = allocator.allocate(["btc_momentum"], MarketRegime.BULL, 0)
        assert result["btc_momentum"] == 0.0

    def test_max_per_strategy_limit(self):
        kg = _kg_with_regime_data()
        allocator = RegimeAwareAllocator(kg, max_per_strategy=0.3)
        result = allocator.allocate(["btc_momentum", "weather_emos"], MarketRegime.BULL, 10000)
        for s, v in result.items():
            assert v <= 10000 * 0.3 + 0.01


class TestPreferredStrategies:
    def test_get_preferred_strategies_for_bull(self):
        kg = _kg_with_regime_data()
        allocator = RegimeAwareAllocator(kg)
        preferred = allocator.get_preferred_strategies(MarketRegime.BULL)
        preferred_ids = [s.entity_id for s in preferred]
        assert "btc_momentum" in preferred_ids

    def test_get_preferred_strategies_unknown_returns_empty(self):
        kg = KnowledgeGraph()
        allocator = RegimeAwareAllocator(kg)
        preferred = allocator.get_preferred_strategies(MarketRegime.UNKNOWN)
        assert preferred == []


class TestRebalancing:
    def test_rebalance_on_regime_change(self):
        kg = _kg_with_regime_data()
        allocator = RegimeAwareAllocator(kg)
        allocator.allocate(["btc_momentum", "copy_trader"], MarketRegime.BULL, 10000)
        transition = RegimeTransition(
            from_regime=MarketRegime.BULL,
            to_regime=MarketRegime.BEAR,
            confidence=0.85,
            timestamp=datetime.now(timezone.utc),
        )
        new_alloc = allocator.rebalance(transition)
        assert len(new_alloc) == 2
        assert new_alloc["copy_trader"] > new_alloc["btc_momentum"]

    def test_rebalance_empty_returns_empty(self):
        kg = KnowledgeGraph()
        allocator = RegimeAwareAllocator(kg)
        transition = RegimeTransition(
            from_regime=MarketRegime.UNKNOWN,
            to_regime=MarketRegime.BULL,
            confidence=0.7,
            timestamp=datetime.now(timezone.utc),
        )
        result = allocator.rebalance(transition)
        assert result == {}
