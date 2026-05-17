"""FinancialKnowledgeManager — domain layer on top of KnowledgeGraph.

Provides typed methods for registering alpha signals, strategy templates,
trade memories, and performing cross-domain reasoning using the existing
KnowledgeGraph infrastructure and CognitiveCoreAdapter.
"""
from __future__ import annotations

from typing import Any, Optional

from loguru import logger

from backend.core.agi_types import KGEntity
from backend.core.cognitive_core import CognitiveCoreAdapter
from backend.core.knowledge_graph import KnowledgeGraph


class FinancialKnowledgeManager:
    """Financial domain layer on top of KnowledgeGraph."""

    def __init__(self, kg: KnowledgeGraph, cognitive_core: CognitiveCoreAdapter):
        self._kg = kg
        self._core = cognitive_core

    # ------------------------------------------------------------------
    # Alpha signal management
    # ------------------------------------------------------------------

    def register_alpha_signal(
        self,
        signal_id: str,
        signal_type: str,
        universe: str,
        lookback: int,
        **kwargs: Any,
    ) -> KGEntity:
        """Register an alpha signal in the knowledge graph."""
        props: dict[str, Any] = {
            "signal_type": signal_type,
            "universe": universe,
            "lookback": lookback,
            "ic": kwargs.get("ic", 0.0),
            "ir": kwargs.get("ir", 0.0),
        }
        props.update(kwargs)
        entity = self._kg.add_entity("alpha_signal", f"alpha:{signal_id}", props)
        try:
            self._core.remember(
                namespace="alpha_signals",
                key=signal_id,
                value=props,
                importance=kwargs.get("importance", 0.5),
            )
        except Exception as exc:
            logger.debug("CognitiveCore remember failed for alpha {}: {}", signal_id, exc)
        return entity

    def get_alphas_for_regime(self, regime_type: str) -> list[KGEntity]:
        """Return alpha signals linked to a given regime."""
        regime_entities = self._kg.query_by_type("regime", limit=50)
        target = None
        for r in regime_entities:
            if regime_type.lower() in r.entity_id.lower():
                target = r
                break
        if target is None:
            return []
        # Use find_pattern to search for entities related TO this regime
        # (performs_well_in_<regime_name>)
        pattern_name = regime_type.split(":")[-1] if ":" in regime_type else regime_type
        results = self._kg.find_pattern(f"performs_well_in_{pattern_name}")
        return [e for e in results if e.entity_type == "alpha_signal"]

    def update_alpha_performance(self, signal_id: str, ic: float, ir: float) -> None:
        """Update IC/IR metrics for an existing alpha signal."""
        entity_id = f"alpha:{signal_id}"
        existing = self._kg.get_entity(entity_id)
        if existing is None:
            logger.warning("Alpha signal {} not found for performance update", signal_id)
            return
        props = dict(existing.properties)
        props["ic"] = ic
        props["ir"] = ir
        self._kg.add_entity("alpha_signal", entity_id, props)

    # ------------------------------------------------------------------
    # Strategy template management
    # ------------------------------------------------------------------

    def register_strategy_template(
        self,
        template_id: str,
        strategy_class: str,
        entry: dict,
        exit: dict,
        risk: dict,
        **kwargs: Any,
    ) -> KGEntity:
        """Register a strategy template in the knowledge graph."""
        props: dict[str, Any] = {
            "strategy_class": strategy_class,
            "entry": entry,
            "exit": exit,
            "risk": risk,
            "regime_effectiveness": kwargs.get("regime_effectiveness", {}),
            "description": kwargs.get("description", ""),
        }
        props.update(kwargs)
        entity = self._kg.add_entity("strategy_template", f"template:{template_id}", props)
        try:
            self._core.remember(
                namespace="strategy_templates",
                key=template_id,
                value=props,
                importance=0.6,
            )
        except Exception as exc:
            logger.debug("CognitiveCore remember failed for template {}: {}", template_id, exc)
        return entity

    def get_templates_for_regime(self, regime_type: str) -> list[KGEntity]:
        """Return strategy templates effective in a given regime."""
        templates = self._kg.query_by_type("strategy_template", limit=50)
        results: list[KGEntity] = []
        for t in templates:
            effectiveness = t.properties.get("regime_effectiveness", {})
            if regime_type in effectiveness and effectiveness[regime_type] > 0.3:
                results.append(t)
        return results

    # ------------------------------------------------------------------
    # Trade memory (enhanced)
    # ------------------------------------------------------------------

    def store_trade_with_context(
        self,
        trade_id: str,
        strategy: str,
        regime: str,
        events: list[str],
        lesson: str,
    ) -> None:
        """Store a trade with contextual information and lesson learned."""
        entity_id = f"trade_ctx:{trade_id}"
        props = {
            "trade_id": trade_id,
            "strategy": strategy,
            "regime": regime,
            "events": events,
            "lesson": lesson,
        }
        self._kg.add_entity("trade_memory", entity_id, props)
        # Link to strategy
        strategy_entity_id = f"strategy:{strategy}"
        if self._kg.get_entity(strategy_entity_id) is None:
            self._kg.add_entity("strategy", strategy_entity_id)
        self._kg.add_relation(entity_id, strategy_entity_id, "executed_by", weight=1.0, confidence=1.0)
        # Link to regime
        regime_entity_id = f"regime:{regime}"
        if self._kg.get_entity(regime_entity_id) is None:
            self._kg.add_entity("regime", regime_entity_id)
        self._kg.add_relation(entity_id, regime_entity_id, "occurred_in", weight=1.0, confidence=0.8)
        # Store in cognitive core for recall
        try:
            self._core.remember(
                namespace="trade_lessons",
                key=f"{strategy}:{regime}",
                value=lesson,
                importance=0.7,
            )
        except Exception as exc:
            logger.debug("CognitiveCore remember failed for trade {}: {}", trade_id, exc)

    def find_similar_trades(
        self, strategy: str, regime: str, limit: int = 10
    ) -> list[dict]:
        """Find trades matching strategy and/or regime context."""
        trades = self._kg.query_by_type("trade_memory", limit=limit * 3)
        results: list[dict] = []
        for t in trades:
            props = t.properties
            match_strategy = props.get("strategy") == strategy
            match_regime = props.get("regime") == regime
            if match_strategy or match_regime:
                results.append(props)
                if len(results) >= limit:
                    break
        return results

    def get_lesson_for_context(self, strategy: str, regime: str) -> Optional[str]:
        """Retrieve the most relevant lesson for a strategy+regime context."""
        # Try cognitive core first
        try:
            memories = self._core.recall(
                query=f"{strategy} {regime}",
                namespace="trade_lessons",
                limit=1,
            )
            if memories:
                return memories[0].get("value")
        except Exception as exc:
            logger.debug("CognitiveCore recall failed: {}", exc)
        # Fallback: query KG trade memories
        trades = self.find_similar_trades(strategy, regime, limit=5)
        lessons = [t.get("lesson") for t in trades if t.get("lesson")]
        return lessons[0] if lessons else None

    # ------------------------------------------------------------------
    # Cross-domain reasoning
    # ------------------------------------------------------------------

    def suggest_strategy_for_conditions(self, regime: str, asset: str) -> list[dict]:
        """Suggest strategies for given market conditions."""
        suggestions: list[dict] = []
        # Check templates for regime
        templates = self.get_templates_for_regime(regime)
        for t in templates:
            suggestions.append({
                "source": "template",
                "template_id": t.entity_id,
                "strategy_class": t.properties.get("strategy_class", ""),
                "effectiveness": t.properties.get("regime_effectiveness", {}).get(regime, 0.0),
                "description": t.properties.get("description", ""),
            })
        # Check KG for strategies linked to regime
        regime_entity = self._kg.get_entity(f"regime:{regime}")
        if regime_entity:
            related = self._kg.get_related(f"regime:{regime}", relation_type="performs_well_in")
            for r in related:
                if r.entity_type in ("strategy", "alpha_signal"):
                    suggestions.append({
                        "source": "knowledge_graph",
                        "entity_id": r.entity_id,
                        "properties": r.properties,
                    })
        # Sort by effectiveness / weight
        suggestions.sort(key=lambda s: s.get("effectiveness", s.get("properties", {}).get("weight", 0)), reverse=True)
        return suggestions

    def get_knowledge_gaps(self) -> list[str]:
        """Identify areas where the knowledge graph is sparse."""
        gaps: list[str] = []
        alphas = self._kg.query_by_type("alpha_signal", limit=100)
        if len(alphas) < 3:
            gaps.append(f"Only {len(alphas)} alpha signals registered; need more diversification")
        templates = self._kg.query_by_type("strategy_template", limit=100)
        if len(templates) < 2:
            gaps.append(f"Only {len(templates)} strategy templates; need more regime coverage")
        trades = self._kg.query_by_type("trade_memory", limit=100)
        if len(trades) < 10:
            gaps.append(f"Only {len(trades)} trade memories; need more settled trades for learning")
        # Check regime coverage
        regimes = self._kg.query_by_type("regime", limit=20)
        if len(regimes) < 3:
            gaps.append(f"Only {len(regimes)} regimes tracked; need broader regime classification")
        return gaps
