"""DEPRECATED: Use backend.core.learning_pipeline instead.

Learning Pipeline — post-settlement feedback loop (ADR-013).

Flows trade settlement events through forensics analysis, lesson extraction,
brain storage, genome fitness adjustment, and knowledge graph updates.

Each stage is isolated with try/except — no stage failure crashes the system
or blocks trade execution.


This module will be removed in a future release.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from loguru import logger

from backend.monitoring.agi_metrics import (
    record_pipeline_processing,
    record_pipeline_lesson_stored,
    record_pipeline_error,
)
from backend.db.utils import utcnow

# ---------------------------------------------------------------------------
# Pipeline metrics
# ---------------------------------------------------------------------------


@dataclass
class PipelineMetrics:
    """Tracks pipeline processing statistics."""

    total_processed: int = 0
    lessons_stored: int = 0
    forensics_errors: int = 0
    extraction_errors: int = 0
    brain_errors: int = 0
    genome_errors: int = 0
    kg_errors: int = 0
    total_processing_ms: float = 0.0

    @property
    def avg_processing_ms(self) -> float:
        if self.total_processed == 0:
            return 0.0
        return self.total_processing_ms / self.total_processed

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_processed": self.total_processed,
            "lessons_stored": self.lessons_stored,
            "forensics_errors": self.forensics_errors,
            "extraction_errors": self.extraction_errors,
            "brain_errors": self.brain_errors,
            "genome_errors": self.genome_errors,
            "kg_errors": self.kg_errors,
            "total_processing_ms": round(self.total_processing_ms, 2),
            "avg_processing_ms": round(self.avg_processing_ms, 2),
        }


# ---------------------------------------------------------------------------
# Trade lesson structure
# ---------------------------------------------------------------------------


@dataclass
class TradeLesson:
    """Structured lesson extracted from a trade outcome."""

    cause: str
    effect: str
    confidence: float
    applicability: Dict[str, Any]
    source_trade_id: int
    strategy_name: str
    outcome: str  # "win", "loss", "marginal"
    pnl: float
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cause": self.cause,
            "effect": self.effect,
            "confidence": self.confidence,
            "applicability": self.applicability,
            "source_trade_id": self.source_trade_id,
            "strategy_name": self.strategy_name,
            "outcome": self.outcome,
            "pnl": self.pnl,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Lesson extractor
# ---------------------------------------------------------------------------


class LessonExtractor:
    """Extracts structured lessons from trade forensics results."""

    def extract_from_forensics(
        self,
        forensics_result: Dict[str, Any],
        trade_id: int,
        strategy_name: str,
        outcome: str,
        pnl: float,
        regime: Optional[str] = None,
    ) -> Optional[TradeLesson]:
        """Extract a TradeLesson from forensics analysis output.

        Returns None if forensics result is insufficient for lesson extraction.
        """
        root_cause = forensics_result.get("root_cause", "unknown")
        confidence = forensics_result.get("confidence", 0.5)
        factors = forensics_result.get("contributing_factors", [])

        # Skip lessons with very low confidence
        if confidence < 0.2:
            return None

        cause_description = root_cause
        if factors:
            cause_description = f"{root_cause}: {', '.join(factors)}"

        effect_description = f"{'gained' if pnl >= 0 else 'lost'} ${abs(pnl):.2f}"
        suggestions = forensics_result.get("suggestions", [])
        if suggestions:
            effect_description += f" — suggest: {suggestions[0]}"

        applicability: Dict[str, Any] = {
            "strategies": [strategy_name],
            "root_cause": root_cause,
        }
        if regime:
            applicability["regimes"] = [regime]

        return TradeLesson(
            cause=cause_description,
            effect=effect_description,
            confidence=confidence,
            applicability=applicability,
            source_trade_id=trade_id,
            strategy_name=strategy_name,
            outcome=outcome,
            pnl=pnl,
        )

    def extract_from_winning_trade(
        self,
        trade_id: int,
        strategy_name: str,
        pnl: float,
        regime: Optional[str] = None,
        signal_confidence: Optional[float] = None,
        outcome: str = "win",
    ) -> TradeLesson:
        """Extract a lesson from a winning (or marginal) trade (no forensics needed)."""
        confidence = signal_confidence if signal_confidence is not None else 0.5
        confidence = max(0.3, min(0.9, confidence))  # clamp

        applicability: Dict[str, Any] = {
            "strategies": [strategy_name],
        }
        if regime:
            applicability["regimes"] = [regime]

        return TradeLesson(
            cause=f"{outcome} trade by {strategy_name}",
            effect=f"{'gained' if pnl >= 0 else 'lost'} ${abs(pnl):.2f}",
            confidence=confidence,
            applicability=applicability,
            source_trade_id=trade_id,
            strategy_name=strategy_name,
            outcome=outcome,
            pnl=pnl,
        )


# ---------------------------------------------------------------------------
# Learning pipeline
# ---------------------------------------------------------------------------


class LearningPipeline:
    """Post-settlement learning pipeline (ADR-013).

    Flows: settlement → forensics → lesson extraction → brain.remember()
    → genome adjustment → KG update.

    Each stage is isolated — no stage failure blocks settlement or crashes
    the system. Processing is async to avoid blocking the settlement path.
    """

    def __init__(
        self,
        cognitive_core: Optional[Any] = None,
        forensics: Optional[Any] = None,
    ) -> None:
        self._core = cognitive_core
        self._forensics = forensics
        self._lesson_extractor = LessonExtractor()
        self._metrics = PipelineMetrics()

    @property
    def metrics(self) -> PipelineMetrics:
        return self._metrics

    async def process_settlement(
        self,
        trade_id: int,
        strategy_name: str,
        market_id: str,
        outcome: str,
        pnl_usd: float,
        genome_id: Optional[str] = None,
        regime_at_entry: Optional[str] = None,
        signal_confidence: Optional[float] = None,
    ) -> Optional[TradeLesson]:
        """Process a settlement event through the full learning pipeline.

        Args:
            trade_id: Database ID of the settled trade.
            strategy_name: Strategy that generated the trade.
            market_id: Market ticker/identifier.
            outcome: "win", "loss", or "marginal".
            pnl_usd: Realized P&L in USD.
            genome_id: Optional genome ID for fitness adjustment.
            regime_at_entry: Market regime at trade entry time.
            signal_confidence: Signal confidence at trade entry.

        Returns:
            The extracted TradeLesson, or None if extraction failed.
        """
        t0 = time.monotonic()
        lesson: Optional[TradeLesson] = None

        try:
            # Stage 1: Forensics analysis (losses only; wins skip forensics)
            forensics_result: Optional[Dict[str, Any]] = None
            if outcome == "loss":
                forensics_result = await self._run_forensics(trade_id)

            # Stage 2: Lesson extraction
            lesson = self._extract_lesson(
                forensics_result,
                trade_id,
                strategy_name,
                outcome,
                pnl_usd,
                regime_at_entry,
                signal_confidence,
            )

            if lesson is None:
                # E-124: Don't increment total_processed here — it's incremented in finally block
                elapsed_ms = (time.monotonic() - t0) * 1000
                self._metrics.total_processing_ms += elapsed_ms
                record_pipeline_processing(elapsed_ms / 1000.0)
                return None

            # Stage 3: Store in brain
            await self._store_in_brain(lesson)

            # Stage 4: Genome fitness adjustment
            if genome_id:
                await self._adjust_genome_fitness(genome_id, outcome, pnl_usd)

            # Stage 5: Knowledge graph update
            await self._update_knowledge_graph(
                trade_id, strategy_name, market_id, outcome, pnl_usd, lesson
            )

            # Stage 6: Wire to AGI self-tuner (non-blocking)
            try:
                from backend.core.agi_self_tuner import get_agi_self_tuner

                tuner = get_agi_self_tuner()
                await tuner.process_settlement(
                    trade_id=trade_id,
                    strategy_name=strategy_name,
                    market_id=market_id,
                    outcome=outcome,
                    pnl_usd=pnl_usd,
                )
            except Exception:
                logger.debug(
                    f"[LearningPipeline] Self-tuner hook failed for trade {trade_id}"
                )

            self._metrics.lessons_stored += 1
            record_pipeline_lesson_stored()

        except Exception:
            record_pipeline_error("unexpected")
            logger.exception(
                f"[LearningPipeline] Unexpected error processing trade {trade_id}"
            )

        finally:
            self._metrics.total_processed += 1
            elapsed_ms = (time.monotonic() - t0) * 1000
            self._metrics.total_processing_ms += elapsed_ms
            record_pipeline_processing(elapsed_ms / 1000.0)

        return lesson

    # ── Stage implementations ──

    async def _run_forensics(self, trade_id: int) -> Optional[Dict[str, Any]]:
        """Stage 1: Run forensics on a losing trade."""
        if self._forensics is None:
            logger.debug(
                f"[LearningPipeline] No forensics engine — skipping trade {trade_id}"
            )
            return None

        try:
            result = await self._forensics.analyze_losing_trade(trade_id)
            return result
        except Exception:
            self._metrics.forensics_errors += 1
            record_pipeline_error("forensics")
            logger.exception(
                f"[LearningPipeline] Forensics failed for trade {trade_id}"
            )
            return None

    def _extract_lesson(
        self,
        forensics_result: Optional[Dict[str, Any]],
        trade_id: int,
        strategy_name: str,
        outcome: str,
        pnl: float,
        regime: Optional[str],
        signal_confidence: Optional[float],
    ) -> Optional[TradeLesson]:
        """Stage 2: Extract a structured lesson from trade outcome."""
        try:
            if outcome == "loss" and forensics_result:
                return self._lesson_extractor.extract_from_forensics(
                    forensics_result, trade_id, strategy_name, outcome, pnl, regime
                )
            elif outcome == "win":
                return self._lesson_extractor.extract_from_winning_trade(
                    trade_id, strategy_name, pnl, regime, signal_confidence
                )
            else:
                # Marginal or unknown — extract minimal lesson
                return self._lesson_extractor.extract_from_winning_trade(
                    trade_id,
                    strategy_name,
                    pnl,
                    regime,
                    signal_confidence,
                    outcome=outcome,
                )
        except Exception:
            self._metrics.extraction_errors += 1
            record_pipeline_error("extraction")
            logger.exception(
                f"[LearningPipeline] Lesson extraction failed for trade {trade_id}"
            )
            return None

    async def _store_in_brain(self, lesson: TradeLesson) -> None:
        """Stage 3: Store lesson in cognitive core."""
        if self._core is None:
            logger.debug("[LearningPipeline] No cognitive core — lesson not stored")
            return

        try:
            key = f"trade_{lesson.source_trade_id}_{lesson.outcome}"
            self._core.remember(
                namespace="trade_lessons",
                key=key,
                value=lesson.to_dict(),
                importance=lesson.confidence,
            )
            logger.info(
                f"[LearningPipeline] Stored lesson for trade {lesson.source_trade_id} "
                f"({lesson.strategy_name}, {lesson.outcome}, conf={lesson.confidence:.2f})"
            )
        except Exception:
            self._metrics.brain_errors += 1
            record_pipeline_error("brain")
            logger.exception(
                f"[LearningPipeline] Brain storage failed for trade {lesson.source_trade_id}"
            )

    async def _adjust_genome_fitness(
        self, genome_id: str, outcome: str, pnl: float
    ) -> None:
        """Stage 4: Adjust genome fitness based on trade outcome.

        Uses botstate_mutex for writes to the genome registry.
        """
        try:
            from backend.models.database import GenomeRegistry, botstate_mutex

            async with botstate_mutex:
                from backend.db.utils import get_db_session

                with get_db_session() as db:
                    genome = (
                        db.query(GenomeRegistry)
                        .filter(GenomeRegistry.genome_id == genome_id)
                        .first()
                    )

                    if genome is None:
                        logger.warning(
                            f"[LearningPipeline] Genome {genome_id} not found — skipping fitness adjustment"
                        )
                        return

                    # Update trade count
                    genome.trade_count = (genome.trade_count or 0) + 1

                    # Update total P&L
                    genome.total_pnl = (genome.total_pnl or 0.0) + pnl

                    # Update win rate (exponential moving average)
                    current_count = genome.trade_count
                    current_wr = genome.win_rate or 0.0
                    is_win = 1.0 if outcome == "win" else 0.0
                    # EMA with alpha = 1/N, capped at 100 trades window
                    alpha = 1.0 / min(current_count, 100)
                    genome.win_rate = current_wr + alpha * (is_win - current_wr)

                    # Adjust composite fitness score
                    # Reward wins, penalize losses, with diminishing magnitude
                    fitness_delta = 0.0
                    if outcome == "win":
                        fitness_delta = 0.01 * min(abs(pnl), 50.0) / 50.0
                    elif outcome == "loss":
                        fitness_delta = -0.01 * min(abs(pnl), 50.0) / 50.0

                    current_fitness = genome.fitness_score or 0.5
                    genome.fitness_score = max(
                        0.0, min(1.0, current_fitness + fitness_delta)
                    )
                    genome.fitness_updated_at = utcnow()

                    db.commit()

            logger.debug(
                f"[LearningPipeline] Genome {genome_id} fitness adjusted: "
                f"outcome={outcome}, pnl=${pnl:+.2f}"
            )
        except Exception:
            self._metrics.genome_errors += 1
            record_pipeline_error("genome")
            logger.exception(
                f"[LearningPipeline] Genome fitness adjustment failed for {genome_id}"
            )

    async def _update_knowledge_graph(
        self,
        trade_id: int,
        strategy_name: str,
        market_id: str,
        outcome: str,
        pnl: float,
        lesson: TradeLesson,
    ) -> None:
        """Stage 5: Update knowledge graph with trade lesson."""
        try:
            from backend.core.knowledge_graph import KnowledgeGraph
            from backend.db.utils import get_db_session

            with get_db_session() as kg_db:
                kg = KnowledgeGraph(session=kg_db)

                # Store trade memory (same as settlement does)
                kg.store_trade_memory(
                    trade_id=trade_id,
                    strategy=strategy_name,
                    market_id=market_id,
                    signal_reasoning=lesson.cause,
                    outcome_pnl=pnl,
                    outcome_correct=(outcome == "win"),
                )

                # Add lesson-specific relation: strategy → root_cause
                root_cause = lesson.applicability.get("root_cause", "unknown")
                cause_entity_id = f"cause:{root_cause}"
                kg.add_entity(
                    "root_cause",
                    cause_entity_id,
                    {
                        "cause": root_cause,
                        "lesson_count": 1,
                    },
                )
                kg.add_relation(
                    from_entity_id=f"strategy:{strategy_name}",
                    to_entity_id=cause_entity_id,
                    relation_type="associated_with",
                    weight=lesson.confidence,
                    confidence=lesson.confidence,
                )

        except Exception:
            self._metrics.kg_errors += 1
            record_pipeline_error("knowledge_graph")
            logger.exception(
                f"[LearningPipeline] KG update failed for trade {trade_id}"
            )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_learning_pipeline: Optional[LearningPipeline] = None


def get_learning_pipeline() -> LearningPipeline:
    """Get or create the module-level LearningPipeline singleton."""
    global _learning_pipeline
    if _learning_pipeline is None:
        _learning_pipeline = LearningPipeline()
    return _learning_pipeline


def set_learning_pipeline(pipeline: LearningPipeline) -> None:
    """Replace the module-level singleton (for testing or reconfiguration)."""
    global _learning_pipeline
    _learning_pipeline = pipeline
