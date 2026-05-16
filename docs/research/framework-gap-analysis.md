# Framework Gap Analysis — PolyEdge AGI Transformation

**Date:** 2026-05-17
**Phase:** 1 — Research & Gap Analysis
**Status:** Complete

---

## Executive Summary

PolyEdge is a mature prediction market trading system with 14 strategies, an AGI intelligence layer (regime detection, knowledge graph, strategy composition, genome evolution), and a full-stack React dashboard. The system already implements significant autonomous capabilities: strategy synthesis via LLM, shadow/paper/live promotion pipelines, genome-based evolution with mutation/crossover, regime-aware capital allocation, and causal reasoning for trade forensics.

The primary gaps for AGI transformation fall into three categories: (1) **cognitive persistence** — the system lacks a unified long-term memory brain (1ai-hub integration is not implemented), with memory scattered across SQLite knowledge graphs, genome registries, and decision logs; (2) **evolution sophistication** — the current genome system uses basic random mutation/crossover without DEAP/PyGAD-style selection pressure, tournament selection, or multi-objective optimization; (3) **multi-agent coordination** — the `agi_orchestrator.py` is a monolithic control loop rather than a council of specialized agents with typed communication and authority hierarchies.

Reference repos (Hummingbot, Freqtrade, FinRL, AutoGen, CrewAI) offer proven patterns for connector abstraction, strategy optimization, RL environments, and multi-agent orchestration that can be adopted incrementally without breaking existing invariants. The recommended approach is evolutionary, not revolutionary: layer new abstractions (CognitiveCoreAdapter, EvolutionBackend, AgentCouncil) behind ABC interfaces with degraded/fallback modes, preserving all existing risk gates and safety boundaries.

---

## Section 1: Pattern Adoption Matrix

### Hummingbot

| Pattern | Description | Relevance to PolyEdge | Adoption Complexity |
|---------|-------------|----------------------|-------------------|
| **Connector Abstraction** | Standardized REST/WebSocket interfaces per exchange (CEX/DEX). Connectors implement a common `ConnectorBase` with unified order/trade/balance methods. | **High.** PolyEdge has `polymarket_clob.py`, `kalshi_client.py`, `crypto.py` as separate, non-uniform clients. A `MarketConnector` ABC would unify the interface and make adding new markets (e.g., Kalshi futures, Polymarket CTF) a plug-in operation. | 3/5 — Requires wrapping existing clients behind a common interface without breaking current call sites. |
| **Strategy Template Pattern** | Strategies inherit from a base class with lifecycle hooks (`on_tick`, `on_order_filled`, `on_trade`). The framework manages state, not the strategy. | **High.** PolyEdge's `BaseStrategy` + `StrategyContext` already follows this pattern but lacks standardized lifecycle hooks for order fills, cancellations, and position changes. | 2/5 — Extend existing `BaseStrategy` with additional hooks. |
| **Event-Driven Architecture** | Internal event bus propagates market data, order updates, and trade events. Strategies subscribe to events rather than polling. | **Medium.** PolyEdge has `backend/core/event_bus.py` but it is fire-and-forget with no guaranteed delivery. Hummingbot's typed event system with subscriber patterns is more robust. | 3/5 — Upgrade existing EventBus to typed events with subscriber management. |
| **Gateway Middleware** | Separate Gateway process for DEX/blockchain interaction, isolating chain-specific logic from core bot. | **Low.** PolyEdge targets prediction markets (Polymarket CLOB, Kalshi REST), not general DEX trading. The Gateway pattern is not directly applicable but the isolation principle (data layer separation) is relevant. | 1/5 — Conceptual adoption only; data clients are already separate modules. |

### Freqtrade

