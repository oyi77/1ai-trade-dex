# ADR-009: Cognitive Core Interface

**Status:** Accepted
**Date:** 2026-05-17

## Context

PolyEdge's AGI orchestrator requires persistent memory across trading sessions to maintain context about market conditions, strategy performance, and learned lessons. Currently, memory is scattered across multiple systems:

- `knowledge_graph.py` — entity-relationship memory in SQLite
- `genome_registry.py` — genome persistence
- `dynamic_prompt_engine.py` — prompt evolution state
- `trade_forensics.py` — trade analysis results in DecisionLog
- SQLite `DecisionLog` / `TradeAttempt` tables

This fragmentation means no single system can answer "what does the AGI know about this market?" or "what lessons were learned from recent losses?" without querying multiple stores. The `1ai-hub` project is intended to serve as the persistent cognitive brain, but it is not yet integrated.

## Decision

Introduce a `CognitiveCoreAdapter` abstract base class that provides a single integration point between PolyEdge and any cognitive core implementation.

### CognitiveCoreAdapter ABC

`backend/core/cognitive_core.py` defines:

```
CognitiveCoreAdapter   — abstract base class
    remember(namespace, key, value, importance)  — store a memory
    recall(query, namespace, limit, min_relevance) — retrieve memories
    forget(namespace, key)                        — delete a memory
    reason(context, question, personality_mode)   — request reasoning
    route_llm(prompt, task_type, max_cost_usd)    — route LLM calls
    health_check()                                — core health status
    memory_stats()                                — memory store statistics
```

### Implementations

| Implementation | Purpose |
|---|---|
| `OneAIHubCore` | Production adapter connecting to 1ai-hub API. Provides full personality-aware reasoning, cross-session memory, and intelligent LLM routing. |
| `DegradedCore` | Fallback when 1ai-hub is unreachable. Uses local SQLite KV store for memory, direct LLM API calls for reasoning, and a write queue for missed operations replayed on reconnection. Reports `status: "amnesia"` via health endpoint. |
| `MockCore` | In-memory implementation for unit tests. No persistence, no external calls. |

### Integration Points

All existing modules that store or retrieve knowledge will route through the adapter:

| Module | Current Behavior | New Behavior |
|---|---|---|
| `agi_orchestrator.py` | Direct LLM calls via `ai/ensemble.py` | Route through `brain.route_llm()` |
| `knowledge_graph.py` | SQLite entity-relationship store | Delegate to `brain.remember()` / `brain.recall()` |
| `dynamic_prompt_engine.py` | Local prompt evolution | Route through `brain.reason()` |
| `strategy_synthesizer.py` | Direct LLM calls | Use `brain.reason()` for context-aware synthesis |
| `trade_forensics.py` | Local analysis, results in DecisionLog | Store insights via `brain.remember(namespace="trade_lessons")` |
| `ai/ensemble.py` | Multi-provider LLM routing | Replace with `brain.route_llm()` for unified cost tracking |

### Initialization

On startup, the system attempts to connect to 1ai-hub. If the connection succeeds, `OneAIHubCore` is used. If it fails, `DegradedCore` is instantiated and a background reconnect loop retries every 60 seconds. The active implementation is injected via dependency injection into all consuming modules.

## Alternatives Considered

1. **Direct 1ai-hub integration in each module.** Rejected because it couples every module to the hub API and makes graceful degradation impossible without duplicating fallback logic in each module.

2. **Centralized memory service (separate microservice).** Rejected because it adds infrastructure complexity beyond the current single-VPS deployment model. The adapter pattern achieves the same decoupling without an additional service.

3. **Event-sourced memory with replay.** Rejected because the write amplification and complexity are not justified for the current scale. The write queue in DegradedCore provides sufficient durability for hub outages.

### Health and Observability

The adapter exposes health status that feeds into the monitoring system:

```
CoreHealth:
    status          — "online" | "amnesia" | "offline"
    latency_ms      — last round-trip to core
    last_success    — timestamp of last successful operation
    queued_writes   — number of pending write queue items (DegradedCore only)
```

When status is "amnesia", the dashboard displays a warning banner. Operators can query the health endpoint to determine whether hub reconnection is expected or requires manual intervention.

### Write Queue Behavior (DegradedCore)

During hub outages, DegradedCore buffers write operations in a local SQLite table:

| Column | Purpose |
|---|---|
| `operation` | "remember" or "forget" |
| `namespace` | Target namespace |
| `key` | Memory key |
| `value` | Serialized value (JSON) |
| `created_at` | When the operation was queued |
| `replayed_at` | When the operation was replayed (null if pending) |

On reconnection, the queue replays in FIFO order. If the queue exceeds 10,000 entries, oldest entries are dropped with a warning log. This prevents unbounded disk usage during extended outages.

## Consequences

**Positive**
- Single integration point for all cognitive operations — new modules only need the adapter, not hub-specific code
- Graceful degradation: system continues operating with reduced capability when hub is offline
- Write queue ensures no memory loss during brief outages
- Health endpoint gives operators clear visibility into brain status
- MockCore enables fast unit testing without external dependencies
- Modular design allows swapping 1ai-hub for any future cognitive core without touching consuming modules

**Negative**
- Additional abstraction layer adds indirection overhead (negligible for I/O-bound operations)
- DegradedCore lacks personality-aware reasoning — prompts will be generic during amnesia mode
- Write queue replay on reconnection may cause burst writes if outage is prolonged
- The adapter is only as reliable as its least reliable implementation — DegradedCore must be thoroughly tested

## Rollback Plan

Revert to direct 1ai-hub calls by removing the adapter indirection. Each module would call the hub API directly, losing graceful degradation. The `CognitiveCoreAdapter` ABC and all implementations can be deleted without affecting existing functionality, as the adapter is a passthrough wrapper around existing call patterns. No database migrations are required — the adapter is a pure code-level abstraction.
