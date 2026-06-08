from __future__ import annotations
from backend.core.logger import get_logger
logger = get_logger(__name__)

import os
from datetime import datetime, timezone
from typing import Any, Optional

from backend.config import settings
from backend.core.agi_types import MarketRegime
from backend.core.db_archiver import query_parquet_analytics
from backend.core.knowledge_graph import KnowledgeGraph


class RegimeAwareAllocator:
    def __init__(self, kg: KnowledgeGraph, max_per_strategy: float = 0.3):
        self._kg = kg
        self._max_per_strategy = max_per_strategy
        self._current_regime = MarketRegime.UNKNOWN
        self._current_allocations: dict[str, float] = {}

    def _get_current_hour_et(self) -> int:
        try:
            import zoneinfo

            et_tz = zoneinfo.ZoneInfo("US/Eastern")
            return datetime.now(et_tz).hour
        except Exception:
            utc_now = datetime.now(timezone.utc)
            return (utc_now.hour - 5) % 24

    def _get_hourly_edge_multiplier(self, hour_et: int, strategy: str) -> float:
        is_maker = "maker" in strategy.lower() or "calibration" in strategy.lower()
        if hour_et in [9, 10]:
            return 1.25 if is_maker else 0.85
        elif hour_et == 14:
            return 0.90 if is_maker else 1.10
        elif hour_et == 23:
            return 0.70 if is_maker else 1.30
        return 1.0

    def _get_category_edge_multiplier(
        self, category: Optional[str], strategy: str
    ) -> float:
        if not category:
            return 1.0

        parquet_dir = getattr(settings, "PARQUET_DIR", "data/parquet")
        trades_dir = os.path.join(parquet_dir, "trades")

        if os.path.exists(trades_dir):
            try:
                sql = f"""
                    SELECT AVG(CASE WHEN result = 'win' THEN 1.0 ELSE 0.0 END) AS win_rate
                    FROM {{table}}
                    WHERE category = '{category}' AND strategy = '{strategy}'
                """
                res = query_parquet_analytics(trades_dir, sql)
                if res and res[0].get("win_rate") is not None:
                    win_rate = float(res[0]["win_rate"])
                    if win_rate >= 0.6:
                        return 1.2
                    elif win_rate <= 0.4:
                        return 0.8
            except Exception:
                logger.debug(f"strategy_allocator: failed to get historical win_rate for {strategy}/{category}")

        try:
            from backend.db.utils import get_db_session
            from backend.models.database import Trade

            with get_db_session() as db:
                recent = (
                    db.query(Trade)
                    .filter(
                        Trade.strategy == strategy,
                        Trade.market_type == category,
                        Trade.settled.is_(True),
                    )
                    .all()
                )
                if recent:
                    wins = sum(1.0 for t in recent if t.result == "win")
                    win_rate = wins / len(recent)
                    if win_rate >= 0.6:
                        return 1.2
                    elif win_rate <= 0.4:
                        return 0.8
        except Exception:
            logger.debug(f"strategy_allocator: failed to compute win_rate for {strategy}/{category}")

        return 1.0

    def allocate(
        self,
        strategies: list[str],
        regime: MarketRegime,
        capital: float,
        hour_et: Optional[int] = None,
        category: Optional[str] = None,
    ) -> dict[str, float]:
        if not strategies or capital <= 0:
            return {s: 0.0 for s in strategies}

        self._current_regime = regime

        if regime == MarketRegime.UNKNOWN:
            allocations = self._equal_weight(strategies, capital)
        else:
            allocations = self._regime_weighted(strategies, regime, capital)

        if hour_et is None:
            hour_et = self._get_current_hour_et()

        scaled_weights: dict[str, float] = {}
        for s in strategies:
            base_alloc = allocations.get(s, 0.0)
            temporal_mult = self._get_hourly_edge_multiplier(hour_et, s)
            category_mult = self._get_category_edge_multiplier(category, s)
            scaled_weight = base_alloc * temporal_mult * category_mult
            scaled_weights[s] = scaled_weight

        total_weight = sum(scaled_weights.values())
        if total_weight > 0:
            allocations = {
                s: (w / total_weight) * capital for s, w in scaled_weights.items()
            }
        else:
            allocations = {s: 0.0 for s in strategies}

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
        new_regime = (
            transition.to_regime
            if hasattr(transition, "to_regime")
            else MarketRegime.UNKNOWN
        )
        strategies = (
            list(self._current_allocations.keys()) if self._current_allocations else []
        )
        capital = (
            sum(self._current_allocations.values()) if self._current_allocations else 0
        )
        if not strategies or capital <= 0:
            return {}
        return self.allocate(strategies, new_regime, capital)

    def _equal_weight(self, strategies: list[str], capital: float) -> dict[str, float]:
        per = capital / len(strategies)
        return {s: per for s in strategies}

    def _regime_weighted(
        self, strategies: list[str], regime: MarketRegime, capital: float
    ) -> dict[str, float]:
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
