# ADR-012: Multi-Agent Topology

**Status:** Accepted
**Date:** 2026-05-17

## Context

The AGI orchestrator (`agi_orchestrator.py`) is a monolithic control loop that sequentially executes all AGI stages: market analysis, strategy synthesis, risk critique, trade execution, historical learning, and genome evolution. This design has several problems:

- **No separation of concerns** — a single module handles analysis, synthesis, critique, and execution
- **Sequential bottleneck** — independent stages (forensics and market scanning) cannot run concurrently
- **No authority hierarchy** — all logic is in one place, making it unclear which component has final say on risk decisions
- **Difficult to test** — testing one stage requires mocking all others
- **No typed communication** — stages pass data through shared mutable state

The gap analysis identified CrewAI's role-based agent pattern and AutoGen's typed message protocol as complementary inspirations for a council of specialized agents.

## Decision

Refactor the monolithic `agi_orchestrator.py` into a council of 6 specialized agents communicating via typed messages, coordinated by an `AgentCouncil` orchestrator.

### Agent Roles

| Agent | Responsibility | Authority Level |
|---|---|---|
| `AnalystAgent` | Market regime detection, signal generation, market scanning | Advisory — produces signals, cannot execute |
| `SynthesizerAgent` | Strategy composition, genome ideation, prompt evolution | Advisory — produces strategy proposals |
| `CriticAgent` | Risk critique, validation against ADR-004/005 bounds, coherence checks | Veto — can reject any proposal |
| `ExecutorAgent` | Trade execution, order management, position tracking | Execution — only agent that touches orders |
| `HistorianAgent` | Trade forensics, causal reasoning, lesson extraction, knowledge graph updates | Advisory — produces lessons |
| `EvolverAgent` | Genome evolution, fitness evaluation, population management | Advisory — produces new genomes |

### Authority Hierarchy

```
RiskManager (ADR-004, ADR-005)  ← absolute authority, not an agent
    └─ CriticAgent               ← veto power over proposals
        └─ ExecutorAgent         ← sole execution authority
            └─ All others        ← advisory, no direct execution
```

The `RiskManager` remains the non-bypassable authority (ADR-004). The `CriticAgent` validates proposals against risk bounds before they reach the `ExecutorAgent`. No agent can bypass this hierarchy.

### Message Protocol

`backend/core/agent_council.py` defines:

```
AgentMessage           — typed message with:
    source_agent       — sender identifier
    target_agent       — recipient (or "broadcast")
    message_type       — enum: SIGNAL, PROPOSAL, CRITIQUE, EXECUTION_ORDER, LESSON, EVOLUTION_REQUEST
    payload            — typed data (Pydantic model per message_type)
    correlation_id     — trace a request through the council
    timestamp          — when the message was created
    ttl_seconds        — message expiry

BaseAgent              — abstract base class:
    handle(message)    — process incoming message
    emit(message)      — send message to council bus
    get_role()         — agent identifier
    get_authority()    — authority level enum
```

### Council Orchestration

`AgentCouncil` manages the message bus and execution flow:

1. **Broadcast phase** — `AnalystAgent` and `HistorianAgent` run concurrently, producing market signals and recent lessons
2. **Synthesis phase** — `SynthesizerAgent` receives signals + lessons, produces strategy proposals
3. **Critique phase** — `CriticAgent` validates proposals against risk bounds
4. **Execution phase** — `ExecutorAgent` acts on approved proposals
5. **Evolution phase** — `EvolverAgent` updates genomes based on outcomes

Phases 1 can run in parallel. Phases 2-5 are sequential due to data dependencies. The council enforces timeouts per phase and per agent.

### Migration from Monolith

The existing `agi_orchestrator.py` stages map to agents:

| Current Stage | New Agent |
|---|---|
| `_analyze_market()` | `AnalystAgent` |
| `_synthesize_strategy()` | `SynthesizerAgent` |
| `_critique_proposals()` | `CriticAgent` |
| `_execute_trades()` | `ExecutorAgent` |
| `_run_forensics()` | `HistorianAgent` |
| `_evolve_genomes()` | `EvolverAgent` |

The monolith is preserved as `LegacyOrchestrator` during migration. A feature flag (`AGENT_COUNCIL_ENABLED=false`) controls which orchestrator is active.

## Alternatives Considered

1. **Adopt AutoGen library.** Rejected because AutoGen is in maintenance mode (Microsoft recommends MAF). The patterns are valuable; the library dependency is not.

2. **Adopt CrewAI library.** Rejected because adding a framework for 6 agents is over-engineering. CrewAI's patterns (role-based agents, task delegation) can be implemented in ~200 lines without the framework overhead.

3. **Keep monolith, add parallelism internally.** Rejected because it does not address separation of concerns or authority hierarchy. The monolith would become a more complex monolith.

4. **Event-driven microservices (one process per agent).** Rejected because the current deployment model is single-VPS. Inter-process communication adds latency and complexity without benefit at current scale.

## Consequences

**Positive**
- Clear separation of concerns — each agent has a single responsibility
- Typed messages make data flow explicit and auditable
- Authority hierarchy is enforced structurally, not by convention
- Independent stages can run concurrently (analyst + historian)
- Each agent is independently testable with mock message inputs
- New agents can be added without modifying existing ones

**Negative**
- More code surface area — 6 agent files + council + message types
- Message passing adds latency vs. direct function calls (mitigated by in-process bus, no serialization)
- Debugging requires tracing messages across agents (mitigated by correlation IDs)
- The monolith has implicit knowledge of stage ordering; the council must encode this explicitly

## Rollback Plan

Set `AGENT_COUNCIL_ENABLED=false` to revert to `LegacyOrchestrator`. The agent council is a parallel implementation that shares no state with the legacy orchestrator. All agent files and the council bus can be deleted without affecting production, as the legacy orchestrator remains the default.
