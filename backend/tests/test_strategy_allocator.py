"""Tests for RegimeAwareAllocator — regime-dependent allocation, bounds, rebalancing."""

from datetime import datetime, timezone
from unittest.mock import patch

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
        result = allocator.allocate(
            ["btc_momentum", "weather_emos"], MarketRegime.BULL, 10000
        )
        assert result["btc_momentum"] > result["weather_emos"]

    def test_bear_regime_allocates_more_to_defensive(self):
        kg = _kg_with_regime_data()
        allocator = RegimeAwareAllocator(kg)
        result = allocator.allocate(
            ["btc_momentum", "copy_trader"], MarketRegime.BEAR, 10000
        )
        assert result["copy_trader"] > result["btc_momentum"]

    def test_unknown_regime_equal_weight(self):
        kg = KnowledgeGraph()
        allocator = RegimeAwareAllocator(kg)
        result = allocator.allocate(
            ["btc_momentum", "weather_emos", "copy_trader"], MarketRegime.UNKNOWN, 9000
        )
        assert abs(result["btc_momentum"] - result["weather_emos"]) < 1.0
        assert abs(result["weather_emos"] - result["copy_trader"]) < 1.0

    def test_allocations_sum_to_at_most_capital(self):
        kg = _kg_with_regime_data()
        allocator = RegimeAwareAllocator(kg)
        result = allocator.allocate(
            ["btc_momentum", "weather_emos"], MarketRegime.BULL, 10000
        )
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
        result = allocator.allocate(
            ["btc_momentum", "weather_emos"], MarketRegime.BULL, 10000
        )
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


class TestTemporalAndCategoryRouting:
    def test_get_current_hour_et(self):
        kg = KnowledgeGraph()
        allocator = RegimeAwareAllocator(kg)
        hour = allocator._get_current_hour_et()
        assert isinstance(hour, int)
        assert 0 <= hour <= 23

    def test_temporal_multiplier_scaling(self):
        kg = KnowledgeGraph()
        allocator = RegimeAwareAllocator(kg)
        
        # High retail hours (9, 10): maker strategies scaled up, taker scaled down
        assert allocator._get_hourly_edge_multiplier(9, "market_maker") == 1.25
        assert allocator._get_hourly_edge_multiplier(9, "hft_taker") == 0.85

        # Very low retail hours (23): maker scaled down, taker scaled up
        assert allocator._get_hourly_edge_multiplier(23, "market_maker") == 0.70
        assert allocator._get_hourly_edge_multiplier(23, "hft_taker") == 1.30

        # Baseline hours: 1.0 for both
        assert allocator._get_hourly_edge_multiplier(12, "market_maker") == 1.0
        assert allocator._get_hourly_edge_multiplier(12, "hft_taker") == 1.0

    def test_temporal_allocation_shift(self):
        kg = _kg_with_regime_data()
        allocator = RegimeAwareAllocator(kg, max_per_strategy=0.8)
        
        # At hour 9 (high retail), maker strategy (e.g. weather_emos, let's treat it as maker by aliasing it)
        # Wait, weather_emos does not have "maker" in name. Let's register "weather_maker"
        kg.add_entity("strategy", "weather_maker", {"win_rate": 0.55})
        kg.add_relation("weather_maker", "bull", "performs_well_in", 0.4, 0.3)

        # Allocate at hour 9 (maker favored)
        res_hour_9 = allocator.allocate(
            ["btc_momentum", "weather_maker"], MarketRegime.BULL, 10000, hour_et=9
        )

        # Allocate at hour 23 (maker penalized)
        res_hour_23 = allocator.allocate(
            ["btc_momentum", "weather_maker"], MarketRegime.BULL, 10000, hour_et=23
        )

        # The ratio of weather_maker allocation should be higher at hour 9 than hour 23
        ratio_9 = res_hour_9["weather_maker"] / sum(res_hour_9.values())
        ratio_23 = res_hour_23["weather_maker"] / sum(res_hour_23.values())
        assert ratio_9 > ratio_23

    @patch("backend.core.strategy_allocator.query_parquet_analytics")
    @patch("os.path.exists")
    def test_category_multiplier_from_parquet(self, mock_exists, mock_query):
        kg = KnowledgeGraph()
        allocator = RegimeAwareAllocator(kg)

        mock_exists.return_value = True
        # Mock high win rate (win_rate >= 0.6 -> multiplier 1.2)
        mock_query.return_value = [{"win_rate": 0.75}]
        mult = allocator._get_category_edge_multiplier("politics", "market_maker")
        assert mult == 1.2

        # Mock low win rate (win_rate <= 0.4 -> multiplier 0.8)
        mock_query.return_value = [{"win_rate": 0.25}]
        mult = allocator._get_category_edge_multiplier("politics", "market_maker")
        assert mult == 0.8

        # Mock missing or None win rate
        mock_query.return_value = []
        mult = allocator._get_category_edge_multiplier("politics", "market_maker")
        assert mult == 1.0

