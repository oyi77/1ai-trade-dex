from __future__ import annotations

from typing import Any

from backend.core.agi_types import MarketRegime
from backend.core.knowledge_graph import KnowledgeGraph


class RegimeAwareAllocator:
    def __init__(self, kg: KnowledgeGraph, max_per_strategy: float = 0.3):
        self._kg = kg
        self._max_per_strategy = max_per_strategy
        self._current_regime = MarketRegime.UNKNOWN
        self._current_allocations: dict[str, float] = {}

    def allocate(self, strategies: list[str], regime: MarketRegime, capital: float) -> dict[str, float]:
        if not strategies or capital <= 0:
            return {s: 0.0 for s in strategies}

        self._current_regime = regime

        if regime == MarketRegime.UNKNOWN:
            allocations = self._equal_weight(strategies, capital)
        else:
            allocations = self._regime_weighted(strategies, regime, capital)

        total = sum(allocations.values())
        if total > capital:
            scale = capital / total
            allocations = {s: v * scale for s, v in allocations.items()}

        for s in allocations:
            allocations[s] = min(allocations[s], capital * self._max_per_strategy)

        total = sum(allocations.values())
        if total > capital:
            scale = capital / total
            allocations = {s: v * scale for s, v in allocations.items()}

        self._current_allocations = allocations
        return allocations

    def get_preferred_strategies(self, regime: MarketRegime) -> list[str]:
        if regime == MarketRegime.UNKNOWN:
            return []
        return self._kg.get_strategies_for_regime(regime)

    def rebalance(self, transition: Any) -> dict[str, float]:
        new_regime = transition.to_regime if hasattr(transition, 'to_regime') else MarketRegime.UNKNOWN
        strategies = list(self._current_allocations.keys()) if self._current_allocations else []
        capital = sum(self._current_allocations.values()) if self._current_allocations else 0
        if not strategies or capital <= 0:
            return {}
        return self.allocate(strategies, new_regime, capital)

    def _equal_weight(self, strategies: list[str], capital: float) -> dict[str, float]:
        per = capital / len(strategies)
        return {s: per for s in strategies}

    def _regime_weighted(self, strategies: list[str], regime: MarketRegime, capital: float) -> dict[str, float]:
        preferred = self._kg.get_strategies_for_regime(regime)
        preferred_ids = {s.entity_id for s in preferred}

        weights: dict[str, float] = {}
        for s in strategies:
            if s in preferred_ids:
                perf = self._kg.get_regime_performance(s)
                regime_perf = perf.get(regime.value, {})
                weight = regime_perf.get("weight", 0.5)
                weights[s] = max(weight, 0.1)
            else:
                weights[s] = 0.1

        total_weight = sum(weights.values())
        if total_weight == 0:
            return self._equal_weight(strategies, capital)

        return {s: (w / total_weight) * capital for s, w in weights.items()}