| Pattern | Description | Relevance to PolyEdge | Adoption Complexity |
|---------|-------------|----------------------|-------------------|
| **FreqAI Adaptive Learning** | Self-training ML models that adapt to market conditions. Supports multiple model types (LightGBM, XGBoost, neural nets) with automatic retraining on drift detection. | **High.** PolyEdge has `ai/bayesian_optimizer.py` and `ai/ensemble.py` but lacks adaptive retraining on market drift. FreqAI's pattern of monitoring model performance and triggering retraining when Brier score degrades is directly applicable. | 4/5 — Requires building a model registry, drift detection pipeline, and retraining scheduler. |
| **Hyperopt Optimization** | Bayesian hyperparameter optimization for strategy parameters using Optuna. Supports custom loss functions (Sharpe, profit, drawdown). | **High.** PolyEdge's genome system does basic mutation/crossover but lacks structured hyperparameter optimization. Freqtrade's Hyperopt pattern with Optuna integration would complement the existing genome evolution. | 3/5 — Integrate Optuna as an alternative optimization backend behind the `EvolutionBackend` ABC. |
| **Pairlist/Whitelist System** | Dynamic market selection based on volume, volatility, spread, and custom filters. Markets are scored and ranked before strategy execution. | **Medium.** PolyEdge's `market_scanner.py` fetches markets but lacks a scoring/ranking pipeline. A pairlist-style system would improve market selection quality. | 2/5 — Add scoring filters to existing market scanner. |
| **Strategy Protection** | Strategies cannot modify core bot state directly. All state mutations go through the framework's trade manager. | **High (already done).** PolyEdge enforces this via RiskManager gates (ADR-004, ADR-005). No adoption needed — the invariant already exists. | 0/5 — Already implemented. |

### FinRL

| Pattern | Description | Relevance to PolyEdge | Adoption Complexity |
|---------|-------------|----------------------|-------------------|
| **Gym-Compatible Market Environment** | `gymnasium.Env` wrapper for financial markets with state/action/reward spaces. Supports multi-agent training and custom reward shaping. | **High.** PolyEdge has no RL environment. The `PredictionMarketEnv` described in poly-improvement.md Phase 3D would wrap the existing backtester into a Gym-compatible interface for RL-based strategy parameter optimization. | 4/5 — Requires building state/action space definitions, reward functions, and integration with existing backtester. |
| **Three-Layer Architecture** | Market Environments (data) -> DRL Agents (learning) -> Applications (execution). Clean separation prevents coupling between learning and trading. | **Medium.** PolyEdge's architecture is already layered (Data -> Strategies -> Orchestrator) but the learning/evolution layer is interleaved with execution. Separating `EvolutionBackend` from `strategy_executor` would improve this. | 3/5 — Refactor evolution_jobs.py to decouple learning from execution scheduling. |
| **Multi-Agent RL (MARL)** | Multiple RL agents trading simultaneously with shared or independent reward signals. Supports cooperative and competitive dynamics. | **Low.** PolyEdge's strategies are independent, not cooperative. MARL is not directly applicable but the concept of independent reward signals per strategy genome is relevant for fitness evaluation. | 2/5 — Conceptual adoption for genome fitness isolation. |

### AutoGen (Microsoft)

| Pattern | Description | Relevance to PolyEdge | Adoption Complexity |
|---------|-------------|----------------------|-------------------|
| **Conversational Agent Protocol** | Agents communicate via typed messages in a conversation graph. Each agent has a role, tools, and a termination condition. | **High.** PolyEdge's `agi_orchestrator.py` is a monolithic loop. AutoGen's conversational pattern would enable the Agent Council design from poly-improvement.md Phase 3C — analyst, synthesizer, critic, executor, historian, evolver as separate agents with typed message passing. | 4/5 — Requires building message bus, agent registry, and conversation management. |
| **Tool Use Pattern** | Agents call external tools (code execution, web search, APIs) through a standardized tool interface. Tools are registered per-agent. | **Medium.** PolyEdge's strategies already call external data sources and LLMs directly. A tool abstraction would standardize how agents access market data, LLMs, and execution. | 3/5 — Wrap existing data clients and LLM providers as registered tools. |
| **Human-in-the-Loop** | Agents can pause and request human approval before proceeding. Supports escalation and override. | **High (partially done).** PolyEdge has manual promotion gates (ADR-006) but lacks a general human-in-the-loop protocol for agent decisions. The AutoGen pattern would generalize the existing promotion gate. | 2/5 — Extend existing promotion gate to support general agent escalation. |

**Note:** AutoGen is now in maintenance mode; Microsoft recommends migrating to Microsoft Agent Framework (MAF). For PolyEdge, adopt AutoGen's *patterns* (conversational agents, typed messages) without depending on the library itself.

### CrewAI

