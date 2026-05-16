# ADR-013: Learning Pipeline

**Status:** Accepted
**Date:** 2026-05-17

## Context

PolyEdge executes trades and records outcomes, but the feedback loop from trade results to strategy improvement is incomplete. When a trade settles (wins or loses), the system:

1. Records the outcome in `trades` table
2. Runs `trade_forensics.py` analysis on losing trades
3. Stores results in `DecisionLog`

What does NOT happen:
- Forensics insights are not fed back into the knowledge graph as structured lessons
- Lessons do not influence future strategy synthesis or genome evolution
- Winning trade analysis is minimal — only losing trades get forensic attention
- The cognitive core (ADR-009) receives no structured trade outcome data

This means the system repeats the same mistakes and fails to compound its wins. The gap analysis identified a learning pipeline as a P1 priority: "close the feedback loop from trade outcomes to brain memory."

## Decision

Introduce a learning pipeline triggered on trade settlement that flows outcomes through forensics, lesson extraction, brain storage, genome adjustment, and knowledge graph updates.

### Pipeline Stages

```
Trade Settlement Event
    │
    ▼
┌─────────────────────┐
│ 1. Forensics        │  Analyze trade outcome (win/loss/marginal)
│    (trade_forensics) │  Identify contributing factors
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ 2. Lesson Extraction│  Extract structured lessons from forensics
│    (lesson_extractor)│  Format: cause → effect → confidence → applicability
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ 3. Brain Storage    │  Store lessons in cognitive core (ADR-009)
│    (brain.remember)  │  namespace="trade_lessons"
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ 4. Genome Adjustment│  Adjust fitness scores for genomes involved
│    (genome_registry) │  Reward winning genomes, penalize losing ones
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ 5. Knowledge Graph  │  Update entity relationships
│    (knowledge_graph) │  Strengthen/weaken strategy-market-condition links
└─────────────────────┘
```

### Trigger Mechanism

The pipeline is triggered by the existing `EventBus` when a trade settles:

```python
# In strategy_executor.py, after settlement:
event_bus.emit("trade_settled", TradeSettledEvent(
    trade_id=trade.id,
    strategy_name=trade.strategy_name,
    market_id=trade.market_id,
    outcome=trade.outcome,       # WIN, LOSS, MARGINAL
    pnl_usd=trade.realized_pnl,
    genome_id=trade.genome_id,
    regime_at_entry=trade.regime,
    signal_confidence=trade.confidence,
))
```

### Lesson Structure

Lessons extracted from forensics follow a structured format:

```
TradeLesson:
    cause           — what market condition or signal triggered the trade
    effect          — the outcome (P&L, duration, slippage)
    confidence      — how confident the analysis is (0.0-1.0)
    applicability   — which market regimes/strategies this applies to
    source_trade_id — the trade that generated this lesson
    timestamp       — when the lesson was extracted
```

### Failure Handling

Each stage is isolated with try/except:
- If forensics fails, the pipeline stops (no lesson to extract)
- If lesson extraction fails, forensics results are still in DecisionLog
- If brain storage fails, the write queue in DegradedCore (ADR-009) buffers the lesson
- If genome adjustment fails, the lesson is still stored for future use
- If knowledge graph update fails, the lesson is still in the brain

No stage failure crashes the system or blocks trade execution.

## Alternatives Considered

1. **Batch learning (periodic analysis of all trades).** Rejected because it delays learning — a bad trade at 10am should influence the 11am strategy, not next week's batch job. Real-time pipeline provides immediate feedback.

2. **LLM-only lesson extraction.** Rejected because LLM calls are expensive and slow. Structured forensics analysis (deterministic) produces lessons faster and cheaper. LLMs are reserved for complex cases where deterministic analysis is insufficient.

3. **Learning only from losing trades.** Rejected because winning trades contain equally valuable information — which market conditions, signals, and genome parameters produced alpha. The pipeline processes all outcomes.

4. **Direct forensics-to-genome without brain storage.** Rejected because it bypasses the cognitive core (ADR-009) and loses cross-session learning. Lessons must be stored centrally so future strategy synthesis can access them.

## Consequences

**Positive**
- Closed feedback loop: trade outcomes directly influence future strategy decisions
- Lessons persist across sessions via cognitive core — no learning is lost
- Genome fitness scores reflect actual trading performance, not just backtest metrics
- Knowledge graph strengthens strategy-market-condition links based on real outcomes
- Pipeline is incremental — each settlement improves the system's knowledge

**Negative**
- Write amplification: each trade settlement triggers up to 5 writes (forensics, lesson, brain, genome, KG)
- Pipeline latency: the full pipeline takes 1-3 seconds per trade, which is acceptable post-settlement but would be unacceptable in the hot path
- Lesson quality depends on forensics quality — garbage forensics produces garbage lessons
- Over-learning from noise: small sample sizes can produce spurious lessons (mitigated by confidence thresholds)

## Rollback Plan

Disable the pipeline trigger by unsubscribing from the `trade_settled` event. The pipeline module (`backend/core/learning_pipeline.py`) can be deleted without affecting trade execution, forensics, or any other system component. Lessons already stored in the brain remain available for recall. Genome fitness adjustments already applied are not reversed.
