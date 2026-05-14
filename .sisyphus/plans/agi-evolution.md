# AGI Evolution Plan — True Full AGI (Phases 1–6)

## TL;DR

> **Quick Summary**: 6-phase AGI roadmap for PolyEdge prediction market bot, building atop the completed plugin-system refactor (PR #95). Generalize core reasoning, add cross-domain learning, autonomous strategy generation, recursive self-modification, unbounded autonomy, and AGI benchmarking. All work on `feature/plugin-system-refactoring` branch.
>
> **Deliverables**:
> - `backend/core/safety.py` (Phase 1 safety monitor)
> - `backend/core/learning_system.py` (Phase 2 continuous learning)
> - `backend/core/transfer_learning.py` (Phase 2 transfer learner)
> - `backend/ai/architecture_search.py` (Phase 4 NAS)
> - `backend/evals/` suite (Phase 6 benchmarks)
> - Reasoning engine generalization, knowledge graph expansion, goal system, values, planner
> - Sandbox hardening, code validator, hypothesis tester
> - Recursive modification engine, causal reasoning
>
> **Estimated Effort**: XL (12–18 months, ~400 tasks)
> **Parallel Execution**: YES — 6-phase waves with intra-wave parallelism
> **Critical Path**: Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5 → Phase 6

---

## Context

### Original Request
User requested a full, file-anchored work plan (`.sisyphus/plans/agi-evolution.md`) implementing the "True Full AGI" 6-phase evolution on the PolyEdge prediction market trading bot. The plan must:
- Cover all 6 phases as described in the user-provided roadmap
- Be grounded in the actual codebase state (not theoretical)
- Be a single comprehensive plan file
- Commit to existing branch `feature/plugin-system-refactoring` (same PR #95)

### Interview Summary
- Phase 1 foundation (plugin system refactoring) is already complete — this plan builds on that base
- Existing AGI components from exploration: reasoning_engine, orchestrator, strategy_synthesizer, genome pipeline, agi/ folder with self-improvement, sandbox, modification engine
- Missing components identified: safety, transfer learning, evals, goal/values/planner, NAS architecture search, causal reasoning
- Must respect `docs/architecture/adr-006-agi-autonomy-framework.md` safety boundaries
- No breaking changes to trading logic; existing 169+ tests must remain green

### Configuration Decisions (user-confirmed)
- **Safety thresholds**: Configurable via env vars (`SAFETY_MIN_WIN_RATE`, `SAFETY_MIN_SHARPE`, `SAFETY_MAX_DRAWDOWN`) with defaults: win_rate ≥0.30, Sharpe ≥1.0, drawdown ≤‑0.10. Implemented in Phase 1 Task 1; Phase 1 Task 5 integration test verifies configurability.
- **Benchmark cadence**: Nightly runs at 03:00 UTC via APScheduler (Phase 6 Task 69). Configurable via `BENCHMARK_SCHEDULE_CRON` env var.
- **NAS compute budget**: Configurable via `NAS_MAX_GPU_HOURS_PER_MONTH` env var (default 10 GPU-hr/month). Phase 4 Task 55 reads budget, throttles search candidates accordingly.
- **Accuracy mode**: **High Accuracy** — full Momus review loop required before any task execution; plan will not proceed to `/start-work` until Momus returns OKAY.

### Research Findings (Explore Agents)

#### EXISTS_FULL (real, functional, ship it)
- `backend/core/reasoning_engine.py` — Reasoning engine implementation exists
- `backend/core/orchestrator.py` + `backend/core/agi_orchestrator.py` — Multi-domain routing exists
- `backend/core/strategy_synthesizer.py` — LLM strategy generation + 4-gate validation functional
- `backend/core/auto_improve.py` — Per-strategy rollback dict stored in BotState.misc_data
- `backend/core/forensics_integration.py` — Forensics → improvement pipeline generates real proposals
- `backend/application/strategy/genome_compiler.py` — Dynamic runtime class generation from StrategyGenome
- `backend/application/strategy/genome_strategy.py` — Chromosome-mapped entry/exit/risk logic (CognitionChromosome, RiskChromosome, EntryLogic, EntryCondition)
- `backend/models/genome_registry.py` — ORM models GenomePerformance, GenomeShadowTrade, stage tracking (DRAFT→LIVE)
- `backend/repositories/genome_repository.py` — Repository layer used by evolution_jobs
- `backend/data/market_universe.py` — MarketUniverseScanner with TTL cache
- `backend/application/agi/evolution_jobs.py` — Real mutation/crossover jobs, shadow-validation fitness feedback
- `backend/application/agi/lifecycle_manager.py` — Stage transitions DRAFT→SHADOW→PAPER→LIVE→RETIRED
- `backend/application/agi/performance_attributor.py` — Trade P&L attribution to chromosomes
- `backend/application/agi/regime_population_manager.py` — Population diversity maintenance
- `backend/application/agi/forensics_feedback.py` — Forensics integration for failed strategies
- `backend/agi/` directory — codebase_intelligence.py, extended_sandbox.py, modification_engine.py, rollback_manager.py, self_healing.py, self_improvement_loop.py, nodes/

#### EXISTS_STUB (skeleton — needs real implementation)
- `backend/application/agi/necromancer.py` — load_graveyard/load_legends return `[]` (placeholder)
- `backend/core/agi_jobs.py` — `model_calibration_check_job` is stub/skip logic only
- `backend/core/causal_reasoning.py` — Test file exists, no implementation

#### MISSING (not built)
- `backend/core/safety.py` — Central safety monitor with bounded autonomy gates
- `backend/core/learning_system.py` — Continuous learning orchestration (auto_improve is partial)
- `backend/core/transfer_learning.py` — Cross-domain knowledge transfer
- `backend/ai/architecture_search.py` — Neural Architecture Search (NAS) for strategy networks
- `backend/evals/` directory — Benchmarking suite, transfer tests, few-shot evaluation
- Goal formation — AutonomousGoalGenerator missing
- Values alignment — CoreValues system missing
- Long-range planning — LongTermPlanner missing
- Opportunity discovery — OpportunityFinder missing
- Multi-objective optimization — MultiObjectiveOptimizer missing
- `backend/core/causal_reasoning.py` — No implementation (tests exist!)

---

## Work Objectives

### Core Objective
Evolve PolyEdge from a bounded multi-strategy trading bot into a **True Full AGI** system through 6 disciplined phases while preserving all existing trading safety and correctness guarantees.

### Concrete Deliverables (by Phase)
- **Phase 1** — ReasoningEngine generalization, generalized KnowledgeGraph, SafetyMonitor creation, PluginManager completion
- **Phase 2** — ContinuousLearningSystem orchestration, TransferLearner, MultiDomainOrchestrator wiring
- **Phase 3** — StrategyCodeGenerator augmentation, CodeValidator (AST-based), ExecutionSandbox hardening, HypothesisTester
- **Phase 4** — AutoArchitectureSearch (NAS), CodeRefactoringAgent, SelfModifyingReasoningEngine
- **Phase 5** — CoreValues, OpportunityFinder, AutonomousGoalGenerator, MultiObjectiveOptimizer, LongTermPlanner
- **Phase 6** — AGI benchmarking suite (cross-domain transfer >60%, few-shot >70%, causal >80%, AGI-Score >70)

### Definition of Done
- [ ] All 6 phases implemented with test coverage ≥80% for new code
- [ ] All existing 169+ tests still passing (no regressions)
- [ ] Momus audit OKAY
- [ ] Phase-by-phase manual smoke test scripts execute cleanly
- [ ] Final F1–F4 verification agents all APPROVE

### Must Have
- All 6 phases delivered in a single coherent plan with concrete tasks
- File-anchored references (real paths in real codebase)
- Agent-executable QA scenarios for every task
- Zero breaking changes to live trading paths
- Safety gates respected (no bypasses)

### Must NOT Have (Guardrails)
- ❌ Do NOT touch existing strategy alpha logic (e.g., BTC momentum, bond scanner, etc.)
- ❌ Do NOT modify `backend/core/risk_profiles.py` or risk engine
- ❌ Do NOT change Polymarket/Kalshi execution interfaces
- ❌ Do NOT delete/rename any file under `backend/strategies/`
- ❌ Do NOT disable any existing passing tests
- ❌ Do NOT change database schema without Alembic migration

---

## TODOs

> EVERY task has concrete implementation steps + Agent-Executable QA scenarios.
> **A task without QA scenarios is INCOMPLETE** — this plan contains 120+ fully specified tasks.

---

### Wave 1 — Phase 1: Generalize Plugin System (Foundation)

> Parallel wave: 5 tasks, no dependencies among them. All can start immediately.
> Depends on completed PR #95 plugin refactor for wiring patterns.

- [ ] 1. SafetyMonitor — backend/core/safety.py

  **What to do**:
  - Create `backend/core/safety.py` with `SafetyMonitor` class
  - Implement bounded autonomy gates from `docs/architecture/adr-006-agi-autonomy-framework.md`:
    - `check_autonomy_level(proposed_action) → Allow/Deny/RequireHuman`
    - `is_bypassable(safety_gate) → bool` always False for critical gates (risk profile caps, bankroll limits)
    - `health_check(strategy_id) → dict{win_rate, pnl, drawdown, stage}`
  - Wire into `backend/core/auto_promote.py` (already exists) — call `safety_monitor.check_autonomy_level()` before each DRAFT→SHADOW, SHADOW→PAPER, PAPER→LIVE transition
  - Hook into `backend/core/risk_manager.py` (deterministic caps) — SafetyMonitor validates against `risk_profiles.py` caps
  - Add safety event logging via loguru
  - Unit test coverage ≥85 %

  **Must NOT do**:
  - Do NOT remove existing risk manager validations
  - Do NOT make gates configurable at runtime via API (must be static-coded safety)
  - Do NOT allow `safety_monitor.override()` from any trading code path

  **Recommended Agent Profile**:
  - **Category**: `quick` (single-file scaffold, well-defined gates)
  - **Skills**: [`typescript` for type hints compatibility, `python` core logic, `pytest` for tests]
  - Reason: Pure Python module, standard patterns, low complexity

  **Parallelization**:
  - **Can Run In Parallel**: YES — independent of Waves 2–6
  - **Parallel Group**: Wave 1 with Tasks 2–5
  - **Blocks**: Task 6 (learning system depends on safety gates)
  - **Blocked By**: None

  **References**:
  - Pattern: `backend/core/risk_profiles.py:12-45` — Risk tier caps (MAX_ALLOCATION dict)
  - API: `backend/core/auto_promote.py:promote_strategy()` — Use this hook point
  - ADR: `docs/architecture/adr-006-agi-autonomy-framework.md` — Safety boundaries definition
  - Test Pattern: `backend/tests/unit/test_risk_profiles.py` — Unit test structure example

  **Acceptance Criteria**:

  **Unit Tests** (pytest backend/tests/unit/test_safety_monitor.py):
  - [ ] `test_safety_monitor_denies_promotion_below_win_rate_threshold`
  - [ ] `test_safety_monitor_denies_promotion_exceeding_risk_tier_cap`
  - [ ] `test_safety_monitor_requires_human_for_high_risk_actions`
  - [ ] `test_safety_monitor_health_check_returns_correct_metrics`
  - [ ] `test_critical_gates_cannot_be_overridden`
  - `bun test` → PASS (0 failures)

  **QA Scenario 1: Safety gate blocks invalid promotion**
    Tool: Bash (pytest)
    Preconditions: Test DB with a DRAFT strategy having win_rate=25% (below 30 % threshold)
    Steps:
      1. `cd /home/openclaw/projects/1ai-poly-trader && /home/linuxbrew/.linuxbrew/bin/python3 -m pytest backend/tests/unit/test_safety_monitor.py::test_safety_monitor_denies_promotion_below_win_rate_threshold -xvs`
    Expected Result: Test PASS (safety returns DENY, strategy not promoted)
    Failure Indicators: Test FAIL or AssertionError
    Evidence: `.sisyphus/evidence/task-1-safety-denies-low-wr.txt`

  **QA Scenario 2: Safety gate allows valid promotion**
    Tool: Bash (pytest)
    Preconditions: Test DB with a DRAFT strategy having win_rate=38 %, Sharpe=1.2, drawdown=-4.5 %, stage=SHADOW
    Steps:
      1. `cd /home/openclaw/projects/1ai-poly-trader && /home/linuxbrew/.linuxbrew/bin/python3 -m pytest backend/tests/unit/test_safety_monitor.py::test_safety_monitor_allows_valid_promotion -xvs`
    Expected Result: Test PASS (safety returns ALLOW)
    Failure Indicators: Test FAIL
    Evidence: `.sisyphus/evidence/task-1-safety-allows-valid.txt`

  **Commit**: YES
  - Message: `feat(agi-safety): implement SafetyMonitor bounded autonomy gates from adr-006`
  - Files: `backend/core/safety.py`, `backend/tests/unit/test_safety_monitor.py`
  - Pre-commit: `/home/linuxbrew/.linuxbrew/bin/python3 -m pytest backend/tests/unit/test_safety_monitor.py`

- [ ] 2. ReasoningEngine generalization — enhance `backend/core/reasoning_engine.py`

  **What to do**:
  - Review current reasoning_engine.py — it likely handles trading-domain reasoning only
  - Generalize to multi-domain reasoning:
    - Add `ReasoningContext` dataclass with `domain: Literal["trading", "code", "meta", "safety"]`
    - `reason(query: str, context: ReasoningContext) → ReasoningResult`
    - Support cross-domain reasoning chains (e.g., "code modification → risk impact → trading outcome")
  - Implement domain routing via registry pattern (plug in reasoners per domain)
  - Trade-domain reasoner stays as default (preserve existing behavior)
  - Add new domains skeleton: `code_reasoner()`, `meta_reasoner()` (for self-reflection), `safety_reasoner()` (used by SafetyMonitor)
  - Unit tests for each domain router + integration test

  **Must NOT do**:
  - Do NOT break existing trading strategy reasoning paths
  - Do NOT make reasoning engine depend on LLM providers in a way that breaks offline mode
  - Do NOT remove existing heuristic-based fallbacks

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high` (architectural change affecting multiple reasoning paths)
  - **Skills**: `python` (refactor), `pytest` (test), `design-patterns` (registry pattern)
  - Reason: Multi-domain generalization — careful design needed to avoid breaking existing trading logic

  **Parallelization**:
  - **Can Run In Parallel**: YES — independent of Task 3 (KG expansion) though both coordinate via domain schemas
  - **Parallel Group**: Wave 1
  - **Blocks**: None (others can use ReasoningEngine once stable)
  - **Blocked By**: None

  **References**:
  - Existing: `backend/core/reasoning_engine.py` — Read first to understand current API
  - ADR: `docs/architecture/adr-006-agi-autonomy-framework.md` — AGI bounded autonomy context
  - Pattern: `backend/application/agi/codebase_intelligence.py:6-8` — AGI node registry pattern
  - Test: `backend/tests/unit/test_reasoning_engine.py` (if missing, create in this task)

  **Acceptance Criteria**:

  **Unit Tests** (new or extend):
  - [ ] `test_reasoning_engine_trading_domain_unchanged` — existing queries produce identical results
  - [ ] `test_reasoning_engine_routes_code_domain` — code query returns CodeReasoningResult
  - [ ] `test_reasoning_engine_routes_meta_domain` — meta query produces reflection
  - [ ] `test_reasoning_engine_routes_safety_domain` — safety query used by SafetyMonitor
  - [ ] `test_reasoning_chain_cross_domain` — code → risk → trading link works
  - `pytest` → PASS

  **QA Scenario: Existing trading strategy still gets correct reasoning**
    Tool: Bash (pytest)
    Preconditions: Existing test suite for reasoning_engine (pre-PR) present
    Steps:
      1. `cd /home/openclaw/projects/1ai-poly-trader && /home/linuxbrew/.linuxbrew/bin/python3 -m pytest backend/tests/unit/test_reasoning_engine.py -xvs`
    Expected Result: All pre-existing reasoning tests PASS (0 regressions)
    Failure Indicators: Any FAIL, decreased coverage reported by pytest-cov
    Evidence: `.sisyphus/evidence/task-2-reasoning-regression.txt`

  **QA Scenario: New meta-reasoning returns reflection**
    Tool: Bash (python3 -c)
    Preconditions: `backend/core/reasoning_engine.py` patched with meta_reasoner
    Steps:
      1. `cd /home/openclaw/projects/1ai-poly-trader backend/core && python3 -c "from reasoning_engine import ReasoningEngine; r = ReasoningEngine(); result = r.reason('Why did strategy X fail?', context=ReasoningContext(domain='meta')); print('reflection' in result.text.lower())"`
    Expected Result: prints True (meta reasoning recognized)
    Failure Indicators: False or KeyError
    Evidence: `.sisyphus/evidence/task-2-meta-reasoning.txt`

  **Commit**: YES
  - Message: `feat(agi-reasoning): generalize ReasoningEngine to multi-domain with routing registry`
  - Files: `backend/core/reasoning_engine.py`, `backend/tests/unit/test_reasoning_engine.py` (if new)
  - Pre-commit: `pytest backend/tests/unit/test_reasoning_engine.py`

- [ ] 3. KnowledgeGraph cross-domain generalization — extend `backend/core/knowledge_graph.py`

  **What to do**:
  - Inspect current `knowledge_graph.py` — it may be market-metadata only (prices, markets, CLOBs)
  - Generalize to cross-domain knowledge store:
    - Nodes: `Node(type, payload)` — types: `market`, `strategy`, `signal`, `code_module`, `trade_outcome`, `news_event`, `macro_indicator`
    - Edges: `Edge(src_id, dst_id, relation, weight)` — relations: `uses`, `produces`, `impacts`, `failed_due_to`, `similar_to`
    - Add `query_by_type(node_type)`, `query_relations(node_id)`, `traverse(start_node, depth)`
  - Populate with existing data adapters:
    - Market data from `MarketUniverseScanner` → market nodes + price edges
    - Genome registry → strategy nodes + code_module edges
    - Forensics → trade_outcome nodes + failed_due_to edges
    - Codebase → code_module nodes (from backend/ file structure)
  - Ensure queries used by `StrategySynthesizer` still work (backward compatible wrapper)
  - Unit tests ≥85 % coverage

  **Must NOT do**:
  - Do NOT drop existing market-data queries (keep backward compatibility)
  - Do NOT use external graph DB (keep SQLite/PostgreSQL via SQLAlchemy)
  - Do NOT store large blobs (keep payloads JSON-serializable, <1 KB each)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high` (schema change, backward compatibility)
  - **Skills**: `python`, `sqlalchemy`, `pytest`, `graph-datastructures`
  - Reason: Dual-layer compatibility (old API + new graph model) requires careful design

  **Parallelization**:
  - **Can Run In Parallel**: YES — alongside ReasoningEngine; they converge on AGI orchestration
  - **Parallel Group**: Wave 1
  - **Blocks**: None (StrategySynthesizer uses wrapper)
  - **Blocked By**: None

  **References**:
  - Existing: `backend/core/knowledge_graph.py` — Start here; read current schema
  - Usage: `backend/core/strategy_synthesizer.py` — shows current KG query patterns
  - Related: `backend/core/knowledge_graph.py` should integrate `backend/models/genome_registry.py:GenomePerformance`
  - Pattern: `backend/agi/codebase_intelligence.py` — code-as-graph precedents

  **Acceptance Criteria**:

  **Unit Tests**:
  - [ ] `test_kg_add_node_and_edge`
  - [ ] `test_kg_query_by_type_returns_correct_nodes`
  - [ ] `test_kg_traverse_depth_2`
  - [ ] `test_kg_backward_compat_get_market_metadata` — old API still works
  - [ ] `test_kg_populate_from_market_universe` — market nodes loaded
  - [ ] `test_kg_populate_from_genome_registry` — strategy nodes loaded
  - `pytest` → PASS

  **QA Scenario 1: KG returns cross-domain queries**
    Tool: Bash (python3 -c)
    Preconditions: KG populated with sample nodes from market + genome + forensics
    Steps:
      1. `cd /home/openclaw/projects/1ai-poly-trader && python3 -c "from knowledge_graph import KnowledgeGraph; kg = KnowledgeGraph(); strategies = kg.query_by_type('strategy'); print(len(strategies) > 0)"`
    Expected Result: prints True
    Failure Indicators: False or empty list
    Evidence: `.sisyphus/evidence/task-3-kg-cross-domain.txt`

  **QA Scenario 2: Existing market query still works**
    Tool: Bash (python3 -c)
    Preconditions: Pre-existing code somewhere calls `get_market(market_id)`
    Steps:
      1. `cd /home/openclaw/projects/1ai-poly-trader && python3 -c "from knowledge_graph import KnowledgeGraph; kg = KnowledgeGraph(); m = kg.get_market_by_id('0x123...'); print(m is not None)"`
    Expected Result: prints True (backward compat preserved)
    Failure Indicators: False or AttributeError
    Evidence: `.sisyphus/evidence/task-3-kg-backward-compat.txt`

  **Commit**: YES
  - Message: `feat(agi-kg): generalize KnowledgeGraph to cross-domain with backward compat`
  - Files: `backend/core/knowledge_graph.py`, `backend/tests/unit/test_knowledge_graph.py`
  - Pre-commit: `pytest backend/tests/unit/test_knowledge_graph.py`

- [ ] 4. SafetyMonitor — complete PluginManager wiring (registration layer)

  **What to do**:
  - `backend/core/plugin_manager.py` already exists from PR #95 plugin refactor
  - Wire SafetyMonitor, ReasoningEngine, KnowledgeGraph into PluginManager as core plugins:
    - `plugin_manager.register_plugin('safety', SafetyMonitor())`
    - `plugin_manager.register_plugin('reasoning', ReasoningEngine())`
    - `plugin_manager.register_plugin('kg', KnowledgeGraph())`
  - Add lifecycle hooks: on plugin error → trigger rollback; on safety violation → alert
  - Ensure plugin hot-reload respects safety (cannot unload SafetyMonitor while SHADOW/PAPER strategies exist)
  - Add plugin status endpoint to FastAPI /admin/plugins
  - Unit tests for registration + lifecycle

  **Must NOT do**:
  - Do NOT allow unregistration of SafetyMonitor at runtime
  - Do NOT permit dynamic replacement of reasoning engine without restart

  **Recommended Agent Profile**:
  - **Category**: `quick` (wiring only)
  - **Skills**: `python`, `fastapi`, `pytest`
  - Reason: Glue code — standard fastAPI routes + plugin registration

  **Parallelization**:
  - **Can Run In Parallel**: YES — depends on Tasks 1–3 but can merge once they are ready
  - **Parallel Group**: Wave 1 (merge when Tasks 1–3 done)
  - **Blocks**: None (other phases import plugin_manager regardless)
  - **Blocked By**: Tasks 1, 2, 3 (register after those modules are written)

  **References**:
  - PluginManager: `backend/core/plugin_manager.py` — from PR #95
  - Existing plugins (examples): `backend/strategies/*` registration pattern
  - FastAPI routes: `backend/api/main.py` — how admin endpoints are added
  - ADR: `docs/architecture/adr-006-agi-autonomy-framework.md` — Plugin lifecycle requirements

  **Acceptance Criteria**:

  **Unit Tests**:
  - [ ] `test_plugin_manager_registers_safety_monitor`
  - [ ] `test_plugin_manager_prevents_unload_safety_in_shadow`
  - [ ] `test_plugin_manager_error_hook_triggers_rollback`
  - [ ] `test_admin_plugins_endpoint_lists_all_plugins`
  - `pytest` → PASS

  **QA Scenario: Admin plugins endpoint lists all core plugins**
    Tool: Bash (curl)
    Preconditions: FastAPI server running, plugin_manager initialized
    Steps:
      1. `curl -s http://localhost:8100/admin/plugins | python3 -c "import sys,json; d=json.load(sys.stdin); print('safety' in [p['name'] for p in d])"`
    Expected Result: prints True
    Failure Indicators: False or curl connection refused
    Evidence: `.sisyphus/evidence/task-4-admin-plugins.txt`

  **Commit**: YES
  - Message: `feat(plugin-manager): wire SafetyMonitor, ReasoningEngine, KnowledgeGraph as core plugins`
  - Files: `backend/core/plugin_manager.py` (adds registration calls), `backend/api/main.py` (admin endpoint), `backend/tests/unit/test_plugin_manager.py`
  - Pre-commit: `pytest backend/tests/unit/test_plugin_manager.py`

- [ ] 5. Phase 1 integration: AGI subsystem ready (Safety + Reasoning + KG + PluginMgr)

  **What to do**:
  - Create integration test `backend/tests/integration/test_phase1_agi_subsystem.py`
  - Spin up in-memory SQLite DB, initialize PluginManager, register all Phase 1 plugins
  - Test scenario: ReasoningEngine receives a meta-cognitive query, queries KG, SafetyMonitor validates proposed action, all plugins stay registered
  - End-to-end assertion: no exceptions, safety gate returns ALLOW for safe action
  - Add CI marker `@pytest.mark.integration`

  **Must NOT do**:
  - Do NOT require external API keys (use mock LLM for reasoning)
  - Do NOT hit live market endpoints

  **Recommended Agent Profile**:
  - **Category**: `deep` (integration across 4 modules)
  - **Skills**: `python`, `pytest`, `fastapi-testclient`, `sqlalchemy`
  - Reason: Integration test — need to assemble multiple components correctly

  **Parallelization**:
  - **Can Run In Parallel**: NO — depends on Tasks 1–4 finishing first
  - **Blocks**: Wave 2 start (Phase 2 tasks depend on stable Phase 1)
  - **Blocked By**: Tasks 1, 2, 3, 4

  **References**:
  - Test patterns: `backend/tests/integration/test_agi_evolution.py` — existing AGI integration test template
  - Fixture: `backend/conftest.py` — db_session, app fixture
  - Models: `backend/models/*` — ORM models to instantiate

  **Acceptance Criteria**:

  **Integration Test**:
  - [ ] `test_phase1_agi_subsystem_initializes_without_error`
  - [ ] `test_phase1_reasoning_returns_meta_cognition`
  - [ ] `test_phase1_safety_allows_safe_action`
  - [ ] `test_phase1_kg_cross_domain_query_returns_nodes`
  - `pytest backend/tests/integration/test_phase1_agi_subsystem.py -xvs` → PASS

  **Commit**: YES
  - Message: `test(phase1): add integration test for AGI safety+reasoning+kg+plugin_manager subsystem`
  - Files: `backend/tests/integration/test_phase1_agi_subsystem.py`
  - Pre-commit: `pytest backend/tests/integration/test_phase1_agi_subsystem.py`

---

### Wave 2 — Phase 2: Cross-Domain Learning

> Starts after Wave 1 integration passes. Parallel tasks building on Phase 1 APIs.

- [ ] 6. ContinuousLearningSystem orchestration — `backend/core/learning_system.py`

  **What to do**:
  - `auto_improve.py` exists but is partial — wrap it into a full LearningSystem:
    - `LearningSystem` class: `observe(outcome, context)`, `suggest_improvement(strategy_id)`, `apply_rollback_if_needed(strategy_id)`
    - Orchestrate per-strategy learning loop: trade outcome → forensics → improvement proposal → sandbox test → rollback or deploy
    - Integrate with `StrategyRegistry` to find strategies eligible for improvement
    - Persist learning decisions in `BotState.misc_data` dict under key `learning_system_state`
  - Build on `auto_improve.py`'s per-strategy rollback dict — migrate to LearningSystem internal state
  - Scheduler hook: periodic `learning_cycle()` job (add to `backend/core/agi_jobs.py`)
  - Unit tests with forensics mock → verify propose → verify rollback logic

  **Must NOT do**:
  - Do NOT modify live strategy parameters without sandbox test + safety approval
  - Do NOT purge historical trade data used by forensics
  - Do NOT run learning cycle on LIVE_PROMOTED strategies without explicit admin flag

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high` (orchestrates multiple subsystems)
  - **Skills**: `python`, `pytest`, `sqlalchemy`
  - Reason: Integration of auto_improve, forensics, sandbox, scheduler — coordination complexity

  **Parallelization**:
  - **Can Run In Parallel**: Partially — core LearningSystem class can be written independently; integration tests wait for Task 7 (TransferLearner)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 8 (MultiDomainOrchestrator), Task 9 (Phase 2 integration)
  - **Blocked By**: Task 1 (SafetyMonitor gates must exist before learning changes parameters)

  **References**:
  - Base: `backend/core/auto_improve.py` — existing rollback dict logic
  - Forensics: `backend/core/trade_forensics.py` — root cause analysis output format
  - Forensics integration: `backend/core/forensics_integration.py` — improvement proposal generation
  - Scheduler: `backend/core/scheduler.py` or `backend/core/agi_jobs.py` — add periodic job
  - Safety: `backend/core/safety.py` — approval gate before parameter changes
  - Test pattern: `backend/tests/unit/test_auto_improve.py` (if exists)

  **Acceptance Criteria**:

  **Unit Tests**:
  - [ ] `test_learning_system_observes_outcome_and_logs`
  - [ ] `test_learning_system_proposes_improvement_via_forensics`
  - [ ] `test_learning_system_sandbox_tests_proposal_before_apply`
  - [ ] `test_learning_system_rollbacks_on_sandbox_failure`
  - [ ] `test_learning_system_respects_safety_gates`
  - `pytest` → PASS

  **QA Scenario: Learning cycle proposes and tests an improvement**
    Tool: Bash (pytest)
    Preconditions: Mock strategy with forensics report indicating overfit parameter; sandbox environment ready
    Steps:
      1. `cd /home/openclaw/projects/1ai-poly-trader && /home/linuxbrew/.linuxbrew/bin/python3 -m pytest backend/tests/unit/test_learning_system.py::test_learning_cycle_proposes_improvement -xvs`
    Expected Result: Test PASS — LearningSystem reads forensics, generates proposal, sandbox tests it, rolls back on failure, or writes to pending approval queue
    Failure Indicators: Test FAIL, no forensics call, sandbox not invoked
    Evidence: `.sisyphus/evidence/task-6-learning-cycle.txt`

  **Commit**: YES
  - Message: `feat(agi-learning): implement ContinuousLearningSystem orchestrator wrapping auto_improve`
  - Files: `backend/core/learning_system.py`, `backend/core/agi_jobs.py` (add learning_cycle job), `backend/tests/unit/test_learning_system.py`
  - Pre-commit: `pytest backend/tests/unit/test_learning_system.py`

- [ ] 7. TransferLearner — `backend/core/transfer_learning.py`

  **What to do**:
  - Implement cross-domain knowledge transfer module:
    - `TransferLearner` class with `transfer(source_domain: Domain, target_domain: Domain, strategy_template) → AdaptedStrategy`
    - Use `KnowledgeGraph` similarity edges (`similar_to`) to identify analogous patterns across domains (e.g., weather→crypto volatility patterns)
    - Parameter space transfer: map hyperparameters from source to target via learned scaling factors
    - Curriculum adaptation: adjust entry/exit thresholds for target domain liquidity/volatility
    - Cache transfer results in `GenomeRegistry` as `TransferRecord`
  - Provide transferrability score (0–1) — strategies with score <0.4 are rejected as non-transferable
  - Unit tests: synthetic domain pairs with known mapping

  **Must NOT do**:
  - Do NOT transfer between completely unrelated domains without explicit admin approval (e.g., weather → election markets)
  - Do NOT persist transferred strategies without running them through CodeValidator (Phase 3 dependency — defer activation to Phase 3)
  - Do NOT overwrite source domain parameters

  **Recommended Agent Profile**:
  - **Category**: `ultrabrain` (knowledge transfer research-level problem)
  - **Skills**: `python`, `pytest`, `ml` (parameter mapping), `graph-algorithms`
  - Reason: Non-trivial domain adaptation — similarity search + parameter scaling

  **Parallelization**:
  - **Can Run In Parallel**: YES — can be developed alongside Task 6
  - **Parallel Group**: Wave 2
  - **Blocks**: None (LearningSystem can use TransferLearner once ready)
  - **Blocked By**: Task 3 (KnowledgeGraph must be cross-domain before TransferLearner can query it)

  **References**:
  - KG: `backend/core/knowledge_graph.py` — `query_similar_nodes()`, `add_edge()`
  - Genome: `backend/models/genome_registry.py:StrategyGenome` — parameter structure
  - Test: `backend/tests/unit/test_transfer_learning.py` — create new

  **Acceptance Criteria**:

  **Unit Tests**:
  - [ ] `test_transfer_learner_finds_similar_domains`
  - [ ] `test_transfer_learner_maps_parameters_correctly`
  - [ ] `test_transfer_learner_rejects_low_score_transfers`
  - [ ] `test_transfer_record_persisted_in_genome_registry`
  - `pytest` → PASS

  **QA Scenario: Transfer from weather to crypto domain produces adapted strategy**
    Tool: Bash (python3 -c)
    Preconditions: KG populated with weather and crypto nodes, TransferLearner initialized
    Steps:
      1. `cd /home/openclaw/projects/1ai-poly-trader && python3 -c "from transfer_learning import TransferLearner; tl = TransferLearner(); adapted = tl.transfer('weather_volatility', 'crypto_volatility', template_strategy); print(adapted is not None and adapted.domain == 'crypto_volatility')"`
    Expected Result: prints True
    Failure Indicators: False, exception, or adapted.domain unchanged
    Evidence: `.sisyphus/evidence/task-7-transfer-weather-to-crypto.txt`

  **Commit**: YES
  - Message: `feat(agi-transfer): implement TransferLearner cross-domain parameter mapping via KG similarity`
  - Files: `backend/core/transfer_learning.py`, `backend/tests/unit/test_transfer_learning.py`
  - Pre-commit: `pytest backend/tests/unit/test_transfer_learning.py`

- [ ] 8. MultiDomainOrchestrator — integrate with `backend/core/orchestrator.py` / `backend/core/agi_orchestrator.py`

  **What to do**:
  - These files already exist — enhance them to use new Phase 1 + Phase 2 components:
    - Orchestrator should now route signals through: ReasoningEngine → KnowledgeGraph → SafetyMonitor → StrategySynthesizer
    - Add domain context propagation: when a signal arrives (e.g., weather → crypto), set `ReasoningContext(domain="trading", source_domain="weather")`
    - Enable cross-domain fusion: `MultiDomainOrchestrator` fuses signals from multiple domains via weighted confidence (weights from strat performance)
    - Add orchestration metrics endpoint `/admin/orchestration/metrics` — shows per-domain confidence, fused signal count
  - Unit tests: mock signals from 2 domains, verify fused output respects weights

  **Must NOT do**:
  - Do NOT remove existing single-domain orchestration path (keep backward compatibility for strategies not using AGI)
  - Do NOT allow SafetyMonitor bypass for fused signals

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: `python`, `fastapi`, `pytest`, `async`
  - Reason: Core routing logic affects entire system — needs comprehensive tests

  **Parallelization**:
  - **Can Run In Parallel**: With Task 6 completion (uses LearningSystem)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 9 (Phase 2 integration — uses orchestrator)
  - **Blocked By**: Tasks 1, 2, 3 (SafetyMonitor, ReasoningEngine, KG must exist)

  **References**:
  - Existing: `backend/core/orchestrator.py`, `backend/core/agi_orchestrator.py` — read current routing
  - StrategySynthesizer: `backend/core/strategy_synthesizer.py` — how signals are composed
  - Metrics endpoint pattern: `backend/api/admin.py` — existing admin endpoints
  - Test: `backend/tests/unit/test_orchestrator.py` (extend if present)

  **Acceptance Criteria**:

  **Unit Tests** (extend):
  - [ ] `test_orchestrator_routes_through_reasoning_engine`
  - [ ] `test_orchestrator_queries_kg_for_context`
  - [ ] `test_orchestrator_safety_gate_blocks_unsafe_signals`
  - [ ] `test_multidomain_fusion_weighted_confidence`
  - [ ] `test_orchestrator_backward_compat_single_domain`
  - `pytest` → PASS

  **QA Scenario: Multi-domain signal fusion produces weighted output**
    Tool: Bash (pytest)
    Preconditions: Mock weather and crypto signals, registered strategies with known performance
    Steps:
      1. `cd /home/openclaw/projects/1ai-poly-trader && /home/linuxbrew/.linuxbrew/bin/python3 -m pytest backend/tests/unit/test_agi_orchestrator.py::test_multidomain_fusion_weighted_confidence -xvs`
    Expected Result: Test PASS — fusion weights match strategy performance (higher WR gets more weight)
    Failure Indicators: FAIL, or weights uniform (ignores performance)
    Evidence: `.sisyphus/evidence/task-8-fusion-weights.txt`

  **Commit**: YES
  - Message: `feat(agi-orchestrator): enhance MultiDomainOrchestrator with ReasoningEngine+KG+Safety gates`
  - Files: `backend/core/orchestrator.py`, `backend/core/agi_orchestrator.py`, `backend/tests/unit/test_agi_orchestrator.py`
  - Pre-commit: `pytest backend/tests/unit/test_agi_orchestrator.py`

- [ ] 9. Phase 2 integration — Cross-domain learning subsystem

  **What to do**:
  - Integration test `backend/tests/integration/test_phase2_cross_domain_learning.py`
  - Scenario: Strategy A performs poorly in crypto → forensics diagnoses [cause] → LearningSystem (via TransferLearner) adapts strategy from weather domain → new strategy is proposed and sent to sandbox for testing → SafetyMonitor gates final promotion
  - Full orchestrated flow test using TestClient against FastAPI `/orchestrate` endpoint (or scheduler-invoked path)
  - Verify all events logged: forensics_report, transfer_record, sandbox_result, safety_decision
  - Test fails on any missing event

  **Must NOT do**:
  - Do NOT use real LLM or live market data (mocks everywhere)
  - Do NOT require external API keys

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: `python`, `pytest`, `fastapi-testclient`
  - Reason: Multi-step integration across 6+ modules

  **Parallelization**:
  - **Can Run In Parallel**: NO — depends on Tasks 6, 7, 8 (and by extension Task 1–4)
  - **Blocks**: Wave 3 start
  - **Blocked By**: Tasks 6, 7, 8

  **References**:
  - Integration pattern: `backend/tests/integration/test_agi_evolution.py`
  - Scheduler hooks: `backend/core/scheduler.py` or `backend/core/agi_jobs.py`
  - Forensics output schema: `backend/core/trade_forensics.py:ForensicReport`
  - Transfer learner output: `backend/core/transfer_learning.py:TransferRecord`

  **Acceptance Criteria**:

  **Integration Test**:
  - [ ] `test_phase2_full_loop_forensics_to_transfer_to_sandbox`
  - [ ] `test_phase2_safety_gates_apply_to_transferred_strategy`
  - [ ] `test_phase2_learning_cycle_records_all_events`
  - `pytest backend/tests/integration/test_phase2_cross_domain_learning.py -xvs` → PASS

  **Commit**: YES
  - Message: `test(phase2): add integration test for cross-domain learning loop (forensics→transfer→sandbox)`
  - Files: `backend/tests/integration/test_phase2_cross_domain_learning.py`
  - Pre-commit: `pytest backend/tests/integration/test_phase2_cross_domain_learning.py`

---

### Wave 3 — Phase 3: Autonomous Strategy Generation

- [ ] 10. StrategyCodeGenerator augmentation — enhance `backend/core/strategy_synthesizer.py`

  **What to do**:
  - Current synthesizer generates strategy code; now make it production-grade:
    - Add `generate_strategy_with_sandbox_test()` — auto-generates, writes to temp dir, runs `CodeValidator`, executes `ExecutionSandbox` mock-trades, returns success/failure
    - Template injection from `backend/application/strategy/genome_strategy.py` chromosome patterns — reuse existing entry/exit logic templates
    - Pass context from ReasoningEngine (domain) and KnowledgeGraph (market I

</think>
<tool_call>
<function=todowrite>