| Pattern | Description | Relevance to PolyEdge | Adoption Complexity |
|---------|-------------|----------------------|-------------------|
| **Crew Orchestration** | Agents are organized into Crews with defined roles, goals, and backstories. A Manager agent delegates tasks to crew members. | **High.** Directly maps to the Agent Council design. CrewAI's Crew pattern with role-based delegation is the closest match to PolyEdge's target architecture. | 3/5 — Build a lightweight Crew abstraction on top of the existing orchestrator. |
| **Task Delegation** | Tasks have expected outputs, context dependencies, and can be delegated to specific agents based on role matching. | **High.** PolyEdge's AGI orchestrator currently runs all stages sequentially. Task delegation would enable parallel execution of independent stages (e.g., forensics and market scanning can run concurrently). | 3/5 — Define task types and agent-role matching. |
| **Memory Systems** | Short-term (conversation), long-term (persistent storage), and entity memory for agents. | **High.** PolyEdge's knowledge graph serves as partial long-term memory but lacks the structured short-term/entity memory patterns CrewAI provides. This ties directly to the CognitiveCoreAdapter design. | 3/5 — Implement memory tiers behind the CognitiveCoreAdapter ABC. |
| **Flows (Event-Driven)** | Enterprise pattern for event-driven multi-agent workflows with granular control and single LLM calls per step. | **Medium.** CrewAI Flows would complement the Crew pattern for production-grade orchestration where deterministic control flow matters (e.g., risk validation must be sequential, not autonomous). | 3/5 — Adopt Flows pattern for safety-critical paths (risk, settlement). |

---

## Section 2: 1ai-hub Integration Analysis

### Current State

The 1ai-hub repository (`github.com/oyi77/1ai-hub`) is described in `poly-improvement.md` as the "persistent cognitive core" — the long-term memory, personality, and reasoning identity of the system. However:

- **The repository does not exist publicly** (GitHub API returned no matching repo; the URL appears to reference a private or planned repository).
- **No integration code exists** in PolyEdge — no `cognitive_core.py`, no `CognitiveCoreAdapter` ABC, no hub client.
- **Memory is currently distributed** across: `knowledge_graph.py` (entity-relationship memory), `genome_registry.py` (genome persistence), `dynamic_prompt_engine.py` (prompt evolution), `trade_forensics.py` (trade analysis memory), and SQLite `DecisionLog`/`TradeAttempt` tables.

### Interfaces Needed

Per the `poly-improvement.md` Phase 3A specification, the following interfaces are required:

#### CognitiveCoreAdapter ABC

```python
class CognitiveCoreAdapter(ABC):
    """Single interface between PolyEdge and the cognitive brain."""

    # Memory operations
    async def remember(namespace: str, key: str, value: dict, importance: float = 0.5) -> None
    async def recall(query: str, namespace: str | None = None, limit: int = 10, min_relevance: float = 0.7) -> list[Memory]
    async def forget(namespace: str, key: str) -> None

    # Reasoning operations
    async def reason(context: CognitiveContext, question: str, personality_mode: str = "default") -> Reasoning
    async def route_llm(prompt: str, task_type: LLMTaskType, max_cost_usd: float = 0.10) -> LLMResponse

    # Introspection
    async def health_check() -> CoreHealth
    async def memory_stats() -> MemoryStats
```

#### DegradedCore (Amnesia Mode)

When 1ai-hub is unreachable, the system must degrade gracefully:

