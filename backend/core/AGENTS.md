# CORE EXECUTION KERNEL
<!-- Parent: ../AGENTS.md -->

**Module**: `backend/core/` — Execution engine, bounded autonomy, settlement integrity

## PURPOSE

Kernel coordination of strategy execution, scheduling, settlement reconciliation, and risk management. 5.8K LOC.

## KEY MODULES

| File | LOC | Purpose |
|------|-----|---------|
| `strategy_executor.py` | 1529 | Execute strategies with bounded AGI autonomy; per-tier allocation limits |
| `scheduler.py` | 1375 | Cron + event-driven task coordination; 15min health checks |
| `settlement_helpers.py` | 1344 | 2-phase settlement: prepare → commit (CRITICAL) |
| `bankroll_reconciliation.py` | 798 | Reconcile live exposure vs. DB state |
| `wallet_reconciliation.py` | 780 | Wallet sync, position accuracy |
| `autonomous_promoter.py` | 769 | Genome promotion, fitness-based strategy selection |
| `agi_orchestrator.py` | 743 | AGI meta-strategy orchestration |
| `scheduling_strategies.py` | 1228 | Cron patterns, scheduling logic |
| `risk_profiles.py` | ~200 | 6 risk tiers (safe→crazy); RISK_TIER_MAX_ALLOCATION |
| `cognitive_core.py` | ~580 | CognitiveCoreAdapter ABC — single interface to 1ai-hub brain (OneAIHubCore, DegradedCore, MockCore); recall/remember/health_check |
| `agent_council.py` | ~500 | Multi-agent council (ADR-012): 6 typed agents (Analyst, Synthesizer, Critic, Executor, Historian, Evolver), MessageBus routing, AuthorityHierarchy |
| `evolution_harness.py` | ~680 | Pluggable evolution engine (ADR-010): DEAPEvolutionBackend (NSGA-II) and LegacyBackend; PopulationStats, Pareto front |
| `learning_pipeline.py` | ~500 | Post-settlement feedback loop (ADR-013): forensics → lesson extraction → brain storage → genome fitness → KG update; PipelineMetrics |
| `correlation_monitor.py` | ~160 | Cross-market correlation monitor: classifies markets into 5 categories, blocks clustered exposure exceeding MAX_CORRELATED_EXPOSURE_PCT |
| `position_monitor.py` | ~750 | Stale position detection + sell signal generation (profit-take, stop-loss, time-decay); closes the 948-buy-vs-4-sell gap |

## CRITICAL RULES

### Settlement is Sacred
- **Never block**: Non-critical hooks (analytics, learning) MUST NOT abort settlement transaction
- **Stale positions block orders**: If settlement fails, new orders can't execute
- **Unresolved outcomes**: Use `closed_unresolved` state if market lags but position provably gone
- **Two-phase protocol**: Prepare validates, commit persists (no partial failures)

### Error Handling
- NEVER bare `except Exception: pass`
- Always `logger.exception("context")` with trade_id, strategy_id
- Use structured logging (JSON format)

### Bounded Autonomy
- Respect RISK_TIER_MAX_ALLOCATION per risk profile
- Circuit breakers: position limits, concentration guards
- AGI health checks every 15min (AGI_HEALTH_CHECK_ENABLED)

### Strategy Governance
- Auto-kill at <30% win rate (from settled ShadowTrades)
- Disabled state in StrategyConfig DB table, NOT code
- NEVER manually re-enable killed strategies

## ANTI-PATTERNS

- ❌ Blocking settlement (cascades order failures)
- ❌ Silent error swallowing
- ❌ Manual strategy re-enable
- ❌ Sync blocking waits in health checks

## TESTS

```bash
pytest backend/tests/test_strategy_executor.py -v
pytest backend/tests/test_settlement_*.py -v
```
