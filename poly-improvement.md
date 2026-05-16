# PolyEdge → AGI Trading Framework: Claude Code Prompt

> Copy seluruh isi dokumen ini dan paste langsung ke Claude Code sebagai opening prompt.

---

## Mandatory Pre-Read (read ALL before touching any code)

- `AGENTS.md` (root + ALL subdirectory `AGENTS.md` files)
- `ARCHITECTURE.md`, `CLAUDE.md`, `IMPLEMENTATION_GAPS.md`
- `docs/architecture/*.md` (every ADR)
- Fetch and fully read: https://github.com/oyi77/1ai-hub
- Fetch and study (architecture patterns only, not copy-paste):
  - https://github.com/hummingbot/hummingbot
  - https://github.com/freqtrade/freqtrade
  - https://github.com/tensortrade-org/tensortrade
  - https://github.com/AI4Finance-Foundation/FinRL
  - https://github.com/microsoft/autogen
  - https://github.com/crewAIInc/crewAI

---

## Mission

Transform PolyEdge into a best-in-class, modular **AGI trading framework** optimized across three dimensions:

- **Performance** — sub-second signal latency, efficient memory, horizontal scalability
- **Learning** — persistent cross-session learning that compounds over time
- **Evolve** — self-improving strategies without human intervention within risk bounds

---

## Core Design Philosophy

PolyEdge must become a **cognitive trading system**, not just an automated bot.

The distinction:
- A bot reacts to signals
- A cognitive system learns *why* signals work, builds mental models of markets, and evolves its own understanding over time

The `1ai-hub` repo is the **persistent cognitive core** — the long-term memory, personality, and reasoning identity of this system. Everything else is infrastructure. If 1ai-hub goes offline, the system degrades gracefully (amnesia mode) but does NOT crash.

```
Other engines (freqtrade, FinRL, etc.)  →  Hands & feet
PolyEdge (orchestration, execution)     →  Nervous system
1ai-hub                                 →  Brain + long-term memory
```

---

## Non-Negotiable Architectural Invariants

These CANNOT be changed under any circumstances:

1. `risk_manager.py`, `circuit_breaker.py`, `settlement.py` — never weakened without a new ADR
2. Trade rows are **append-only** — never mutate historical records
3. `botstate_mutex` — always acquired before BotState read-modify-write
4. All AGI strategies start in **SHADOW** — never skip to LIVE
5. `backend/domain/` — zero imports from `core/`, `api/`, `strategies/`
6. All SSE/WS routes through `authorize_realtime_access()`
7. All DB schema changes require Alembic migration
8. Never commit `.env`
9. `1ai-hub` is the **only** authoritative brain — no parallel competing memory systems

---

## PHASE 1 — Research & Gap Analysis

Fetch all repos listed above. For each, extract patterns relevant to performance, learning, and evolution. Identify what PolyEdge is **missing**, not what it already has.

**Produce:** `docs/research/framework-gap-analysis.md`

```markdown
## Executive Summary
[3-paragraph overview of biggest gaps]

## Pattern Adoption Matrix
| Pattern | Source Repo | Gap in PolyEdge | Complexity (1-5) | Priority (P0/P1/P2) |

## 1ai-hub Integration Analysis
[What 1ai-hub provides, what's missing for deep integration,
recommended interface contract between PolyEdge and 1ai-hub]

## Technology Recommendations

### Evolutionary/Genetic (DEAP vs PyGAD vs current genome system)
[Compare, recommend one, explain why]

### Reinforcement Learning (Ray RLlib vs Stable Baselines3)
[Compare for prediction market context specifically, recommend one]

### Multi-Agent (AutoGen vs CrewAI vs current agi_orchestrator.py)
[Compare, recommend one, explain integration point with existing orchestrator]

## Risk Register
| Risk | Affected Module | Severity | Mitigation |

## Migration Sequence
[Ordered list of changes that minimizes breakage]
```

Do NOT write any production code in Phase 1.

---

## PHASE 2 — ADR Suite

Write ADRs for every architectural decision before implementing. Format: `docs/architecture/adr-00N-<slug>.md`

**Required ADRs (minimum):**

| File | Topic |
|------|-------|
| `adr-007-cognitive-core-interface.md` | 1ai-hub as persistent brain, fault tolerance contract |
| `adr-008-evolution-backend.md` | DEAP/PyGAD integration with existing genome system |
| `adr-009-rl-environment.md` | RL framework choice and Gym-compatible wrapper design |
| `adr-010-multi-agent-topology.md` | Agent roles, communication protocol, authority hierarchy |
| `adr-011-learning-pipeline.md` | How trade outcomes flow back into brain memory |
| `adr-012-performance-targets.md` | Latency SLOs, memory budgets, parallelism boundaries |

Each ADR must explicitly state:
- What existing invariants are preserved
- Rollback plan if the decision proves wrong
- How 1ai-hub interface contract is maintained

Do NOT write production code until Phase 2 ADRs are complete.

---

## PHASE 3 — Core Abstractions