- **Local SQLite KV store** for memory operations (no personality, no cross-session learning)
- **Basic LLM routing** via direct Anthropic/Groq API calls (bypassing hub's routing intelligence)
- **Write queue** for missed memory operations, replayed when brain reconnects
- **No crash** — all hub calls are wrapped in try/except with fallback to DegradedCore
- **Health endpoint** reports `status: "amnesia"` so operators know the brain is offline

#### Integration Points

The CognitiveCoreAdapter must be wired into:

| Module | Current State | Integration Required |
|--------|--------------|---------------------|
| `agi_orchestrator.py` | Direct LLM calls via `ai/ensemble.py` | Route through `brain.route_llm()` |
| `knowledge_graph.py` | SQLite-backed entity-relationship store | Delegate persistence to `brain.remember()`/`brain.recall()` |
| `dynamic_prompt_engine.py` | Local prompt evolution | Route through `brain.reason()` for personality-aware prompt generation |
| `strategy_synthesizer.py` | Direct LLM calls for strategy ideation | Use `brain.reason()` for context-aware synthesis |
| `trade_forensics.py` | Local analysis, results in DecisionLog | Store insights via `brain.remember(namespace="trade_lessons")` |
| `ai/ensemble.py` | Multi-provider LLM routing | Replace with `brain.route_llm()` for unified cost tracking |

---

## Section 3: Technology Recommendations

### Evolutionary/Genetic: DEAP vs PyGAD vs Current Genome System

| Criterion | DEAP | PyGAD | Current Genome System |
|-----------|------|-------|----------------------|
| **Maturity** | 10+ years, widely used in research | 5+ years, simpler API | Custom implementation, 2 months old |
| **Selection Algorithms** | Tournament, roulette, NSGA-II (multi-objective) | Tournament, roulette, rank | None — random selection |
| **Crossover Operators** | One-point, two-point, uniform, custom | One-point, two-point, uniform | Basic single-point only |
| **Mutation Operators** | Gaussian, shuffle, flip, custom | Random, adaptive | Random parameter perturbation only |
| **Multi-Objective** | NSGA-II, SPEA2 built-in | Not supported | Not supported |
| **Parallelism** | Built-in multiprocessing/distributed | Built-in | Sequential only |
| **Integration Effort** | Medium — wrap existing genome as DEAP Individual | Low — simpler API, closer to current code | N/A — already integrated |
| **Community** | Large academic community | Growing, simpler docs | N/A |

**Recommendation: DEAP**

Rationale:
- NSGA-II multi-objective optimization is critical for trading (optimize Sharpe AND minimize drawdown simultaneously, not just a single fitness score)
- Tournament selection with configurable pressure enables better population diversity than current random selection
- DEAP's `creator` and `toolbox` patterns map cleanly to the existing `StrategyGenome` dataclass
- The `EvolutionBackend` ABC from poly-improvement.md Phase 3B can wrap DEAP behind the interface, allowing PyGAD as a simpler alternative if needed

**Integration path:** Create `backend/core/evolution_backends/deap_backend.py` implementing `EvolutionBackend`. Map existing genome chromosomes to DEAP individuals. Preserve `evolution_jobs.py` as the scheduler entry point — it calls through the backend.

### Reinforcement Learning: Ray RLlib vs Stable-Baselines3

| Criterion | Ray RLlib | Stable-Baselines3 |
|-----------|-----------|-------------------|
| **Scale** | Distributed, multi-GPU, multi-node | Single-process, single-GPU |
| **Algorithm Coverage** | PPO, SAC, A2C, DDPG, TD3, IMPALA, MARL | PPO, SAC, A2C, DDPG, TD3 |
| **Custom Environments** | Full Gymnasium support | Full Gymnasium support |
| **Production Readiness** | Built for production serving | Research/education focused |
| **Complexity** | High — Ray cluster setup, resource management | Low — pip install and go |
| **Trading Relevance** | Used by FinRL-X for production trading | Used by original FinRL for research |
| **Memory/Overhead** | High — Ray runtime overhead | Low — lightweight |

**Recommendation: Stable-Baselines3 (initial), Ray RLlib (long-term)**

Rationale:
- PolyEdge's RL use case is strategy parameter optimization, not high-frequency execution. SB3's simplicity is sufficient for training genome parameters against historical data.
- The `PredictionMarketEnv` (Phase 3D) is a standard Gymnasium environment — SB3 works directly with it.
- Ray RLlib becomes valuable when scaling to distributed training across multiple strategy genomes simultaneously, which is a Phase 4+ concern.
- FinRL's own progression (SB3 for research -> Ray for production) validates this staged approach.

**Integration path:** Create `backend/core/rl_environment.py` as a `gymnasium.Env`. Use SB3's PPO/SAC for initial parameter optimization. Wrap in `RLEvolution(EvolutionBackend)` for the evolution harness.

### Multi-Agent: AutoGen vs CrewAI vs Current AGIOrchestrator

| Criterion | AutoGen | CrewAI | Current AGIOrchestrator |
|-----------|---------|--------|------------------------|
| **Status** | Maintenance mode (succeeded by MAF) | Active development, 100k+ developers | Custom, 2 months old |
| **Agent Model** | Conversational agents with tool use | Role-based crews with delegation | Monolithic sequential loop |
| **Communication** | Typed messages in conversation graph | Task delegation with context | Direct function calls |
| **Memory** | External (requires custom integration) | Built-in short/long/entity memory | Knowledge graph (partial) |
| **Human-in-Loop** | Supported via termination conditions | Supported via delegation gates | Manual promotion gate only |
| **Overhead** | Medium — conversation management | Low — lean framework | None — direct calls |
| **Trading Fit** | General-purpose, not trading-specific | General-purpose, not trading-specific | Purpose-built for PolyEdge |

**Recommendation: Custom Agent Council (inspired by CrewAI patterns)**

Rationale:
- Neither AutoGen nor CrewAI is designed for trading-specific requirements (risk authority hierarchies, settlement integration, genome evolution)
- AutoGen is in maintenance mode — adopting it creates migration debt to MAF
- CrewAI's patterns (role-based agents, task delegation, memory tiers) are excellent but adding a framework dependency for 6 agents is over-engineering
- The current `agi_orchestrator.py` already has the domain logic — refactoring it into a council of agents with typed messages preserves the domain knowledge while gaining modularity

**Integration path:** Create `backend/core/agent_council.py` with `BaseAgent` ABC, `AgentMessage` typed model, and `AgentCouncil` orchestrator. Refactor existing `agi_orchestrator.py` stages into agent handlers (analyst, synthesizer, critic, executor, historian, evolver). Preserve authority hierarchy: RiskManager > executor > critic > others.

---

## Section 4: Gap Map

### What PolyEdge Already Has

| Capability | Implementation | Quality |
|-----------|---------------|---------|
| Strategy execution pipeline | `strategy_executor.py` + `BaseStrategy` | Production-grade |
| Risk management | `risk_manager.py` + `circuit_breaker.py` (ADR-004, ADR-005) | Non-bypassable, well-tested |
| Market regime detection | `regime_detector.py` (bull/bear/sideways/volatile + hysteresis) | Functional |
| Knowledge graph | `knowledge_graph.py` (entity-relationship memory) | Write-heavy, read-light |
| Strategy composition | `strategy_composer.py` (block-based, 5 building blocks) | Functional |
| Genome evolution | `genome_compiler.py` + `evolution_jobs.py` (mutation/crossover/fitness) | Basic — lacks selection pressure |
| Promotion pipeline | `autonomous_promoter.py` + `agi_promotion_pipeline.py` | Production-grade |
| LLM ensemble | `ai/ensemble.py` (Claude, Groq, custom providers) | Functional |
| Self-debugging | `self_debugger.py` (API failure diagnosis) | Functional |
| Causal reasoning | `causal_reasoning.py` (trade outcome analysis) | Basic |
| Trade forensics | `trade_forensics.py` (losing trade analysis) | Functional |
| LLM cost tracking | `llm_cost_tracker.py` ($10/day cap) | Production-grade |
| Multi-wallet routing | `TradingWallet` + `WalletAllocation` (ADR-007) | Production-grade |
| Copy trading | `CopySource` ABC + `CopyPolicy` (ADR-008) | Functional |
| Dashboard | React 18 + AGI control panel, regime display, decision audit | Production-grade |

### What's Missing for AGI Transformation

| Gap | Priority | Source Pattern | Effort | Dependencies |
|-----|----------|---------------|--------|-------------|
| **CognitiveCoreAdapter ABC** | P0 | poly-improvement.md Phase 3A | High | 1ai-hub availability (or DegradedCore) |
| **DegradedCore (amnesia mode)** | P0 | poly-improvement.md Phase 3A | Medium | CognitiveCoreAdapter ABC |
| **EvolutionBackend ABC with DEAP** | P1 | Freqtrade Hyperopt, poly-improvement.md Phase 3B | Medium | Existing genome system |
| **NSGA-II multi-objective optimization** | P1 | DEAP library | Medium | EvolutionBackend ABC |
| **Gym-compatible RL environment** | P1 | FinRL, poly-improvement.md Phase 3D | High | Backtester, market data |
| **Agent Council architecture** | P1 | CrewAI patterns, poly-improvement.md Phase 3C | High | CognitiveCoreAdapter |
| **Typed agent message bus** | P1 | AutoGen patterns | Medium | Agent Council |
| **Connector abstraction (MarketConnector ABC)** | P2 | Hummingbot | Medium | Existing data clients |
| **Adaptive model retraining** | P2 | Freqtrade FreqAI | High | LLM ensemble, calibration |
| **Structured hyperparameter optimization (Optuna)** | P2 | Freqtrade Hyperopt | Medium | EvolutionBackend |
| **Learning pipeline (trade outcome -> brain memory)** | P1 | poly-improvement.md Phase 3E | Medium | CognitiveCoreAdapter |
| **Signal latency instrumentation** | P2 | poly-improvement.md Phase 4A | Low | Prometheus |
| **Evolution observability (Prometheus)** | P2 | poly-improvement.md Phase 4C | Low | Prometheus |
| **Brain memory observability** | P2 | poly-improvement.md Phase 4B | Low | CognitiveCoreAdapter |
| **Dynamic market scoring/ranking** | P2 | Freqtrade Pairlist | Low | Market scanner |

### Priority Ordering

**P0 — Foundation (must complete before any other AGI work):**
1. CognitiveCoreAdapter ABC + DegradedCore — all other AGI modules route through this
2. Wire CognitiveCoreAdapter into existing modules (orchestrator, KG, prompt engine, synthesizer, forensics)

**P1 — Core AGI Capabilities:**
3. EvolutionBackend ABC + DEAP integration — upgrade genome evolution with proper selection pressure
4. Gym-compatible RL environment — enable RL-based parameter optimization
5. Agent Council architecture — decompose monolithic orchestrator into specialized agents
6. Learning pipeline — close the feedback loop from trade outcomes to brain memory

**P2 — Optimization & Observability:**
7. Connector abstraction — unify market data interfaces
8. Adaptive model retraining — FreqAI-style drift detection
9. Structured hyperparameter optimization — Optuna integration
10. Observability instrumentation — Prometheus metrics for brain, evolution, agents

---

## Risk Register

| Risk | Affected Module | Severity | Mitigation |
|------|----------------|----------|-----------|
| 1ai-hub unavailable or delayed | All AGI modules | Critical | DegradedCore provides full functionality without hub; hub integration is opt-in enhancement |
| DEAP integration breaks existing genome evolution | `evolution_jobs.py`, `genome_compiler.py` | High | EvolutionBackend ABC preserves existing code as fallback; feature-flag DEAP backend |
| RL environment produces overfitted strategies | `rl_environment.py`, genome system | High | RL runs in SHADOW mode only (ADR-006); statistical promotion gates still apply |
| Agent Council increases latency vs monolithic loop | `agent_council.py`, `agi_orchestrator.py` | Medium | Profile before/after; keep risk-critical paths (validation, settlement) sequential |
| CognitiveCoreAdapter becomes single point of failure | All AGI modules | High | DegradedCore fallback; health monitoring; circuit breaker on hub calls |
| Multi-agent message bus introduces race conditions | `agent_council.py` | Medium | Typed messages with timeouts; no shared mutable state between agents |

---

## Migration Sequence

Ordered to minimize breakage and enable incremental validation:

1. **Create `docs/research/` directory and this document** — done
2. **CognitiveCoreAdapter ABC + MockCore** — no production impact, enables testing
3. **DegradedCore implementation** — local SQLite fallback, validates graceful degradation
4. **Wire CognitiveCoreAdapter into `knowledge_graph.py`** — lowest-risk integration point
5. **Wire into `trade_forensics.py`** — one-way memory writes, easy to validate
6. **Wire into `agi_orchestrator.py`** — replace direct LLM calls with `brain.route_llm()`
7. **Wire into `strategy_synthesizer.py`** — use brain for context-aware synthesis
8. **Wire into `dynamic_prompt_engine.py`** — personality-aware prompt generation
9. **EvolutionBackend ABC + DEAP backend** — parallel to existing genome system, feature-flagged
10. **Gym-compatible RL environment** — standalone module, no production impact until integrated
11. **Agent Council refactor** — decompose `agi_orchestrator.py` into agent handlers
12. **Learning pipeline** — close feedback loop, depends on CognitiveCoreAdapter
13. **Observability instrumentation** — Prometheus metrics for all new modules
14. **Connector abstraction** — unify market data clients (lowest priority, highest disruption)

Each step should be validated with tests before proceeding to the next. All existing invariants (ADR-001 through ADR-008) must be preserved at every step.
