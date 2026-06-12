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
| `risk/position_sizer.py` | ~100 | Kelly Criterion + dynamic position sizing (quarter-Kelly, confidence discount, liquidity cap) |
| `risk/exposure_limits.py` | ~100 | Pre-trade validation: 8 checks (capital, positions, market, category, daily loss, hours, size) |
| `risk/sanity_checks.py` | ~150 | Market health (quick: 6 checks) + source wallet quality (deep: 6 checks) |
| `position_monitor.py` | ~750 | Stale position detection + sell signal generation (profit-take, stop-loss, time-decay); closes the 948-buy-vs-4-sell gap |
| `market_classifier.py` | ~200 | 25+ market categories (BTC_5m, Politics_US, Geopolitics, Sports, etc.) with word-boundary matching |
| `wallet_analyzer.py` | ~500 | Full wallet analysis: PnL, WR, Sharpe, VaR, category/temporal/size breakdowns, copy-trade rating |
| `wallet_resolver.py` | ~160 | Any input (0x, @username) → WalletInfo (eoa, proxy, username, method) |
| `wallet_scanner.py` | ~300 | Ecosystem-wide profitable trader discovery via Gamma API + Blockscout whale tracking |
| `proxy_finder.py` | ~200 | EOA → Polymarket proxy wallet resolution via Blockscout PUSD MINT events |

## SUBDIRECTORIES

| Directory | Purpose |
|-----------|---------|
| `copy_sources/` | Copy trading signal sources (internal mirror, leaderboard scraper) |
| `execution_pipeline/` | Pluggable trade execution pipeline (validate -> simulate -> execute -> record -> notify) |
| `tests/` | Core-specific unit tests (agent council, learning system, reasoning engine, safety monitor) |

## CRITICAL RULES

### Settlement is Sacred
- **Never block**: Non-critical hooks (analytics, learning) MUST NOT abort settlement transaction
- **Stale positions block orders**: If settlement fails, new orders can't execute
  — `_cleanup_stale_trades_job`'s `stale_paper` branch marks unresolved
  >12h-old paper trades `settled=True, pnl=NULL, result="pending"` while
  awaiting Gamma resolution (up to 5d, see ADR-016). Any "is this position
  open" guard MUST treat `settled=True AND pnl IS NULL` as still-open
  (`or_(Trade.settled.is_(False), Trade.pnl.is_(None))`), not just
  `settled=False` — see `strategy_executor.py`'s cross-strategy duplicate
  guard, `apex_strategy.py::_get_existing_positions`, and
  `apex_strategy.py::_check_exits`.
- **Unresolved outcomes**: Use `closed_unresolved` state if market lags but position provably gone
- **`force_closed_unresolved` (>5d stuck paper trades)**: `pnl` must equal
  `-cost_basis` via `calculate_pnl(trade, total_loss_settlement_value(trade.direction))`
  — never hardcode `pnl=0.0` for a `result="loss"` trade (ADR-016)
- **`early_exit_*` (APEX profit-target/stop-loss/time-decay)**: a *partial*
  realization at a continuous price, computed via
  `calculate_exit_pnl(trade, exit_price)` — NOT `calculate_pnl` (which is
  binary-settlement-only). See `apex_strategy.py::_close_position` and
  ADR-017. `paper_pnl_audit.py` skips recompute for these (different pnl
  model than binary settlement).
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