### 3A. CognitiveCoreAdapter (`backend/core/cognitive_core.py`)

Single interface between PolyEdge and 1ai-hub. ALL memory reads/writes and LLM routing MUST go through this — no direct calls to Anthropic/Groq/OpenAI from strategy code.

```python
class CognitiveCoreAdapter(ABC):
    """
    The persistent brain interface. PolyEdge knows nothing about
    HOW memory works — only that it can store and retrieve.
    """

    # Memory operations
    async def remember(self,
                       namespace: str,       # e.g. "market_regimes", "strategy_outcomes"
                       key: str,
                       value: dict,
                       importance: float = 0.5  # 0-1, affects retention priority
                      ) -> None: ...

    async def recall(self,
                     query: str,
                     namespace: str | None = None,
                     limit: int = 10,
                     min_relevance: float = 0.7
                    ) -> list[Memory]: ...

    async def forget(self, namespace: str, key: str) -> None: ...

    # Reasoning operations
    async def reason(self,
                     context: CognitiveContext,    # market state, portfolio, regime
                     question: str,
                     personality_mode: str = "default"  # maps to 1ai-hub personas
                    ) -> Reasoning: ...

    async def route_llm(self,
                        prompt: str,
                        task_type: LLMTaskType,    # SIGNAL, SYNTHESIS, FORENSICS, etc.
                        max_cost_usd: float = 0.10
                       ) -> LLMResponse: ...

    # Introspection
    async def health_check(self) -> CoreHealth: ...
    async def memory_stats(self) -> MemoryStats: ...


class OneAIHubCore(CognitiveCoreAdapter):
    """Production implementation backed by 1ai-hub"""
    ...


class DegradedCore(CognitiveCoreAdapter):
    """
    Amnesia mode — runs when 1ai-hub is unreachable.
    Uses local SQLite KV store, no personality, basic LLM routing.
    Queues all missed memory writes for replay when brain reconnects.
    """
    ...


class MockCore(CognitiveCoreAdapter):
    """For tests and CI — deterministic, no API calls"""
    ...
```

Wire `CognitiveCoreAdapter` into:
- `agi_orchestrator.py` — replace direct LLM calls
- `knowledge_graph.py` — delegate persistence to brain
- `dynamic_prompt_engine.py` — route through brain's personality system
- `strategy_synthesizer.py` — use brain for strategy ideation
- `trade_forensics.py` — store insights into brain memory

---

### 3B. EvolutionHarness (`backend/core/evolution_harness.py`)

Pluggable evolution engine wrapping the existing genome system.

```python
class EvolutionBackend(ABC):
    async def mutate(self, genome: StrategyGenome,
                     context: EvolutionContext) -> StrategyGenome: ...
    async def crossover(self, parents: list[StrategyGenome]) -> StrategyGenome: ...
    async def select(self, population: list[GenomeWithFitness],
                     selection_pressure: float = 0.5) -> list[StrategyGenome]: ...
    async def evaluate_fitness(self, genome: StrategyGenome,
                               trades: list[Trade]) -> FitnessScore: ...


class DEAPEvolution(EvolutionBackend):
    """DEAP-based genetic algorithm — recommended primary"""
    ...


class RLEvolution(EvolutionBackend):
    """
    RL-based strategy parameter optimization.
    Each genome parameter = action dimension.
    Trade PnL / Sharpe = reward signal.
    """
    ...


class HybridEvolution(EvolutionBackend):
    """
    GA for genome structure discovery, RL for parameter fine-tuning.
    This is the target long-term architecture.
    """
    ...
```

Preserve `evolution_jobs.py` as scheduler entry point. Replace its internal logic to call through `EvolutionHarness`.

---

### 3C. MultiAgentCouncil (`backend/core/agent_council.py`)

Replace the `agi_orchestrator` monolith with a council of specialized agents. Each agent has a single responsibility and communicates via typed messages.

```python
AGENT_ROLES = {
    "analyst":     "Reads market data, detects regime, generates hypotheses",
    "synthesizer": "Creates new strategies from building blocks + brain memory",
    "critic":      "Challenges signals, runs counter-arguments, assigns confidence",
    "executor":    "Routes approved signals through RiskManager to order_executor",
    "historian":   "Writes outcomes to brain memory, runs forensics on losses",
    "evolver":     "Runs evolution cycles, manages genome population health",
}


class AgentMessage(BaseModel):
    from_agent: str
    to_agent: str | Literal["broadcast"]
    message_type: str
    payload: dict
    requires_response: bool = False
    timeout_seconds: float = 30.0


class BaseAgent(ABC):
    role: str
    brain: CognitiveCoreAdapter  # ALL agents share the same brain instance

    async def handle(self, message: AgentMessage) -> AgentMessage | None: ...
    async def on_market_tick(self, tick: MarketTick) -> None: ...
```

**Authority hierarchy (who can override whom):**

```
RiskManager (non-agent, always wins)
    └── executor
        └── critic
            └── analyst, synthesizer, historian, evolver
```

---

