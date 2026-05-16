# ADR-014: Performance Targets

**Status:** Accepted
**Date:** 2026-05-17

## Context

PolyEdge has no formal performance targets for AGI components. The system prioritizes correctness over speed, which is appropriate for a prediction market trading system where latency tolerance is measured in seconds, not microseconds. However, the absence of defined SLOs means:

- **No degradation detection** — a component that takes 10x longer than expected goes unnoticed until users complain
- **No capacity planning** — without latency budgets per component, it is impossible to know when the system is approaching its limits
- **No algorithmic guardrails** — an RL training loop or genome evolution cycle could consume unbounded resources without a defined budget
- **No observability baseline** — Prometheus metrics exist for some components but without targets, dashboards show numbers without context

The AGI transformation adds computationally expensive components (RL training, NSGA-II evolution, multi-agent councils, learning pipeline) that need resource budgets to prevent runaway costs.

## Decision

Define latency SLOs, memory budgets, and cost limits for all AGI components, instrumented via Prometheus metrics.

### Latency SLOs

| Component | p50 | p99 | Measurement Point |
|---|---|---|---|
| Signal generation (analyst) | < 100ms | < 500ms | From market data received to signal emitted |
| Strategy synthesis (synthesizer) | < 2s | < 10s | From signal received to proposal emitted |
| Risk critique (critic) | < 50ms | < 200ms | From proposal received to verdict emitted |
| Trade execution (executor) | < 500ms | < 2s | From approved proposal to order submitted |
| Forensics analysis (historian) | < 5s | < 30s | From trade settled to lesson extracted |
| Genome evolution step (evolver) | < 30s | < 120s | One generation of NSGA-II |
| RL training episode | < 60s | < 300s | One episode of PPO/SAC |
| Brain recall (cognitive core) | < 100ms | < 500ms | From query to results returned |
| Brain remember (cognitive core) | < 50ms | < 200ms | From write request to confirmation |
| Full AGI cycle (council) | < 10s | < 60s | From cycle start to all agents idle |

### Memory Budgets

| Component | Max Memory | Rationale |
|---|---|---|
| Agent Council (all agents) | 512 MB | 6 agents with message buffers |
| RL Environment | 1 GB | Historical data window + model |
| DEAP Population | 256 MB | Genome individuals + fitness cache |
| Knowledge Graph | 512 MB | Entity-relationship store |
| Learning Pipeline | 128 MB | Lesson buffer + write queue |
| Cognitive Core (DegradedCore) | 256 MB | Local SQLite KV + write queue |

### Cost Budgets

| Resource | Daily Limit | Enforced By |
|---|---|---|
| LLM API calls | $10/day | `llm_cost_tracker.py` (existing) |
| RL training compute | 4 GPU-hours/day | Resource scheduler |
| Evolution compute | 2 CPU-hours/day | Resource scheduler |

### Prometheus Metrics

All AGI components export the following metrics:

```
# Latency histograms
agi_signal_latency_seconds{agent="analyst"}
agi_synthesis_latency_seconds{agent="synthesizer"}
agi_critique_latency_seconds{agent="critic"}
agi_execution_latency_seconds{agent="executor"}
agi_forensics_latency_seconds{agent="historian"}
agi_evolution_generation_duration_seconds{agent="evolver"}
agi_rl_episode_duration_seconds
agi_brain_recall_latency_seconds
agi_brain_remember_latency_seconds
agi_council_cycle_duration_seconds

# Resource gauges
agi_memory_usage_bytes{component="council|rl|deap|kg|pipeline|brain"}
agi_population_size{backend="deap|legacy"}
agi_active_genomes_total
agi_brain_status{status="online|amnesia|offline"}

# Counters
agi_messages_total{source, target, type}
agi_lessons_extracted_total
agi_genomes_evolved_total
agi_rl_episodes_total
agi_brain_operations_total{operation="remember|recall|forget", status="success|failure"}
```

### SLO Violation Handling

When a component exceeds its p99 SLO:
1. **Log warning** with component name, actual latency, and SLO threshold
2. **Increment violation counter** for dashboard alerting
3. **No automatic action** — SLOs are observability targets, not circuit breakers
4. **Exception: cost budgets** are hard limits — exceeding them triggers fallback behavior (cached results, reduced population size, paused RL training)

## Alternatives Considered

1. **No SLOs, just raw metrics.** Rejected because metrics without targets provide no actionable signal. A 5-second signal latency is fine for prediction markets but would be alarming if the historical norm is 100ms.

2. **Hard circuit breakers on SLO violation.** Rejected because prediction market trading tolerates occasional latency spikes. A circuit breaker that halts trading on a single p99 violation would be too aggressive. Cost budgets are the exception — those must be hard limits.

3. **Percentile-based auto-scaling.** Rejected because the current deployment is single-VPS with no auto-scaling infrastructure. SLOs inform manual capacity decisions, not automated scaling.

4. **Trace-based observability only (OpenTelemetry).** Considered as complementary. Prometheus metrics provide aggregate dashboards; traces provide per-request debugging. Both are valuable — this ADR focuses on the aggregate targets. OpenTelemetry integration is a future enhancement.

## Consequences

**Positive**
- Measurable quality bar for all AGI components — operators know what "healthy" looks like
- Prometheus metrics enable dashboard alerting on degradation
- Memory budgets prevent any single component from starving others
- Cost budgets prevent runaway LLM/compute expenses
- SLOs inform capacity planning — when p99 approaches the limit, it is time to optimize or scale

**Negative**
- SLO targets may constrain some algorithms — a genome evolution step that takes 130s exceeds the 120s p99, forcing optimization even if correctness is fine
- Metrics instrumentation adds overhead (negligible for histograms, ~1-5 microseconds per observation)
- Memory budgets require enforcement logic — exceeding a budget needs a defined response (OOM kill, graceful degradation, or warning-only)
- SLOs require periodic review as the system evolves — stale targets provide false confidence

## Rollback Plan

Remove Prometheus metric instrumentation and SLO checks from all AGI components. The SLOs are observability-only (except cost budgets) — removing them has zero impact on trading functionality. Cost budget enforcement is handled by the existing `llm_cost_tracker.py` and can be disabled independently.