### 3D. RLEnvironment (`backend/core/rl_environment.py`)

Gym-compatible wrapper for prediction market trading. Used by `RLEvolution` to train strategy parameters.

```python
class PredictionMarketEnv(gymnasium.Env):
    """
    State space:  market features, portfolio state, regime, active signals
    Action space: [BUY, SELL, HOLD] × position_size (continuous)
    Reward:       risk-adjusted PnL (Sharpe increment per step)

    CRITICAL: This env runs in SHADOW mode only.
    It NEVER touches production DB or wallet.
    """
    ...
```

---

### 3E. LearningPipeline (`backend/core/learning_pipeline.py`)

The feedback loop that makes the system learn over time.

```python
class LearningPipeline:
    """
    Triggered after every trade settlement (win or loss).

    Flow:
      Trade outcome
        → TradeForensics.analyze()
        → extract_lessons(forensics_report)
        → brain.remember(namespace="trade_lessons", importance=impact_score)
        → update_genome_fitness(trade)
        → update_knowledge_graph(trade)
        → regime_detector.incorporate_feedback(trade)
        → if pattern_threshold_met: trigger EvolutionHarness cycle

    All BotState writes: respect botstate_mutex.
    All brain writes: include importance score based on trade impact.
    """
```

---

## PHASE 4 — Performance & Observability

### 4A. Signal Latency Instrumentation

Add `@trace_latency` decorator to every strategy's `generate_signal()` method. Emit `signal_latency_seconds` histogram to Prometheus with labels `strategy_name` and `signal_outcome` (executed/blocked/shadow).

**Target:** p99 < 500ms. Document actual baseline in `docs/research/performance-baseline.md`.

### 4B. Brain Memory Observability

Add to Prometheus:

| Metric | Description |
|--------|-------------|
| `cognitive_core_memory_entries_total` | By namespace |
| `cognitive_core_recall_latency_seconds` | Histogram |
| `cognitive_core_health` | 1=healthy, 0=degraded/amnesia |
| `cognitive_core_pending_replay_count` | Memories queued for replay after reconnect |

### 4C. Evolution Observability

Add to Prometheus:

| Metric | Description |
|--------|-------------|
| `genome_population_size` | By status (SHADOW/PAPER/LIVE/GRAVEYARD) |
| `genome_fitness_score` | Histogram |
| `evolution_cycle_duration_seconds` | Histogram |
| `agent_council_message_latency_seconds` | By from_agent/to_agent |

### 4D. Safe Parallelization Audit

Profile the orchestrator. Identify strategies that only READ BotState (never write) — these can safely use `asyncio.gather()`. Write-requiring strategies remain sequential. Document findings in `docs/research/parallelization-audit.md`.

---

## PHASE 5 — Integration Validation

### Test Suite Extensions

```
tests/test_cognitive_core.py              MockCore round-trips, DegradedCore fallback
tests/test_evolution_harness.py           DEAP mutation/crossover, fitness evaluation
tests/test_agent_council.py               Message routing, authority hierarchy
tests/test_learning_pipeline.py           Full feedback loop with mock trades
tests/test_rl_environment.py              Gym env step/reset, reward calculation
tests/integration/test_brain_reconnect.py Amnesia mode → memory replay on reconnect
```

All tests must run with: `SHADOW_MODE=true`, `TRADING_MODE=paper`, `USE_MOCK_BRAIN=true`

### Health Check Extension

Extend `/api/v1/health` to include:

```json
{
  "cognitive_core": {
    "status": "healthy | degraded | amnesia",
    "backend": "1ai-hub",
    "memory_namespaces": {},
    "pending_replay_count": 0,
    "last_successful_write": "ISO8601"
  },
  "agent_council": {
    "active_agents": ["analyst", "critic", "synthesizer", "executor", "historian", "evolver"],
    "message_queue_depth": 0
  },
  "evolution": {
    "backend": "DEAP | RL | Hybrid",
    "population_size": 0,
    "last_cycle": "ISO8601"
  }
}
```

---

## Documentation Requirements (mandatory, no exceptions)

After every phase, update:

| Document | What to update |
|----------|----------------|
| Root `AGENTS.md` | Key Files table — every new file |
| Nearest subdirectory `AGENTS.md` | Same |
| `docs/api.md` | Every new endpoint |
| `IMPLEMENTATION_GAPS.md` | Close addressed gaps, open newly discovered ones |
| `.env.example` | Every new env var with description |
| `ARCHITECTURE.md` | Full rewrite of AGI Intelligence Layer section after Phase 5 |

---

## Progress Logging

After each phase, append a `## Phase N Complete` section to `docs/research/progress-log.md` with:

- What was done
- What decisions were made and why
- What was deferred and why
- Any invariant violations that were considered and rejected

At the end of all phases, produce a final summary at `docs/research/transformation-report.md` covering the full before/after architecture comparison.

---

## Execution Mode

Run all phases **sequentially without pausing for approval**. Do not write production code until Phase 2 ADRs are complete. Begin with Phase 1 research now.
