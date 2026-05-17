# True Full AGI Evolution Plan

## TL;DR

> **Quick Summary**: Evolve PolyEdge from its current bounded-AGI state (autonomous promotion pipeline, shadow-validation loop, genome evolution) to a True Full AGI system capable of cross-domain learning, autonomous strategy generation, recursive self-modification, unbounded goal formation, and certified AGI benchmarking — all within deterministic safety boundaries. All 6 phases build on existing infrastructure without breaking 169 passing tests.

> **Deliverables**:
> - SafetyMonitor with UI-configurable thresholds (5+ new/refactored files)
> - ProviderRegistry abstraction with 5 LLM backends (Runpod, Omniroute, OpenAI, HuggingFace, Ollama)
> - Generalized ReasoningEngine and KnowledgeGraph (cross-domain)
> - LearningSystem with online/offline learning + transfer learning
> - StrategyCodeGenerator with sandbox-test loop
> - Autonomous goal formation and multi-objective optimization
> - Self-modifying ReasoningEngine with SafetyMonitor gating
> - 4 AGI benchmarks (cross-domain transfer, few-shot, causal reasoning, AGI-Score)
> - All configuration UI-accessible via BotState.misc_data

> **Estimated Effort**: Large (6 phases, 35 tasks, ~34 new/modified files)
> **Parallel Execution**: YES — 6 parallel waves (up to 7 concurrent tasks)
> **Critical Path**: Task 1 (SafetyMonitor) → Task 2 (ProviderRegistry) → Task 3 (ReasoningEngine) → Phase 1 integration → Phase 2 (LearningSystem) → Phase 3 (StrategyCodeGenerator) → Phase 4 (NAS) → Phase 5 (GoalFormation) → Phase 6 (Benchmarks) → Final Certification

---

## Context

### Original Request
Evolve PolyEdge into a True Full AGI trading system with: autonomous strategy generation, self-modifying reasoning engine, cross-domain transfer learning, causal reasoning, multi-objective optimization, and a composite AGI-Score benchmark. Must remain safe, testable, and incrementally deployable on the existing `feature/plugin-system-refactoring` branch.

### Interview Summary
**Key Decisions**:
- Full scope confirmed: all 6 phases from safety foundation through AGI certification
- All configuration UI-configurable in addition to env var defaults
- InferenceProvider chain must support 5 backends with priority/failover
- Momus high-accuracy review selected (option B) — must loop until OKAY
- No new branches/PRs — all on `feature/plugin-system-refactoring` (PR #95)

**Research Findings**:
- Existing AGI infrastructure: autonomous promoter, bankroll allocator, evolution jobs, genome registry+compiler, forensics, lifecycle manager, strategy synthesizer
- Missing: safety.py, learning_system.py, transfer_learning.py, evals/ directory, causal_reasoning.py, goal/values/planner suite
- Existing tests: 169 passing, pytest suite exits SIGTERM (143) — use batch groups per wave
- ProviderRegistry new files needed: base_provider.py, provider_registry.py, runpod/omniroute/openai/huggingface/ollama providers

### Metis Review
**Identified Gaps** (addressed):
- ProviderRegistry interface design: 5-provider chain with priority/failover
- SafetyMonitor missing: treat as Phase 1 Task 1 — without safety no AGI expands
- Evals scaffold needed from Phase 1 to house Phase 6 benchmarks
- Phase Gate CI checks after each wave prevent dependency drift
- KnowledgeGraph generalization needed before cross-domain Phase 5
- Momus review confirmed file incompleteness: Phases 1-2 must be prepended

---

## Work Objectives

### Core Objective
Build a certified True Full AGI trading system on PolyEdge's existing bounded-AGI foundation, with safe recursive self-improvement, cross-domain intelligence, and quantifiable capability thresholds.

### Concrete Deliverables
- 35 tasks across 6 phases + final verification
- ~34 new/modified files across backend/core, backend/agi, backend/ai, backend/evals, backend/api
- 4 AGI benchmarks with hard thresholds (transfer>60%, few-shot>70%, causal>80%, AGI-Score>70)
- All new AGI features gated by SafetyMonitor and Phase Gates 1-6

### Definition of Done
- [ ] All 35 tasks implemented with passing tests
- [ ] All 4 benchmark thresholds met
- [ ] SafetyMonitor zero CRITICAL alerts during certification
- [ ] UI configuration endpoints functional for all AGI parameters
- [ ] All 169 existing tests pass (no regressions)
- [ ] Certificate timestamp recorded in BotState

### Must Have
- SafetyMonitor guarding all AGI operations (UI+env configurable thresholds)
- ProviderRegistry as single LLM entry point (5 providers, priority chain, failover)
- KnowledgeGraph generalized for cross-domain queries
- LearningSystem with online/offline modes
- TransferLearner for cross-domain adaptation
- StrategyCodeGenerator with sandbox+validation loop
- CodeValidator AST-based security checker
- ExecutionSandbox with resource limits and isolation
- HypothesisTester with statistical significance
- AutoArchitectureSearch with GPU budget
- CodeRefactoringAgent with test-gated rollback
- SelfModifyingReasoningEngine with risk-gated safety
- CoreValues alignment system with UI-configurable thresholds
- OpportunityFinder scanning cross-domain edges
- AutonomousGoalGenerator with multi-objective optimization
- LongTermPlanner with 90-day resource scheduling
- 4 AGI benchmarks meeting published thresholds
- AGI-Score composite metric with certification

### Must NOT Have (Guardrails)
- No direct LLM imports in AGI code — always through ProviderRegistry
- No trading logic changes — existing strategies untouched
- No unsafe code execution outside ExecutionSandbox
- No self-modification of strategy/risk engine code without SafetyMonitor gate
- No goals exceeding AGGRESSIVE risk tier without explicit admin override
- No benchmark bypass or threshold relaxation
- No hardcoded configuration — all values configurable via UI or env var
- No breaking changes to existing 169 tests

---

## Verification Strategy (MANDATORY)

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed. No exceptions.

### Test Decision
- **Infrastructure exists**: YES (pytest.ini, 169 tests across unit+integration)
- **Automated tests**: YES (Tests-after — each task includes unit tests; integration tests per phase)
- **Framework**: pytest (Python backend)
- **Runner**: `/home/linuxbrew/.linuxbrew/bin/python3 -m pytest` (not `rtk pytest` wrapper)

### QA Policy
Every task MUST include agent-executed QA scenarios. Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`.

- **Backend/API**: Bash (curl) — Send requests, assert status + response fields
- **Library/Module**: Bash (pytest) — Run test commands, assert PASS
- **CLI/TUI**: Bash (python3 -c) — Import modules, call functions, compare output
- **Frontend/UI**: Not in scope for this plan (backend-only AGI evolution)

---

## Execution Strategy

### Parallel Execution Waves

> Maximize throughput by grouping independent tasks into parallel waves.
> Each wave completes before the next begins (Phase Gate sign-off required between waves).

```
Wave 1 — Phase 1a: Foundation (7 parallel tasks):
├── Task 1: SafetyMonitor [quick]
├── Task 2: ProviderRegistry + 5 backends [quick]
├── Task 3: ReasoningEngine generalization [quick]
├── Task 4: KnowledgeGraph cross-domain [quick]
├── Task 5: PluginManager wiring [quick]
├── Task 6: Evals scaffold [quick]
└── Task 7: Phase 1 integration [unspecified-high]

Wave 2 — Phase 1b + 2: Learning & Transfer (6 parallel tasks):
├── Task 8: Phase Gate 1 [quick]
├── Task 9: LearningSystem [unspecified-high]
├── Task 10: TransferLearner [unspecified-high]
├── Task 11: MultiDomainOrchestrator [unspecified-high]
├── Task 12: Phase 2 integration [unspecified-high]
└── Task 13: Phase Gate 2 [quick]

[Wave 3 onward — Phase 3-6: existing plan content]
├── Task 14: StrategyCodeGenerator augmentation [unspecified-high]
├── Task 15: CodeValidator [unspecified-high]
├── Task 16: ExecutionSandbox hardening [unspecified-high]
├── Task 17: HypothesisTester [unspecified-high]
├── Task 18: Phase 3 integration [deep]
├── Task 19: Phase Gate 3 [deep]
├── Task 21: AutoArchitectureSearch (NAS) [ultrabrain]
├── Task 22: CodeRefactoringAgent [unspecified-high]
├── Task 23: SelfModifyingReasoningEngine [ultrabrain]
├── Task 24: Phase Gate 4 [deep]
├── Task 25: CoreValues [deep]
├── Task 26: OpportunityFinder [unspecified-high]
├── Task 27: AutonomousGoalGenerator [deep]
├── Task 28: MultiObjectiveOptimizer [ultrabrain]
├── Task 29: LongTermPlanner [deep]
├── Task 30: Phase Gate 5 [deep]
├── Task 31: Cross-Domain Transfer benchmark [deep]
├── Task 32: Few-Shot Learning benchmark [deep]
├── Task 33: Causal Reasoning benchmark [ultrabrain]
├── Task 34: AGI-Score benchmark [deep]
└── Task 35: Phase Gate 6 + Final Certification [oracle]

Wave FINAL (4 parallel reviews):
├── F1: Plan Compliance Audit [oracle]
├── F2: Code Quality Review [unspecified-high]
├── F3: Real Manual QA [unspecified-high]
└── F4: Scope Fidelity Check [deep]
→ Present results → Get explicit user okay

Critical Path: Task 1 → Task 7 → Task 12 → Phase Gate 2 → Phase 3 → Phase 4 → Phase 5 → Phase 6 → Final Verification
Parallel Speedup: ~65% faster than sequential
Max Concurrent: 7 (Wave 1)
```

### Dependency Matrix

- Task 1 (SafetyMonitor): None — Wave 1 leader
- Task 2 (ProviderRegistry): None — Wave 1 leader
- Task 3 (ReasoningEngine): None — Wave 1 leader
- Task 4 (KnowledgeGraph): None — Wave 1 leader
- Task 5 (PluginRegistry): Task 2 (provider routing config)
- Task 6 (Evals scaffold): None — Wave 1 leader
- Task 7 (Phase 1 integration): Tasks 1-6
- Task 8 (Phase Gate 1): Tasks 1-7
- Task 9 (LearningSystem): Tasks 3, 4 (ReasoningEngine + KnowledgeGraph)
- Task 10 (TransferLearner): Tasks 4, 9 (KnowledgeGraph + LearningSystem)
- Task 11 (MultiDomainOrchestrator): Tasks 4, 9, 10
- Task 12 (Phase 2 integration): Tasks 9-11
- Task 13 (Phase Gate 2): Tasks 8-12
- Tasks 14+: Blocked by Phase Gate 2 (see existing plan content)

### Agent Dispatch Summary

- **Wave 1**: 7 tasks — Tasks 1-6 → `quick`, Task 7 → `unspecified-high`
- **Wave 2**: 6 tasks — Tasks 9-12 → `unspecified-high`/`deep`, Tasks 8,13 → `quick`
- **Wave 3**: 6 tasks — Tasks 14,15,16,17 → `unspecified-high`, Tasks 18,19 → `deep`
- **Wave 4**: 4 tasks — Tasks 21,23 → `ultrabrain`, Task 22 → `unspecified-high`, Task 24 → `deep`
- **Wave 5**: 6 tasks — Tasks 25,27,29 → `deep`, Task 26 → `unspecified-high`, Task 28 → `ultrabrain`, Task 30 → `deep`
- **Wave 6**: 5 tasks — Tasks 31,32,34 → `deep`, Task 33 → `ultrabrain`, Task 35 → `oracle`
- **Final**: 4 tasks — F1 → `oracle`, F2,F3 → `unspecified-high`, F4 → `deep`

---

## TODOs

### Wave 1 — Phase 1a: Foundation & Infrastructure

> Parallel wave: 7 tasks (Tasks 1-7). All can start concurrently.
> These are the critical bedrock — every subsequent phase depends on them.

- [x] 1. SafetyMonitor — create `backend/core/safety.py`

  **What to do**:
  - Create `SafetyMonitor` module:
    - `RiskMonitor` class: maintains per-strategy and global risk state
    - Methods: `check_trade(signal) → (approved: bool, reason: str)`, `get_risk_tier(strategy_key) → str`, `set_risk_tier(strategy_key, tier)`, `get_global_limits() → dict`, `record_alert(severity, message)`
    - Thresholds read from `BotState.misc_data['safety_thresholds']` (UI-configurable); fallback to env vars (`SAFETY_MAX_POSITION_SIZE`, `SAFETY_MAX_DAILY_LOSS`, `SAFETY_MIN_CONFIDENCE`)
    - Alert severity: INFO, WARNING, CRITICAL. CRITICAL alerts auto-pause trading for that strategy.
    - Persist alert history to `BotState.misc_data['safety_alerts']` (list of dicts with timestamp)
  - Unit tests: mock BotState thresholds; verify trade approval/rejection; verify CRITICAL alert pauses strategy
  - Integration: SafetyMonitor must be importable and usable by all AGI phases; expose health endpoint `/agi/safety/status`

  **Must NOT do**:
  - Do NOT hardcode thresholds — always read from BotState.misc_data or env var
  - Do NOT allow bypass of CRITICAL alerts without explicit admin override in UI
  - Do NOT modify existing trade execution flow — SafetyMonitor is advisory/blocking, not mutating

  **Recommended Agent Profile**:
  - **Category**: `quick` (well-defined, safety-critical but straightforward)
  - **Skills**: `python`, `pytest`, `fastapi`
  - Reason: Safety infrastructure is foundational but API surface is simple and well-scoped

  **Parallelization**:
  - **Can Run In Parallel**: YES — independent foundation piece
  - **Parallel Group**: Wave 1
  - **Blocks**: All subsequent phases (safety gates needed everywhere)
  - **Blocked By**: None

  **References**:
  - BotState pattern: `backend/core/bankroll_allocator.py` reads from `BotState.misc_data`
  - Existing risk: `backend/core/risk_profiles.py` — `RISK_TIER_MAX_ALLOCATION` dict, 6 risk presets
  - Safety patterns: no existing `backend/core/safety.py` — create from scratch

  **Acceptance Criteria**:

  **Unit Tests**:
  - [ ] `test_safety_monitor_approves_safe_trade`
  - [ ] `test_safety_monitor_rejects_oversized_trade`
  - [ ] `test_safety_monitor_critical_alert_pauses_strategy`
  - [ ] `test_safety_monitor_reads_thresholds_from_botstate`
  - `pytest backend/tests/unit/test_safety_monitor.py -xvs` → PASS

  **QA Scenario 1: SafetyMonitor approves valid trade**
    Tool: Bash (python3 -c)
    Preconditions: BotState.misc_data['safety_thresholds'] = {"max_position_size": 1000, "max_daily_loss": 500}
    Steps:
      1. `python3 -c "from backend.core.safety import SafetyMonitor; s = SafetyMonitor(); r = s.check_trade({'position_size': 100, 'confidence': 0.8}); print(r.approved, r.reason)"`
    Expected Result: `True trade_approved`
    Failure Indicators: False or error
    Evidence: `.sisyphus/evidence/task-1-approve-trade.txt`

  **QA Scenario 2: SafetyMonitor CRITICAL alert pauses strategy**
    Tool: Bash (python3 -c)
    Preconditions: Thresholds configured; trade exceeds max_position_size
    Steps:
      1. `python3 -c "from backend.core.safety import SafetyMonitor; s = SafetyMonitor(); s.check_trade({'position_size': 5000}); a = s.get_alerts('test_strat'); print(len([x for x in a if x['severity']=='CRITICAL']))"`
    Expected Result: prints 1 (alert recorded)
    Failure Indicators: prints 0 or error
    Evidence: `.sisyphus/evidence/task-1-critical-alert.txt`

  **Commit**: YES
  - Message: `feat(agi-safety): implement SafetyMonitor with UI-configurable risk thresholds and alert system`
  - Files: `backend/core/safety.py`, `backend/tests/unit/test_safety_monitor.py`
  - Pre-commit: `pytest backend/tests/unit/test_safety_monitor.py`

- [x] 2. ProviderRegistry — augment existing `backend/ai/provider_registry.py` + add 5 new provider backends

  **What to do**:
  - **IMPORTANT CONTEXT**: `backend/ai/provider_registry.py` and `backend/ai/base_provider.py` ALREADY EXIST and are fully functional:
    - `BaseAIProvider` (base_provider.py): abstract class with `manifest()`, `complete()`, `ProviderManifest` dataclass
    - `ProviderRegistry` (provider_registry.py): singleton extending `PluginRegistry[ProviderManifest, BaseAIProvider]` with health checks, env var validation, plugin registration
    - 4 existing providers in `backend/ai/providers/`: `claude_provider.py`, `gemini_provider.py`, `groq_provider.py`, `openrouter_provider.py`
    - Missing: priority/failover `get(name)` method, UI-configurable provider chain, `embed()` method on base, `cost()` tracking
  - **Augment** `backend/ai/provider_registry.py`:
    - Add priority/failover: `get(name=None, prefer_fastest=False) → BaseAIProvider` — returns highest-priority healthy provider
    - Failover behavior: if `get(name)` fails, fall through to next healthy provider with same tag/type; if all fail, raise `AllProvidersExhausted`
    - Add `set_provider_chain(ordered_names: list[str])` — reads priority chain from `BotState.misc_data['provider_chain']` (UI-configurable)
    - Add `embed()` method if missing on BaseAIProvider (optional, default returns empty list)
    - Convert stdlib `logging` to `loguru` `logger.bind(task="provider_registry")` pattern
  - Create 5 new provider backends in `backend/ai/providers/` following existing patterns:
    1. `runpod_provider.py` — calls Runpod Serverless endpoint via requests
    2. `omniroute_provider.py` — calls Omniroute API
    3. `openai_provider.py` — calls OpenAI chat completions
    4. `huggingface_provider.py` — calls HuggingFace Inference API
    5. `ollama_provider.py` — calls local Ollama instance
  - Each provider: subclass `BaseAIProvider`, define `manifest()` with name/env_vars/cost, implement `complete()`
  - Provider errors (timeout, auth, rate-limit) caught and logged; do not crash the caller
  - Integration: All AGI LLM calls route through `ProviderRegistry.get()` — no direct imports of provider SDKs

  **Must NOT do**:
  - Do NOT import any provider SDK directly — all calls go through ProviderRegistry
  - Do NOT hardcode provider priority — always read from BotState.misc_data
  - Do NOT let provider errors propagate — catch and log, then failover
  - Do NOT store API keys in code — read from env vars only

  **Recommended Agent Profile**:
  - **Category**: `quick` (augment existing pattern + 5 implementations)
  - **Skills**: `python`, `pytest`, `requests`, `llm-api`
  - Reason: Existing infrastructure already solid — just add failover + 5 providers

  **Parallelization**:
  - **Can Run In Parallel**: YES — independent foundation
  - **Parallel Group**: Wave 1
  - **Blocks**: All AGI phases that use LLM (Tasks 3, 4, 9, 10, 11, 14, 17, 21-23, 25-35)
  - **Blocked By**: None

  **References**:
  - Existing: `backend/ai/provider_registry.py` — full singleton registry extending PluginRegistry
  - Existing: `backend/ai/base_provider.py` — BaseAIProvider abstract class
  - Existing providers: `backend/ai/providers/claude_provider.py`, `backend/ai/providers/groq_provider.py` — patterns to copy
  - LLM usage: `backend/core/strategy_synthesizer.py` — refactor to use ProviderRegistry.get()
  - Env var pattern: `.env.example` for API keys
  - BotState pattern: `backend/core/autonomous_promoter.py` reads from BotState.misc_data

  **Acceptance Criteria**:

  **Unit Tests**:
  - [ ] `test_provider_registry_returns_highest_priority_healthy_provider`
  - [ ] `test_provider_registry_failover_when_primary_unhealthy`
  - [ ] `test_provider_registry_raises_all_exhausted`
  - [ ] `test_provider_registry_chain_configurable_via_botstate`
  - [ ] `test_each_provider_implements_complete_and_health`
  - [ ] Existing 4 providers still work after augmentation
  - `pytest backend/ai/tests/test_provider_registry.py -xvs` → PASS

  **QA Scenario: ProviderRegistry failover to secondary**
    Tool: Bash (pytest)
    Preconditions: Existing 4 providers registered; Provider A (priority=1, health()=False), Provider B (priority=2, health()=True)
    Steps:
      1. `pytest backend/ai/tests/test_provider_registry.py::test_failover_to_secondary -xvs`
    Expected Result: Test PASS — `get()` returns Provider B
    Failure Indicators: Returns A or raises AllProvidersExhausted
    Evidence: `.sisyphus/evidence/task-2-failover.txt`

  **Commit**: YES
  - Message: `feat(agi-provider): augment ProviderRegistry with priority failover + 5 new backends (Runpod, Omniroute, OpenAI, HuggingFace, Ollama)`
  - Files: `backend/ai/provider_registry.py`, `backend/ai/base_provider.py`, `backend/ai/providers/runpod_provider.py`, `backend/ai/providers/omniroute_provider.py`, `backend/ai/providers/openai_provider.py`, `backend/ai/providers/huggingface_provider.py`, `backend/ai/providers/ollama_provider.py`, `backend/ai/tests/test_provider_registry.py`
  - Pre-commit: `pytest backend/ai/tests/`

- [x] 3. ReasoningEngine — create `backend/core/reasoning_engine.py`

  **What to do**:
  - Create `backend/core/reasoning_engine.py` (file does not exist yet; `backend/core/agi_orchestrator.py` has existing AGI orchestration logic to draw from):
    - Define `ReasoningContext` dataclass: `domain: str (crypto|weather|sports|general)`, `query: str`, `constraints: list[str]`, `evidence: list[dict]`
    - Define `ReasoningResult` dataclass: `conclusion, confidence: float, reasoning_chain: list[str], supporting_evidence: list[dict]`
    - Add `ReasoningEngine.reason(context) → ReasoningResult`:
    - Add `ReasoningContext` dataclass: `domain: str (crypto|weather|sports|general)`, `query: str`, `constraints: list[str]`, `evidence: list[dict]`
    - Add `ReasoningEngine.reason(context) → ReasoningResult`:
      - Uses ProviderRegistry for LLM-based reasoning (route through Task 2)
      - Returns `ReasoningResult(conclusion, confidence, reasoning_chain, supporting_evidence)`
    - Keep existing trading-specific methods as domain-specific wrappers (backward compat)
    - Structured logging: `logger.bind(task="reasoning", domain=context.domain).info(...)`
    - Error handling: ProviderRegistry failures caught, fallback to rule-based reasoning or return low-confidence result
  - Update existing callers to use new interface without breaking them
  - Unit tests: mock ProviderRegistry; assert `reason()` returns structured result; test cross-domain queries

  **Must NOT do**:
  - Do NOT remove existing trading-specific methods — add, don't delete
  - Do NOT use ProviderRegistry directly — call through ProviderRegistry.get()
  - Do NOT expose raw ProviderRegistry output in ReasoningResult — always wrap

  **Recommended Agent Profile**:
  - **Category**: `quick` (enhance existing module with clean extension)
  - **Skills**: `python`, `pytest`, `dataclasses`
  - Reason: Structured generalization of existing module; well-scoped

  **Parallelization**:
  - **Can Run In Parallel**: YES — Wave 1 (depends on Task 2 for ProviderRegistry)
  - **Parallel Group**: Wave 1
  - **Blocks**: Tasks 9 (LearningSystem uses ReasoningEngine), Tasks 23 (self-mod)
  - **Blocked By**: Task 2 (ProviderRegistry for LLM calls)

  **References**:
  - Draw from: `backend/core/agi_orchestrator.py` — existing AGI orchestration logic to generalize
  - Reasoning patterns: `backend/agi/codebase_intelligence.py` — existing codebase analysis module
  - Logging: loguru pattern throughout project

  **Acceptance Criteria**:

  **Unit Tests**:
  - [ ] `test_reasoning_engine_returns_structured_result`
  - [ ] `test_reasoning_engine_supports_multiple_domains`
  - [ ] `test_reasoning_engine_fallback_on_provider_failure`
  - [ ] `test_existing_methods_still_work`
  - `pytest backend/core/tests/test_reasoning_engine.py -xvs` → PASS

  **QA Scenario: ReasoningEngine handles cross-domain query**
    Tool: Bash (pytest)
    Preconditions: Mock ProviderRegistry returns {"conclusion": "correlation_detected"}; ReasoningEngine initialized
    Steps:
      1. `pytest backend/core/tests/test_reasoning_engine.py::test_reasoning_handles_weather_domain -xvs`
    Expected Result: Test PASS — context.domain="weather" returns valid ReasoningResult
    Failure Indicators: Fails or returns generic domain
    Evidence: `.sisyphus/evidence/task-3-cross-domain-reasoning.txt`

  **Commit**: YES
  - Message: `feat(agi-reasoning): generalize ReasoningEngine with ReasoningContext, cross-domain support, ProviderRegistry integration`
  - Files: `backend/core/reasoning_engine.py`, `backend/core/tests/test_reasoning_engine.py`
  - Pre-commit: `pytest backend/core/tests/test_reasoning_engine.py`

- [x] 4. KnowledgeGraph cross-domain generalization — enhance `backend/core/knowledge_graph.py`

  **What to do**:
  - Current KnowledgeGraph likely focused on trading correlations; generalize:
    - Add `query_by_cross_domain(source_domain, target_domain) → list[Relation]` — find entities linked across domains
    - Add `inject_domain_knowledge(domain, entities, relations)` — batch insert domain ontology
    - Add confidence threshold filtering: `query(min_confidence=0.5)`
    - All new methods route through same existing storage (no migration needed)
    - Structured logging per query: `logger.bind(task="knowledge_graph", query_type="cross_domain").info(...)`
  - Unit tests: create test domain data (weather→crypto correlations); verify cross-domain queries return expected relations

  **Must NOT do**:
  - Do NOT change existing query methods — add, don't modify
  - Do NOT add new storage backend — use existing KnowledgeGraph persistence
  - Do NOT introduce LLM calls — KnowledgeGraph is pure retrieval, ProviderRegistry is for generation

  **Recommended Agent Profile**:
  - **Category**: `quick` (targeted extension of existing module)
  - **Skills**: `python`, `pytest`, `knowledge-graph`
  - Reason: Adding specific query methods to existing graph; well-scoped

  **Parallelization**:
  - **Can Run In Parallel**: YES — Wave 1 foundation piece
  - **Parallel Group**: Wave 1
  - **Blocks**: Tasks 10 (TransferLearner uses cross-domain queries), Tasks 26, 31, 32, 33 (benchmarks use KG)
  - **Blocked By**: None (uses existing storage, no new external deps)

  **References**:
  - Existing: `backend/core/knowledge_graph.py:query_by_type()`, `query_relations()`
  - Usage: search for KnowledgeGraph imports — understand current API before extending
  - Cross-domain patterns: KG literature on multi-relational graph queries

  **Acceptance Criteria**:

  **Unit Tests**:
  - [ ] `test_knowledge_graph_cross_domain_query_returns_results`
  - [ ] `test_knowledge_graph_inject_domain_knowledge`
  - [ ] `test_knowledge_graph_confidence_filtering`
  - `pytest backend/core/tests/test_knowledge_graph.py -xvs` → PASS

  **QA Scenario: Cross-domain query finds weather→crypto link**
    Tool: Bash (pytest)
    Preconditions: KG seeded with weather entities and crypto entities, 2 cross-domain relations
    Steps:
      1. `pytest backend/core/tests/test_knowledge_graph.py::test_cross_domain_weather_crypto -xvs`
    Expected Result: Test PASS — query returns relation "weather_event_X correlates_with crypto_market_Y", confidence 0.62
    Failure Indicators: Empty result or wrong relation type
    Evidence: `.sisyphus/evidence/task-4-cross-domain-kg.txt`

  **Commit**: YES
  - Message: `feat(agi-kg): generalize KnowledgeGraph with cross-domain queries and domain injection`
  - Files: `backend/core/knowledge_graph.py`, `backend/core/tests/test_knowledge_graph.py`
  - Pre-commit: `pytest backend/core/tests/test_knowledge_graph.py`

- [x] 5. PluginRegistry wiring — augment `backend/core/plugin_registry.py`

  **What to do**:
  - The PluginRegistry was created in PR #95 (plugin system refactoring) as `backend/core/plugin_registry.py`. Now wire it into AGI pipeline:
    - Add `plugin_registry.discover_agi_modules()` — scans `backend/agi/`, `backend/ai/`, `backend/evals/` for AGI plugin modules
    - Add `plugin_registry.register_agi_provider(name, provider_instance)` — so ProviderRegistry can discover plugins
    - Integration test: PluginRegistry discovers AGI modules after Phase 1 creation
    - Log all discovered/wired AGI modules: `logger.bind(task="plugin_registry", type="agi").info(...)`
  - Unit tests: mock AGI module directories; verify discovery works

  **Must NOT do**:
  - Do NOT break existing plugin functionality from PR #95
  - Do NOT auto-register modules with errors — skip and log warning

  **Recommended Agent Profile**:
  - **Category**: `quick` (wiring + discovery, no new module creation)
  - **Skills**: `python`, `pytest`, `importlib`
  - Reason: Straightforward module discovery pattern

  **Parallelization**:
  - **Can Run In Parallel**: YES — after Task 2 (ProviderRegistry to register providers)
  - **Parallel Group**: Wave 1
  - **Blocks**: None (advisory — integration tests use it)
  - **Blocked By**: Task 2

  **References**:
  - Plugin registry: `backend/core/plugin_registry.py` from PR #95
  - Provider registry: `backend/ai/provider_registry.py` (Task 2) — provider registration
  - Module discovery: `importlib` or `pkgutil.iter_modules`

  **Acceptance Criteria**:

  **Unit Tests**:
  - [ ] `test_plugin_registry_discovers_agi_modules`
  - [ ] `test_plugin_registry_registers_agi_providers`
  - [ ] `test_plugin_registry_skips_broken_modules`
  - `pytest` → PASS

  **QA Scenario: PluginRegistry discovers new AGI modules**
    Tool: Bash (pytest)
    Preconditions: backend/agi/ has at least one module; PluginRegistry loaded
    Steps:
      1. `pytest backend/core/tests/test_plugin_registry.py::test_discover_agi_modules -xvs`
    Expected Result: Test PASS — discovered list includes backend/agi modules
    Failure Indicators: Empty list or error
    Evidence: `.sisyphus/evidence/task-5-plugin-discovery.txt`

  **Commit**: YES
  - Message: `feat(agi-plugins): wire PluginRegistry into AGI pipeline for module discovery and provider registration`
  - Files: `backend/core/plugin_registry.py`, `backend/core/tests/test_plugin_registry.py`
  - Pre-commit: `pytest backend/core/tests/test_plugin_registry.py`

- [x] 6. Evals scaffold — create `backend/evals/` directory structure

  **What to do**:
  - Create directory: `backend/evals/`
  - Create `backend/evals/__init__.py` — exports `EvalsRunner`, `BenchmarkRegistry`
  - Create `backend/evals/runner.py`:
    - `EvalsRunner` class: `run_benchmark(benchmark_id, fixtures) → BenchmarkResult`
    - `BenchmarkResult` dataclass: `benchmark_id, score: float, passed: bool, metadata: dict, timestamp`
    - Runner auto-discovers benchmarks registered in `BenchmarkRegistry`
  - Create `backend/evals/registry.py`:
    - `BenchmarkRegistry` singleton: `register(benchmark_id, benchmark_class)`, `list() → list[str]`, `get(benchmark_id) → BenchmarkClass`
  - Create `backend/evals/benchmarks/__init__.py` — Phase 6 benchmarks will register here
  - Create `backend/evals/reports/` — JSON output directory for benchmark results
  - Create `backend/evals/tests/test_runner.py` — unit tests for runner and registry
  - All modules use structured logging: `logger.bind(task="evals", benchmark_id=x).info(...)`

  **Must NOT do**:
  - Do NOT implement actual benchmarks in this task — scaffold only (Phase 6 fills them)
  - Do NOT create files outside `backend/evals/` tree
  - Do NOT depend on files from later phases

  **Recommended Agent Profile**:
  - **Category**: `quick` (directory scaffold + simple runner)
  - **Skills**: `python`, `pytest`, `dataclasses`
  - Reason: Standard scaffold creation pattern

  **Parallelization**:
  - **Can Run In Parallel**: YES — independent foundation
  - **Parallel Group**: Wave 1
  - **Blocks**: Phase 6 benchmark tasks (31-34) need scaffold
  - **Blocked By**: None

  **References**:
  - Evals pattern industry standard: ML benchmark runners
  - Existing test patterns: `backend/tests/` for test structure conventions

  **Acceptance Criteria**:

  **Unit Tests**:
  - [ ] `test_evals_runner_runs_registered_benchmark`
  - [ ] `test_benchmark_registry_register_and_list`
  - [ ] `test_benchmark_result_dataclass`
  - `pytest backend/evals/tests/ -xvs` → PASS

  **QA Scenario: EvalsRunner executes a mock benchmark**
    Tool: Bash (pytest)
    Preconditions: Mock benchmark registered with known expected score
    Steps:
      1. `pytest backend/evals/tests/test_runner.py::test_run_mock_benchmark -xvs`
    Expected Result: Test PASS — result.score matches expected, result.passed=True
    Failure Indicators: Fails or no result
    Evidence: `.sisyphus/evidence/task-6-evals-runner.txt`

  **Commit**: YES
  - Message: `feat(agi-evals): scaffold EvalsRunner, BenchmarkRegistry, and reports directory for Phase 6 benchmarks`
  - Files: `backend/evals/__init__.py`, `backend/evals/runner.py`, `backend/evals/registry.py`, `backend/evals/benchmarks/__init__.py`, `backend/evals/reports/__init__.py`, `backend/evals/tests/test_runner.py`
  - Pre-commit: `pytest backend/evals/tests/`

- [x] 7. Phase 1 integration — module wiring test

  **What to do**:
  - Create integration test `backend/tests/integration/test_phase_1_integration.py`
  - Scenario: SafetyMonitor approves trade → ProviderRegistry serves LLM call → ReasoningEngine produces result → KnowledgeGraph queries cross-domain → PluginManager discovers modules → EvalsRunner runs mock benchmark
  - Verifies all Phase 1 modules (Tasks 1-6) work together
  - All calls mocked where external dependencies needed (LLM, network), but real module imports
  - Test passes only if full chain completes without error
  - All structured logging verified: check logger captures phase_1_test entries

  **Must NOT do**:
  - Do NOT hit external APIs — mock all network calls
  - Do NOT modify Phase 1 task files — integration test is read-only consumer

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high` (orchestration across 6 modules)
  - **Skills**: `python`, `pytest`, `unittest.mock`
  - Reason: Complex orchestration chain requiring careful mocking

  **Parallelization**:
  - **Can Run In Parallel**: NO — depends on Tasks 1-6 being complete
  - **Blocks**: Phase Gate 1 (Task 8)
  - **Blocked By**: Tasks 1-6

  **References**:
  - Integration pattern: `backend/tests/integration/` for existing examples
  - Mocking: `unittest.mock` or `pytest-mock`

  **Acceptance Criteria**:

  **Integration Test**:
  - [ ] `test_phase_1_full_integration_chain`
  - `pytest backend/tests/integration/test_phase_1_integration.py -xvs` → PASS

  **Commit**: YES
  - Message: `test(phase1): integration test wiring SafetyMonitor, ProviderRegistry, ReasoningEngine, KnowledgeGraph, PluginManager, EvalsRunner`
  - Files: `backend/tests/integration/test_phase_1_integration.py`
  - Pre-commit: `pytest backend/tests/integration/test_phase_1_integration.py`

- [x] 8. Phase Gate 1 — Foundation sign-off

  **What to do**:
  - `backend/tests/integration/test_phase_gate_1.py` aggregates all Phase 1 tasks (1-7) tests
  - Fail if any unit or integration test from Phase 1 fails
  - Required CI check before Wave 2 begins
  - Report: print summary table of each task's test status

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `pytest`
  - Reason: Simple test aggregation

  **Parallelization**:
  - **Can Run In Parallel**: NO — after Tasks 1-7
  - **Blocks**: Wave 2 (Phase 1b + Phase 2)
  - **Blocked By**: Tasks 1-7

  **Acceptance Criteria**:
  - [ ] Phase Gate 1 suite PASS
  - `pytest backend/tests/integration/test_phase_gate_1.py -xvs` → PASS

  **Commit**: YES
  - Message: `test(gate): Phase Gate 1 — foundation (SafetyMonitor, ProviderRegistry, ReasoningEngine, KnowledgeGraph, PluginManager, Evals)`
  - Files: `backend/tests/integration/test_phase_gate_1.py`
  - Pre-commit: `pytest backend/tests/integration/test_phase_gate_1.py`

---

### Wave 2 — Phase 1b + Phase 2: Learning & Transfer

> Parallel wave: 6 tasks (Tasks 9-13). All proceed after Phase Gate 1.
> LearningSystem and TransferLearner are the bridge between foundation and autonomous generation.

- [x] 9. LearningSystem — create `backend/core/learning_system.py`

  **What to do**:
  - Create `LearningSystem` module:
    - `record_outcome(strategy_key, market_id, prediction, actual, pnl, timestamp)` — stores learning examples
    - `get_learning_examples(domain, n=100) → list[Example]` — retrieve recent examples for adaptation
    - `compute_calibration(domain) → CalibrationReport` — Brier score, calibration curve bins
    - `get_learning_stats() → dict` — examples per domain, average accuracy, recency distribution
    - Two modes: `offline` (batch from DB) and `online` (streaming via event bus)
    - Persistence: store examples in SQL via existing DB models or BotState.misc_data
    - Structured logging: `logger.bind(task="learning", domain=domain).info("outcome_recorded", prediction=p, actual=a)`
  - Unit tests: record outcomes, verify retrieval, test calibration computation

  **Must NOT do**:
  - Do NOT store PII or strategy details — only domain, prediction, actual outcome
  - Do NOT block on online mode — degrade gracefully to offline if event bus unavailable
  - Do NOT accumulate unlimited examples — max 10,000 per domain, oldest evicted

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high` (data management + statistics)
  - **Skills**: `python`, `pytest`, `sqlalchemy`, `statistics`
  - Reason: Learning system requires careful data management and calibration math

  **Parallelization**:
  - **Can Run In Parallel**: YES — after Phase Gate 1
  - **Parallel Group**: Wave 2
  - **Blocks**: Tasks 10 (TransferLearner needs learning examples)
  - **Blocked By**: Phase Gate 1 (Tasks 1-8); Task 3 (ReasoningEngine for calibration queries)

  **References**:
  - Existing DB models: `backend/models/` — follow same SQLAlchemy pattern
  - Calibration: Brier score computation in existing code (search for `brier`)
  - Example storage pattern: `backend/models/genome_registry.py:GenomePerformance`

  **Acceptance Criteria**:

  **Unit Tests**:
  - [ ] `test_learning_system_records_and_retrieves_outcomes`
  - [ ] `test_learning_system_computes_calibration`
  - [ ] `test_learning_system_enforces_example_limit`
  - [ ] `test_learning_system_offline_mode`
  - `pytest backend/core/tests/test_learning_system.py -xvs` → PASS

  **QA Scenario: LearningSystem records 1000 examples, calibration improves**
    Tool: Bash (pytest)
    Preconditions: 1000 synthetic examples for weather domain (600 correct, 400 wrong)
    Steps:
      1. `pytest backend/core/tests/test_learning_system.py::test_calibration_after_1000_examples -xvs`
    Expected Result: Test PASS — Brier score ~0.24 (well-calibrated for 60% accuracy)
    Failure Indicators: Brier >0.3 or error
    Evidence: `.sisyphus/evidence/task-9-calibration.txt`

  **Commit**: YES
  - Message: `feat(agi-learning): implement LearningSystem with offline/online modes, calibration, and example management`
  - Files: `backend/core/learning_system.py`, `backend/core/tests/test_learning_system.py`
  - Pre-commit: `pytest backend/core/tests/test_learning_system.py`

- [x] 10. TransferLearner — create `backend/core/transfer_learning.py`

  **What to do**:
  - Create `TransferLearner`:
    - `adapt_strategy(source_domain, target_domain, strategy_code, n_examples=5) → AdaptedStrategy`
    - Uses ProviderRegistry to few-shot prompt: given N examples of target domain, adapt strategy logic
    - Uses LearningSystem (Task 9) examples from target domain as few-shot material
    - Uses KnowledgeGraph cross-domain queries (Task 4) to find relevant relations between domains
    - Validates adapted strategy via CodeValidator (Task 15) if available, else syntax-check only
    - Returns `AdaptedStrategy(code, confidence, adaptation_notes)`
    - Logs each adaptation: `logger.bind(task="transfer", source=src, target=tgt).info(...)`
  - Unit tests: mock source strategy and target examples; verify adaptation produces valid code

  **Must NOT do**:
  - Do NOT run adapted strategies on live markets — only for sandbox evaluation
  - Do NOT use more than 5 examples for adaptation (few-shot constraint)
  - Do NOT hardcode LLM model — use ProviderRegistry default

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high` (cross-domain adaptation logic)
  - **Skills**: `python`, `pytest`, `llm-prompt-engineering`
  - Reason: Requires careful few-shot prompt construction + code adaptation

  **Parallelization**:
  - **Can Run In Parallel**: YES — after Tasks 4, 9
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 11 (MultiDomainOrchestrator uses TransferLearner)
  - **Blocked By**: Tasks 4, 9

  **References**:
  - Few-shot patterns: StrategyCodeGenerator in `backend/core/strategy_synthesizer.py`
  - KnowledgeGraph queries: `backend/core/knowledge_graph.py:query_by_cross_domain()` (Task 4)
  - LearningSystem: `backend/core/learning_system.py:get_learning_examples()` (Task 9)

  **Acceptance Criteria**:

  **Unit Tests**:
  - [ ] `test_transfer_learner_adapts_strategy_to_new_domain`
  - [ ] `test_transfer_learner_uses_few_shot_examples`
  - [ ] `test_transfer_learner_knowledge_graph_integration`
  - [ ] `test_transfer_learner_returns_valid_code`
  - `pytest backend/core/tests/test_transfer_learning.py -xvs` → PASS

  **QA Scenario: TransferLearner adapts crypto strategy to weather**
    Tool: Bash (pytest)
    Preconditions: Crypto strategy returns Python code; LearningSystem has 5 weather examples; KG has weather→crypto correlation 0.62
    Steps:
      1. `pytest backend/core/tests/test_transfer_learning.py::test_adapt_crypto_to_weather -xvs`
    Expected Result: Test PASS — adapted strategy passes syntax validation, confidence >0.5, notes mention KG correlation
    Failure Indicators: Invalid code or confidence <0.3
    Evidence: `.sisyphus/evidence/task-10-transfer-adapt.txt`

  **Commit**: YES
  - Message: `feat(agi-transfer): implement TransferLearner with few-shot cross-domain strategy adaptation`
  - Files: `backend/core/transfer_learning.py`, `backend/core/tests/test_transfer_learning.py`
  - Pre-commit: `pytest backend/core/tests/test_transfer_learning.py`

- [x] 11. MultiDomainOrchestrator — create `backend/core/multi_domain_orchestrator.py`

  **What to do**:
  - Create `MultiDomainOrchestrator`:
    - Maintains active domains: `list_domains() → list[str]`, `add_domain(name, config)`, `remove_domain(name)`
    - Routes incoming signals to domain-appropriate handlers
    - `orchestrate_adaptation(source_domain, target_domain) → AdaptedStrategy` — calls TransferLearner (Task 10)
    - `get_domain_performance(domain) → dict` — aggregates LearningSystem stats per domain
    - Integration: MarketUniverseScanner reports new markets; Orchestrator determines if new domain needed
    - Logs all routing: `logger.bind(task="orchestrator", domain=d).info("signal_routed")`
  - Unit tests: mock two domains; verify signal routing; verify cross-domain adaptation triggered

  **Must NOT do**:
  - Do NOT auto-add domains without SafetyMonitor approval
  - Do NOT route signals to domains below minimum confidence threshold
  - Do NOT override existing strategy lifecycle — Orchestrator adds new capabilities

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high` (multi-domain orchestration)
  - **Skills**: `python`, `pytest`, `event-routing`
  - Reason: Domain lifecycle management and routing logic

  **Parallelization**:
  - **Can Run In Parallel**: After Tasks 9, 10
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 12 (Phase 2 integration)
  - **Blocked By**: Tasks 9, 10

  **References**:
  - Market scanner: `backend/data/market_universe.py:MarketUniverseScanner` — domain discovery
  - LearningSystem: `backend/core/learning_system.py` (Task 9)
  - TransferLearner: `backend/core/transfer_learning.py` (Task 10)

  **Acceptance Criteria**:

  **Unit Tests**:
  - [ ] `test_multi_domain_orchestrator_routes_signals_by_domain`
  - [ ] `test_multi_domain_orchestrator_triggers_cross_domain_adaptation`
  - [ ] `test_multi_domain_orchestrator_aggregates_domain_performance`
  - `pytest` → PASS

  **QA Scenario: Orchestrator adapts signal from crypto to weather domain**
    Tool: Bash (pytest)
    Preconditions: Crypto domain active with signals; weather domain added with 5 learning examples; TransferLearner returns valid strategy
    Steps:
      1. `pytest backend/core/tests/test_multi_domain_orchestrator.py::test_orchestrate_cross_domain_signal -xvs`
    Expected Result: Test PASS — signal routed, TransferLearner called, adapted strategy returned
    Failure Indicators: Signal dropped or adaptation not triggered
    Evidence: `.sisyphus/evidence/task-11-orchestrate-adapt.txt`

  **Commit**: YES
  - Message: `feat(agi-orchestrator): implement MultiDomainOrchestrator for cross-domain signal routing and strategy adaptation`
  - Files: `backend/core/multi_domain_orchestrator.py`, `backend/core/tests/test_multi_domain_orchestrator.py`
  - Pre-commit: `pytest backend/core/tests/test_multi_domain_orchestrator.py`

- [x] 12. Phase 2 integration — learning pipeline test

  **What to do**:
  - Create `backend/tests/integration/test_phase_2_integration.py`
  - Scenario: LearningSystem records 100 outcomes → TransferLearner adapts crypto strategy to weather using KG + examples → MultiDomainOrchestrator routes new weather signal → adapted strategy runs
  - Full Phase 2 chain: all real imports, mocked external calls (LLM)
  - Test passes only if all components execute without error

  **Must NOT do**:
  - Do NOT modify Phase 2 task files
  - Do NOT exceed 5 examples in adaptation prompt

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: `python`, `pytest`, `unittest.mock`
  - Reason: Complex 3-module orchestration

  **Parallelization**:
  - **Can Run In Parallel**: NO — after Tasks 9-11
  - **Blocks**: Phase Gate 2 (Task 13)
  - **Blocked By**: Tasks 9, 10, 11

  **References**:
  - Phase 1 integration pattern: `backend/tests/integration/test_phase_1_integration.py`

  **Acceptance Criteria**:
  - [ ] `test_phase_2_learning_pipeline_completes`
  - `pytest backend/tests/integration/test_phase_2_integration.py -xvs` → PASS

  **Commit**: YES
  - Message: `test(phase2): integration test for LearningSystem → TransferLearner → MultiDomainOrchestrator pipeline`
  - Files: `backend/tests/integration/test_phase_2_integration.py`
  - Pre-commit: `pytest backend/tests/integration/test_phase_2_integration.py`

- [x] 13. Phase Gate 2 — Learning & Transfer sign-off

  **What to do**:
  - `backend/tests/integration/test_phase_gate_2.py` aggregates all Phase 1b + Phase 2 tests (9-12)
  - Gate 1 must also be green (Phase 1 foundation still valid)
  - Fail if any test fails
  - Required CI check before Wave 3 (Phase 3: Autonomous Strategy Generation)

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `pytest`
  - Reason: Simple test aggregation

  **Parallelization**:
  - **Can Run In Parallel**: NO — after Tasks 9-12
  - **Blocks**: Wave 3 start
  - **Blocked By**: Tasks 9-12, Phase Gate 1

  **Acceptance Criteria**:
  - [ ] Phase Gate 2 suite PASS
  - [ ] Phase Gate 1 still green
  - `pytest backend/tests/integration/test_phase_gate_2.py -xvs` → PASS

  **Commit**: YES
  - Message: `test(gate): Phase Gate 2 — learning and transfer (LearningSystem, TransferLearner, MultiDomainOrchestrator)`
  - Files: `backend/tests/integration/test_phase_gate_2.py`
  - Pre-commit: `pytest backend/tests/integration/test_phase_gate_2.py`

---

### Wave 3 — Phase 3: Autonomous Strategy Generation

> Parallel wave: 6 tasks (Tasks 14–19). All can proceed concurrently after Phase Gate 2 passes.
> Critical dependency: All LLM calls route through ProviderRegistry (Phase 1 Task 2).

- [x] 14. StrategyCodeGenerator augmentation — enhance `backend/core/strategy_synthesizer.py`

  **What to do**:
  - Current synthesizer generates strategy code; now make it production-grade:
    - Add `generate_strategy_with_sandbox_test(spec) → (code, test_report)` method:
      - Calls `ProviderRegistry.get().complete(prompt=spec)` to generate code
      - Writes generated code to temp dir under `backend/tmp/generated/`
      - Invokes `CodeValidator.validate(code_path)` (Task 15)
      - Executes `ExecutionSandbox.run_mock_trades(code_path, market_fixtures)` (Task 16)
      - Returns success + performance summary or failure + diagnostics
    - Inject templates from `backend/application/strategy/genome_strategy.py` chromosome patterns (reuse entry/exit logic snippets)
    - Accept context: `ReasoningContext(domain)` and `KnowledgeGraph` market ID lookup
    - Log every generation attempt with `logger.bind(task="strategy_synthesizer").info(...)`
  - Unit tests: mock ProviderRegistry, assert validator and sandbox called in sequence

  **Must NOT do**:
  - Do NOT generate strategies that directly trade live markets without sandbox
  - Do NOT use direct LLM imports — go through ProviderRegistry only
  - Do NOT skip validation even for synthetic strategies

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: `python`, `pytest`, `fastapi` (if endpoint), `llm-prompt-engineering`
  - Reason: Integrates LLM generation, AST validation, sandbox execution — complex orchestration

  **Parallelization**:
  - **Can Run In Parallel**: Partially — core generator method independent; integration tests wait for Tasks 15–16
  - **Parallel Group**: Wave 3
  - **Blocks**: None (other phases call this later)
  - **Blocked By**: Task 2 (ProviderRegistry must exist), Task 15, Task 16

  **References**:
  - Existing: `backend/core/strategy_synthesizer.py:StrategySynthesizer.generate()` — current implementation
  - Templates: `backend/application/strategy/genome_strategy.py:CognitionChromosome.render()` — template patterns
  - Provider: `backend/ai/provider_registry.py:ProviderRegistry` — LLM calls go here
  - Test pattern: `backend/tests/unit/test_strategy_synthesizer.py` (if missing, create)

  **Acceptance Criteria**:

  **Unit Tests**:
  - [ ] `test_generate_strategy_with_sandbox_test_calls_validator_and_sandbox`
  - [ ] `test_generate_strategy_uses_provider_registry`
  - [ ] `test_generate_strategy_fails_when_sandbox_returns_negative`
  - [ ] `test_generate_strategy_injects_genome_templates`
  - `pytest` → PASS

  **QA Scenario 1: Generated strategy passes sandbox and returns success**
    Tool: Bash (pytest)
    Preconditions: Mock ProviderRegistry returns valid Python code; sandbox fixture with price data; CodeValidator stubbed to PASS
    Steps:
      1. `cd /home/openclaw/projects/1ai-poly-trader && /home/linuxbrew/.linuxbrew/bin/python3 -m pytest backend/tests/unit/test_strategy_synthesizer.py::test_generate_strategy_with_sandbox_test_success -xvs`
    Expected Result: Test PASS — generated strategy executes mock trades, validator passes, report indicates success
    Failure Indicators: FAIL, sandbox not invoked, validator skipped
    Evidence: `.sisyphus/evidence/task-14-gen-success.txt`

  **QA Scenario 2: Generated strategy fails validation or sandbox**
    Tool: Bash (pytest)
    Preconditions: ProviderRegistry returns code with syntax error; sandbox raises exception
    Steps:
      1. `pytest backend/tests/unit/test_strategy_synthesizer.py::test_generate_strategy_with_sandbox_test_failure -xvs`
    Expected Result: Test PASS — generator returns failure report, does not raise
    Failure Indicators: Test FAIL or unhandled exception
    Evidence: `.sisyphus/evidence/task-14-gen-failure.txt`

  **Commit**: YES
  - Message: `feat(agi-gen): augment StrategyCodeGenerator with sandbox-test loop and provider routing`
  - Files: `backend/core/strategy_synthesizer.py`, `backend/tests/unit/test_strategy_synthesizer.py`
  - Pre-commit: `pytest backend/tests/unit/test_strategy_synthesizer.py`

- [x] 15. CodeValidator — AST-based security and style validator (`backend/agi/code_validator.py`)

  **What to do**:
  - Create `backend/agi/code_validator.py`:
    - `validate(code_path: str) -> ValidationResult`:
      - AST parse with `ast.parse()` — reject syntax errors
      - Walk AST: forbid `eval()`, `exec()`, `__import__`, `subprocess`, `open()` (except read-only within sandbox dir)
      - Enforce style: function names snake_case, no bare `except:`, max cyclomatic complexity 10 (use `radon` if available, else simple heuristic)
      - Check for unsafe imports (`os`, `sys`, `requests` require explicit whitelist)
      - Return `is_valid: bool`, `issues: list[str]`, `severity: "error"/"warning"`
  - Integrate into StrategyCodeGenerator (Task 14) — generator must not accept code that fails validation
  - Unit tests: sample malicious code snippets that should be rejected; safe examples that pass

  **Must NOT do**:
  - Do NOT allow strategies to import arbitrary libraries — whitelist only: `numpy`, `pandas`, `math`, `statistics`, `datetime`, `typing`
  - Do NOT permit network calls or file writes outside sandbox temp dir
  - Do NOT let validator crash on malformed code — catch all exceptions and mark invalid

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high` (security-sensitive)
  - **Skills**: `python`, `ast`, `pytest`, `security`
  - Reason: AST analysis + security policy enforcement

  **Parallelization**:
  - **Can Run In Parallel**: YES — can implement alongside Task 14; Task 14 depends on this
  - **Parallel Group**: Wave 3
  - **Blocks**: Task 14 (generator waits for validator)
  - **Blocked By**: None

  **References**:
  - AST patterns: `ast` module docs; `flake8` plugin source for inspiration
  - Existing security: Look for similar checks in `backend/agi/extended_sandbox.py` (sandbox restrictions)
  - Test examples: search `backend/tests/` for security tests

  **Acceptance Criteria**:

  **Unit Tests**:
  - [ ] `test_validator_accepts_clean_strategy_code`
  - [ ] `test_validator_rejects_eval_and_exec`
  - [ ] `test_validator_rejects_unauthorized_imports`
  - [ ] `test_validator_checks_cyclomatic_complexity`
  - `pytest` → PASS

  **QA Scenario: Validator blocks malicious code pattern**
    Tool: Bash (python3 -c)
    Preconditions: Save malicious snippet to `backend/tmp/malicious.py` with `eval(__import__('os').system('echo pwned'))`
    Steps:
      1. `cd /home/openclaw/projects/1ai-poly-trader && python3 -c "from agi.code_validator import CodeValidator; v = CodeValidator(); r = v.validate('backend/tmp/malicious.py'); print(r.is_valid)"`
    Expected Result: prints False
    Failure Indicators: True or exception
    Evidence: `.sisyphus/evidence/task-15-block-malicious.txt`

  **Commit**: YES
  - Message: `feat(agi-security): implement CodeValidator AST-based security and style checker`
  - Files: `backend/agi/code_validator.py`, `backend/tests/unit/test_code_validator.py`
  - Pre-commit: `pytest backend/tests/unit/test_code_validator.py`

- [x] 16. ExecutionSandbox hardening — strengthen `backend/agi/extended_sandbox.py`

  **What to do**:
  - Review existing sandbox: it likely runs strategies in isolated env; now harden for production:
    - Resource limits: CPU time 1s max, memory 200 MB max (via `resource.setrlimit` in subprocess)
    - Filesystem: writable only within temp sandbox dir; `/etc`, `/usr` read-only
    - Network: block all outbound connections (use seccomp if available, else deny via iptables in container)
    - Time: enforce hard timeout 2s per trade simulation step; kill if exceeded
    - Result: capture stdout/stderr, exit code, resource usage
    - Return structured `SandboxResult(success, output, cpu_ms, mem_kb, killed)`
  - Add comprehensive unit tests that attempt escapes (file open outside dir, infinite loop, large allocation)
  - Integration: StrategyCodeGenerator (Task 14) calls sandbox and aborts on sandbox failure

  **Must NOT do**:
  - Do NOT run untrusted strategies in main process — always subprocess
  - Do NOT allow strategies to modify environment variables (clear env in subprocess)
  - Do NOT permit persistent state across sandbox runs — fresh temp dir each time

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high` (security-critical)
  - **Skills**: `python`, `subprocess`, `resource-limits`, `pytest`
  - Reason: Hardened sandbox required before any autonomous code runs

  **Parallelization**:
  - **Can Run In Parallel**: YES — with Task 15
  - **Parallel Group**: Wave 3
  - **Blocks**: Task 14 (generator needs sandbox)
  - **Blocked By**: None

  **References**:
  - Existing sandbox: `backend/agi/extended_sandbox.py` — current implementation
  - Resource limits: `resource` module docs; Docker resource constraints if containerized
  - Security: `seccomp` py package; `subprocess` with `--sandbox` flags if using `bubblewrap`

  **Acceptance Criteria**:

  **Unit Tests**:
  - [ ] `test_sandbox_enforces_cpu_time_limit`
  - [ ] `test_sandbox_enforces_memory_limit`
  - [ ] `test_sandbox_blocks_network_access`
  - [ ] `test_sandbox_isolates_filesystem_to_temp_dir`
  - [ ] `test_sandbox_kills_process_exceeding_timeout`
  - `pytest` → PASS

  **QA Scenario: Sandbox kills infinite loop**
    Tool: Bash (python3 -c)
    Preconditions: Create script `while True: pass` in temp dir
    Steps:
      1. `python3 -c "from agi.extended_sandbox import ExecutionSandbox; s = ExecutionSandbox(); r = s.run('while True: pass', timeout=1); print(r.killed)"`
    Expected Result: prints True (killed due to timeout)
    Failure Indicators: False or hang
    Evidence: `.sisyphus/evidence/task-16-sandbox-kill.txt`

  **Commit**: YES
  - Message: `feat(agi-sandbox): harden ExecutionSandbox with resource limits, filesystem isolation, network block`
  - Files: `backend/agi/extended_sandbox.py`, `backend/tests/unit/test_extended_sandbox.py`
  - Pre-commit: `pytest backend/tests/unit/test_extended_sandbox.py`

- [x] 17. HypothesisTester — A/B testing framework for autonomous strategies (`backend/agi/hypothesis_tester.py`)

  **What to do**:
  - Create `backend/agi/hypothesis_tester.py`:
    - `HypothesisTester` class: `run_ab_test(strategy_a_path, strategy_b_path, market_fixture, period) → TestResult`
    - Run both strategies in parallel in sandbox against same market data snapshot
    - Metrics: Sharpe ratio, win rate, max drawdown, total P&L (simulated)
    - Statistical test: Welch's t-test on per-trade returns; p-value <0.05 means significant difference
    - Decision: Recommend superior strategy; also detect regression (B worse than A)
    - Tie-in to LearningSystem (Phase 2): after improvement proposal, HypothesisTester validates before promotion
  - Unit tests: mock two simple strategies, verify tester picks known better one

  **Must NOT do**:
  - Do NOT run tests against live markets — only use historical fixtures or synthetic data
  - Do NOT promote strategy based on <30 trades sample — enforce minimum sample size
  - Do NOT let test allocate more than 1% of simulated bankroll per run

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high` (statistics + integration)
  - **Skills**: `python`, `statistics`, `pytest`, `sandbox`
  - Reason: Needs careful statistical rigor and sandbox orchestration

  **Parallelization**:
  - **Can Run In Parallel**: YES — once Tasks 14–16 ready
  - **Parallel Group**: Wave 3
  - **Blocks**: None (LearningSystem uses it in Phase 2, but Phase 2 already done; Phase 3 integration uses it)
  - **Blocked By**: Tasks 14, 15, 16

  **References**:
  - Statistics: `scipy.stats.ttest_ind` — Welch's t-test
  - Existing metrics: `backend/core/performance_attributor.py` — P&L attribution logic
  - Test fixtures: `backend/tests/fixtures/market_data.py` — sample market data

  **Acceptance Criteria**:

  **Unit Tests**:
  - [ ] `test_hypothesis_tester_identifies_superior_strategy`
  - [ ] `test_hypothesis_tester_detects_regression`
  - [ ] `test_hypothesis_tester_enforces_minimum_trades`
  - [ ] `test_hypothesis_tester_returns_statistically_significant_result`
  - `pytest` → PASS

  **QA Scenario: A/B test correctly picks higher Sharpe strategy**
    Tool: Bash (pytest)
    Preconditions: Strategy A (Sharpe 0.8), Strategy B (Sharpe 1.4), same market fixture
    Steps:
      1. `pytest backend/tests/unit/test_hypothesis_tester.py::test_ab_test_selects_better -xvs`
    Expected Result: Test PASS — tester recommends B
    Failure Indicators: FAIL, or recommendation A
    Evidence: `.sisyphus/evidence/task-17-ab-test-selects-b.txt`

  **Commit**: YES
  - Message: `feat(agi-eval): implement HypothesisTester A/B testing framework with statistical significance`
  - Files: `backend/agi/hypothesis_tester.py`, `backend/tests/unit/test_hypothesis_tester.py`
  - Pre-commit: `pytest backend/tests/unit/test_hypothesis_tester.py`

- [x] 18. Phase 3 integration — Autonomous generation subsystem

  **What to do**:
  - Integration test `backend/tests/integration/test_phase3_autonomous_generation.py`
  - Scenario: AGI identifies opportunity in new domain (e.g., weather → crypto volatility) → StrategyCodeGenerator produces candidate strategy → CodeValidator passes → ExecutionSandbox runs mock trades → HypothesisTester A/B against baseline → SafetyMonitor gates → if PASS, strategy queued for Shadow promotion
  - Full path: end-to-end orchestration using FastAPI `/agi/generate-and-test` endpoint (new) or direct module calls
  - Verify all events logged with proper severity: generation, validation, sandbox, hypothesis, safety decision
  - Test passes only if full chain completes with "approved_for_shadow" outcome

  **Must NOT do**:
  - Do NOT hit external LLM — mock ProviderRegistry to return deterministic code
  - Do NOT use live market data — use provided fixtures

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: `python`, `pytest`, `fastapi-testclient`
  - Reason: Long orchestration chain across 5+ components

  **Parallelization**:
  - **Can Run In Parallel**: NO — depends on Tasks 14, 15, 16, 17, and Phase 2 (TransferLearner provides domain inspiration)
  - **Blocks**: Wave 4 start
  - **Blocked By**: Tasks 14, 15, 16, 17, Phase Gate 2

  **References**:
  - Integration pattern: `backend/tests/integration/` existing files
  - API endpoint: `backend/api/agi.py` (will be created by Task 14 as part of generator endpoint)
  - Events: loguru structured logging pattern

  **Acceptance Criteria**:

  **Integration Test**:
  - [ ] `test_phase3_full_generation_pipeline_approved_for_shadow`
  - [ ] `test_phase3_ab_test_identifies_improvement`
  - [ ] `test_phase3_safety_gate_enforced_before_shadow`
  - `pytest backend/tests/integration/test_phase3_autonomous_generation.py -xvs` → PASS

  **Commit**: YES
  - Message: `test(phase3): add integration test for autonomous generation → validation → sandbox → hypothesis → safety pipeline`
  - Files: `backend/tests/integration/test_phase3_autonomous_generation.py`
  - Pre-commit: `pytest backend/tests/integration/test_phase3_autonomous_generation.py`

- [x] 19. Phase Gate 3 Review — Sign-off before Wave 4

  **What to do**:
  - `backend/tests/integration/test_phase_gate_3.py` aggregates all Phase 3 tasks (14–18)
  - Fail if any unit or integration test from Phase 3 fails
  - CI required check before Wave 4 merges

  **Recommendation**: `deep` agent; `pytest`

  **Parallelization**: NO — after Tasks 14–18
  - **Blocks**: Wave 4
  - **Blocked By**: Tasks 14, 15, 16, 17, 18

  **Acceptance**:
  - [ ] Phase Gate 3 suite PASS
  - `pytest test_phase_gate_3.py -xvs` → PASS

  **Commit**: YES
  - Message: `test(gate): Phase Gate 3 — autonomous generation`
  - Files: `backend/tests/integration/test_phase_gate_3.py`
  - Pre-commit: `pytest backend/tests/integration/test_phase_gate_3.py`

---

### Wave 4 — Phase 4: Recursive Self-Modification

> Self-improvement of AGI's own reasoning and code. High risk — requires extensive safety reviews.

- [x] 21. AutoArchitectureSearch (NAS) — `backend/ai/architecture_search.py`

  **What to do**:
  - Implement Neural Architecture Search for strategy neural components (e.g., price prediction head, sentiment encoder):
    - Search space: layer types (conv1d, lstm, attention), widths, depths, activation functions
    - Controller: lightweight LLM (via ProviderRegistry) proposes architectures in text (JSON spec)
    - Evaluator: trains each candidate for 5 epochs on recent market data (`backend/data/`), computes validation Sharpe
    - Budget: stop after `NAS_MAX_GPU_HOURS_PER_MONTH` GPU-hours reached or 64 candidates evaluated
    - Use `ExecutionSandbox` for evaluation isolation; metrics logged to `GenomeRegistry` as `ArchitectureTrial`
    - Top-K architectures saved to `backend/ai/architectures/` as PyTorch model definitions
  - Respect `NAS_MAX_GPU_HOURS_PER_MONTH` from BotState.misc_data (configurable via UI)
  - All LLM calls (controller) via ProviderRegistry; all training uses local GPU/Runpod provider

  **Must NOT do**:
  - Do NOT modify live strategy models without SafetyMonitor approval
  - Do NOT exceed monthly GPU budget — hard stop when budget exhausted
  - Do NOT deploy architectures that haven't completed at least 5-epoch validation

  **Recommended Agent Profile**:
  - **Category**: `ultrabrain`
  - **Skills**: `python`, `pytorch`, `pytest`, `gpu-compute`
  - Reason: Research-level NAS + budget constraints + safety gating

  **Parallelization**:
  - **Can Run In Parallel**: YES — independent of Wave 3 but depends on ProviderRegistry (Task 2)
  - **Parallel Group**: Wave 4
  - **Blocks**: Task 23 (SelfModifyingReasoningEngine may use discovered architectures)
  - **Blocked By**: Task 2 (ProviderRegistry), Task 16 (Sandbox for evaluation)

  **References**:
  - NAS literature: `backend/ai/` for any existing search attempts
  - GPU billing: track via provider cost APIs (Runpod billing endpoint)
  - Sandbox: `backend/agi/extended_sandbox.py` — run training inside sandbox
  - Metrics: `backend/core/performance_attributor.py` — Sharpe calculation reuse

  **Acceptance Criteria**:

  **Unit Tests** (lightweight, mocked training):
  - [ ] `test_nas_controller_proposes_valid_json_spec`
  - [ ] `test_nas_respects_gpu_budget_limit`
  - [ ] `test_nas_logs_trial_results_to_genome_registry`
  - `pytest` → PASS

  **Integration Test** (runs 2 short training cycles):
  - [ ] `test_nas_evaluates_at_least_one_candidate`
  - [ ] `test_nas_selects_best_candidate_within_budget`
  - `pytest backend/ai/tests/test_architecture_search.py -xvs` → PASS

  **QA Scenario: NAS finds better architecture within budget**
    Tool: Bash (pytest)
    Preconditions: GPU budget 0.5 hr; mock training to take 0.1 hr each; 3 candidates
    Steps:
      1. `pytest backend/ai/tests/test_architecture_search.py::test_nas_finds_improvement -xvs`
    Expected Result: Test PASS — NAS completes, logs top architecture, does not exceed budget
    Failure Indicators: Budget exceeded, or no candidate evaluated
    Evidence: `.sisyphus/evidence/task-21-nas-finds-improvement.txt`

  **Commit**: YES
  - Message: `feat(agi-nas): implement AutoArchitectureSearch with provider-controlled LLM controller and GPU budget`
  - Files: `backend/ai/architecture_search.py`, `backend/ai/tests/test_architecture_search.py`, `backend/ai/architectures/__init__.py`
  - Pre-commit: `pytest backend/ai/tests/`

- [x] 22. CodeRefactoringAgent — autonomous code improvement (`backend/agi/code_refactorer.py`)

  **What to do**:
  - Create `CodeRefactoringAgent`:
    - Input: target module path + improvement goal (e.g., "reduce cyclomatic complexity", "add type hints", "improve naming")
    - Uses ProviderRegistry LLM to propose refactoring diff (ask for unified diff format)
    - Applies diff via `patch` utility after CodeValidator re-check
    - Runs existing unit tests for that module; if tests fail, automatically rolls back via version control (git revert) or file backup
    - Requires SafetyMonitor approval for any file under `backend/core/` or `backend/strategies/`
    - Logs all proposals, approvals, rollbacks to `BotState.misc_data['refactor_history']`
  - Unit tests: mock LLM diff, verify apply/rollback logic, test SafetyMonitor gate

  **Must NOT do**:
  - Do NOT refactor files outside configured allowlist (exclude `backend/strategies/` alpha code without explicit human approval)
  - Do NOT trust LLM diff blindly — always validate AST after patch
  - Do NOT commit without pre-existing tests passing

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high` (code mutation is risky)
  - **Skills**: `python`, `git`, `pytest`, `diff`, `ast`
  - Reason: Autonomous code changes require safety + test gate

  **Parallelization**:
  - **Can Run In Parallel**: YES — after ProviderRegistry
  - **Parallel Group**: Wave 4
  - **Blocks**: Task 23 (SelfModifyingReasoningEngine uses refactor agent)
  - **Blocked By**: Task 15 (CodeValidator), SafetyMonitor (Task 1)

  **References**:
  - Diff apply: `patch` command or `unidiff` Python lib
  - Git rollback: `subprocess.run(["git","checkout","--",path])`
  - Validation: reuse CodeValidator from Task 15
  - Safety: `backend/core/safety.py` — approval gate

  **Acceptance Criteria**:

  **Unit Tests**:
  - [ ] `test_refactor_agent_proposes_diff_via_llm`
  - [ ] `test_refactor_agent_applies_and_validates`
  - [ ] `test_refactor_agent_rolls_back_on_test_failure`
  - [ ] `test_refactor_agent_requires_safety_approval_for_core_files`
  - `pytest` → PASS

  **QA Scenario: Agent successfully refactors and tests pass**
    Tool: Bash (pytest)
    Preconditions: Temp file with complex function; mock LLM returns simplified version; unit tests exist and pass post-refactor
    Steps:
      1. `pytest backend/agi/tests/test_code_refactorer.py::test_successful_refactor -xvs`
    Expected Result: Test PASS — diff applied, tests green, changes committed to temp repo
    Failure Indicators: Rollback triggered, or tests fail
    Evidence: `.sisyphus/evidence/task-22-refactor-success.txt`

  **Commit**: YES
  - Message: `feat(agi-selfmod): implement CodeRefactoringAgent with safety-gated LLM diff and test-gated rollout`
  - Files: `backend/agi/code_refactorer.py`, `backend/agi/tests/test_code_refactorer.py`
  - Pre-commit: `pytest backend/agi/tests/`

- [x] 23. SelfModifyingReasoningEngine — ReasoningEngine can propose and apply self-modifications (`backend/core/reasoning_engine.py`)

  **What to do**:
  - Enhance ReasoningEngine (Task 3) with self-mod capability:
    - Add `suggest_improvement(own_code=True) → ModificationProposal` using ProviderRegistry
    - ModificationProposal includes: target file, diff, risk_score (0–1), rationale
    - High-risk modifications (risk_score >0.7) require explicit SafetyMonitor human-approval flag
    - Low-risk modifications automatically routed through CodeRefactoringAgent (Task 22) then validated via unit tests
    - Maintain `self_mod_history` log in BotState.misc_data
    - Only modifies files in `backend/core/reasoning_engine.py` and `backend/ai/` (not strategies)
  - Unit tests: mock safe improvement (docstring addition), verify low-risk auto-apply; mock risky change, verify gate

  **Must NOT do**:
  - Do NOT allow self-mod of trading strategy code or risk engine
  - Do NOT apply modifications that reduce test coverage below 80%
  - Do NOT permit multiple concurrent modifications — serialize

  **Recommended Agent Profile**:
  - **Category**: `ultrabrain`
  - **Skills**: `python`, `ast`, `pytest`, `self-mod`
  - Reason: Self-modifying code requires extreme caution

  **Parallelization**:
  - **Can Run In Parallel**: After Task 22 (CodeRefactoringAgent) and Task 2 (ProviderRegistry)
  - **Parallel Group**: Wave 4
  - **Blocks**: None (self-mod is orthogonal to other Phase 4 tasks)
  - **Blocked By**: Task 22, Task 2

  **References**:
  - Reasoning engine: `backend/core/reasoning_engine.py` (Task 3)
  - AST utilities: `ast` module; `oh-my-claudecode_t_lsp_diagnostics` for self-check patterns
  - Safety gate: `backend/core/safety.py:RiskMonitor`

  **Acceptance Criteria**:

  **Unit Tests**:
  - [ ] `test_suggest_improvement_returns_modification_proposal`
  - [ ] `test_low_risk_modification_auto_applied_via_refactor_agent`
  - [ ] `test_high_risk_modification_requires_safety_approval`
  - [ ] `test_self_mod_serialized_no_concurrent_mods`
  - `pytest` → PASS

  **QA Scenario: Low-risk self-mod auto-applied and tests pass**
    Tool: Bash (pytest)
    Preconditions: ReasoningEngine running with mock ProviderRegistry returning docstring addition; CodeRefactorAgent stubbed to apply; unit tests for ReasoningEngine exist
    Steps:
      1. `pytest backend/core/tests/test_reasoning_engine_self_mod.py::test_low_risk_auto_apply -xvs`
    Expected Result: Test PASS — modification proposed, risk_score <0.7, refactor agent applies, tests green, history logged
    Failure Indicators: Proposal rejected, rollback triggered, tests fail
    Evidence: `.sisyphus/evidence/task-23-self-mod-success.txt`

  **Commit**: YES
    - Message: `feat(agi-selfmod): ReasoningEngine self-modification with risk-gated SafetyMonitor approval`
    - Files: `backend/core/reasoning_engine.py`, `backend/core/tests/test_reasoning_engine_self_mod.py`
    - Pre-commit: `pytest backend/core/tests/test_reasoning_engine_self_mod.py`

- [x] 24. Phase Gate 4 Review — Autonomous self-modification sign-off

  **What to do**:
  - `backend/tests/integration/test_phase_gate_4.py` aggregates Tasks 21–23
  - Fail if any test fails; CI required before Wave 5

  **Recommendation**: `deep` agent; `pytest`

  **Parallelization**: NO — after Tasks 21–23
    - **Blocks**: Wave 5

  **Acceptance**:
  - [ ] Phase Gate 4 suite PASS
  - `pytest test_phase_gate_4.py -xvs` → PASS

  **Commit**: YES
    - Message: `test(gate): Phase Gate 4 — recursive self-modification`
    - Files: `backend/tests/integration/test_phase_gate_4.py`
    - Pre-commit: `pytest backend/tests/integration/test_phase_gate_4.py`

---

### Wave 5 — Phase 5: Unbounded Autonomy

> Goal formation, multi-objective planning, opportunity discovery — highest agentic capability layer.
> Depends on all previous phases (safety, knowledge, generation, self-mod all operational).

- [x] 25. CoreValues alignment — value system and constitutional guard (`backend/agi/core_values.py`)

  **What to do**:
  - Create `CoreValues` module:
    - Define value dimensions: Safety (no blow-up), Honesty (no deception), User Intent Alignment (follow configured goals), Resource Stewardship (no waste), Compliance ( jurisdictional respect ), Transparency (log all decisions)
    - `ValueScorer.score(action_context) → float [0–1]` per dimension
    - `ValueAlignmentGate.check(proposal) → bool` — blocks actions scoring <0.6 on any dimension
    - Thresholds configurable via UI → persisted in `BotState.misc_data['core_values_thresholds']`
    - All high-level AGI proposals (new goals, self-mod, strategy generation) must pass CoreValues check before execution
  - Unit tests: sample proposals (safe/dangerous/honest/deceptive) verify scorer and gate

  **Must NOT do**:
  - Do NOT make values hardcoded — UI must override defaults
  - Do NOT allow value system to be hijacked — only admin role can edit thresholds
  - Do NOT block all exploration — thresholds tuned for <0.6 reject, not <0.9

  **Recommended Agent Profile**:
  - **Category**: `deep` (ethics + system design)
  - **Skills**: `python`, `pytest`, `fastapi`
  - Reason: Constitutional AI layer requires careful design + testing edge cases

  **Parallelization**:
  - **Can Run In Parallel**: YES — after ProviderRegistry and SafetyMonitor exist (independent axis)
  - **Parallel Group**: Wave 5
  - **Blocks**: Tasks 26, 27, 28 (use CoreValues gate)
  - **Blocked By**: Task 1 (SafetyMonitor baseline), Task 2 (ProviderRegistry for optional LLM scoring)

  **References**:
  - Constitutional AI: Anthropic research; `backend/agi/` for any existing guardrails
  - Config pattern: `backend/core/bankroll_allocator.py` reads from BotState.misc_data — follow same pattern
  - UI config: How settings persist from React → backend

  **Acceptance Criteria**:

  **Unit Tests**:
  - [ ] `test_core_values_scorer_produces_coherent_scores`
  - [ ] `test_value_alignment_gate_blocks_low_safety`
  - [ ] `test_value_alignment_allows_high_integrity_proposals`
  - [ ] `test_thresholds_loaded_from_botstate_misc_data`
  - `pytest` → PASS

  **QA Scenario: Gate blocks deceptive proposal**
    Tool: Bash (pytest)
    Preconditions: Proposal with honesty_score=0.3; thresholds honesty_min=0.6
    Steps:
      1. `pytest backend/agi/tests/test_core_values.py::test_gate_blocks_deceptive -xvs`
    Expected Result: Test PASS — gate rejects proposal, logs reason
    Failure Indicators: Proposal accepted
    Evidence: `.sisyphus/evidence/task-25-gate-blocks-deceptive.txt`

  **Commit**: YES
    - Message: `feat(agi-values): implement CoreValues alignment with UI-configurable thresholds`
    - Files: `backend/agi/core_values.py`, `backend/agi/tests/test_core_values.py`
    - Pre-commit: `pytest backend/agi/tests/test_core_values.py`

- [x] 26. OpportunityFinder — scans all domains for actionable edges (`backend/agi/opportunity_finder.py`)

  **What to do**:
  - Create `OpportunityFinder`:
    - Inputs: KnowledgeGraph (Task 4), MarketUniverseScanner (existing), external data feeds (weather, economic releases)
    - `find_opportunities() → list[Opportunity]` — each has: domain (crypto/weather/sports), market_id, confidence, required_capability (strategy type), estimated_edge_bps
    - Scoring: cross-domain correlation strength via KnowledgeGraph + novelty via market data deviation from baseline
    - Filters: SafetyMonitor risk tier (reject >AGGRESSIVE unless explicit override), CoreValues compliance (Task 25)
    - Output: prioritized list sent to AutonomousGoalGenerator (Task 27)
  - Unit tests: mock multi-domain datasets; verify known opportunity detected; verify risky opportunity filtered

  **Must NOT do**:
  - Do NOT propose opportunities requiring capabilities not in GenomeRegistry (no ability → no goal)
  - Do NOT flood with low-confidence opportunities — minimum 0.55 confidence threshold
  - Do NOT ignore jurisdiction/compliance constraints — filter via KnowledgeGraph legal matrix

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high` (cross-domain synthesis)
  - **Skills**: `python`, `pytest`, `knowledge-graph`, `data-synthesis`
  - Reason: Integrates structured + unstructured signal sources

  **Parallelization**:
  - **Can Run In Parallel**: After Task 4 (KnowledgeGraph) and Task 25 (CoreValues)
  - **Parallel Group**: Wave 5
  - **Blocks**: Task 27 (needs opportunity list)
  - **Blocked By**: Task 4, Task 25

  **References**:
  - Market scanner: `backend/data/market_universe.py:MarketUniverseScanner` — reuse discovery patterns
  - KnowledgeGraph queries: `backend/core/knowledge_graph.py:query_by_type()` — cross-domain link queries
  - Existing opportunities: `backend/strategies/` — what capabilities exist already

  **Acceptance Criteria**:

  **Unit Tests**:
  - [ ] `test_opportunity_finder_detects_cross_domain_edge`
  - [ ] `test_opportunity_finder_filters_by_safety_tier`
  - [ ] `test_opportunity_finder_respects_core_values_gate`
  - `pytest` → PASS

  **QA Scenario: Finds weather→crypto volatility edge**
    Tool: Bash (pytest)
    Preconditions: KnowledgeGraph has "weather event X correlates with crypto Y 0.62"; MarketUniverse has crypto market open; SafetyMonitor tier=MODERATE (allows cross-domain)
    Steps:
      1. `pytest backend/agi/tests/test_opportunity_finder.py::test_weather_crypto_edge_detected -xvs`
    Expected Result: Test PASS — opportunity returned with confidence 0.65+, required_capability="cross_domain_signal"
    Failure Indicators: No opportunity or confidence <0.55
    Evidence: `.sisyphus/evidence/task-26-opportunity-found.txt`

  **Commit**: YES
    - Message: `feat(agi-opportunity): scan cross-domain edges via KnowledgeGraph + MarketUniverse`
    - Files: `backend/agi/opportunity_finder.py`, `backend/agi/tests/test_opportunity_finder.py`
    - Pre-commit: `pytest backend/agi/tests/test_opportunity_finder.py`

- [x] 27. AutonomousGoalGenerator — turns opportunities into executable goals (`backend/agi/goal_generator.py`)

  **What to do**:
  - Create `AutonomousGoalGenerator`:
    - Input: `Opportunity` from Task 26
    - `generate_goal(opportunity) → Goal` — Goal has: objective (natural language), required_strategies (list of chromosomes), constraints (risk tier, max allocation), success_metric (e.g., "Sharpe >1.2 over 30 days"), time_horizon
    - Uses ProviderRegistry LLM to decompose objective into concrete strategy specification (reuse Phase 3 StrategyCodeGenerator patterns but now goal-level, not code-level)
    - Goal stored in `BotState.misc_data['active_goals']` with lifecycle status (proposed → approved → executing → completed → failed)
    - Requires CoreValues approval (Task 25) + SafetyMonitor risk gate (Task 1) before activation
  - Unit tests: mock opportunity → goal; verify constraints captured; verify approval flow

  **Must NOT do**:
  - Do NOT generate goals requiring >AGGRESSIVE risk tier without explicit admin override
  - Do NOT set success metrics that are unmeasurable — must map to performance_attributor metrics
  - Do NOT create goals with indefinite time horizons — max 90 days

  **Recommended Agent Profile**:
  - **Category**: `deep` (planning + constraint reasoning)
  - **Skills**: `python`, `pytest`, `llm-prompt-engineering`, `goal-specification`
  - Reason: Translating opportunity → constrained executable goal is complex reasoning

  **Parallelization**:
  - **Can Run In Parallel**: With Task 26 once API stable; Task 28 depends on this
  - **Parallel Group**: Wave 5
  - **Blocks**: Task 28
  - **Blocked By**: Task 26, Task 25, Task 1

  **References**:
  - Strategy spec format: `backend/core/strategy_synthesizer.py` output format (reuse schema)
  - Metrics: `backend/application/agi/performance_attributor.py` — what we can measure
  - Goal lifecycle: similar to `backend/application/agi/lifecycle_manager.py` for genome stages

  **Acceptance Criteria**:

  **Unit Tests**:
  - [ ] `test_goal_generator_produces_measurable_goal_from_opportunity`
  - [ ] `test_goal_requires_core_values_and_safety_approval`
  - [ ] `test_goal_constraints_respect_risk_tier`
  - `pytest` → PASS

  **QA Scenario: Generates valid goal with measurable success metric**
    Tool: Bash (pytest)
    Preconditions: Opportunity with confidence 0.7; mock ProviderRegistry returns strategy spec; SafetyMonitor tier=MODERATE approves
    Steps:
      1. `pytest backend/agi/tests/test_goal_generator.py::test_goal_generated_and_approved -xvs`
    Expected Result: Test PASS — Goal created, status=approved, success_metric="Sharpe >1.2", constraints include max_allocation=5% bankroll
    Failure Indicators: Goal rejected or missing constraints
    Evidence: `.sisyphus/evidence/task-27-goal-generated.txt`

  **Commit**: YES
    - Message: `feat(agi-goals): AutonomousGoalGenerator with safety+values gating`
    - Files: `backend/agi/goal_generator.py`, `backend/agi/tests/test_goal_generator.py`
    - Pre-commit: `pytest backend/agi/tests/test_goal_generator.py`

- [x] 28. MultiObjectiveOptimizer — resource allocation across concurrent goals (`backend/agi/multi_objective_optimizer.py`)

  **What to do**:
  - Create `MultiObjectiveOptimizer`:
    - Input: active `Goal` list from Task 27 (each with bankroll allocation request, time_horizon, expected_return, risk_score)
    - Optimize: maximize total expected utility subject to: total allocation ≤ `BankrollAllocator.daily_cap` (existing), risk-tier diversification (no single-domain >30%), time-horizon blending (long-term vs short-term mix)
    - Algorithm: simple constrained optimization (scipy.optimize.minimize with constraints) or heuristic weighted score: `score = 0.4*expected_return - 0.3*risk - 0.2*time_horizon_penalty + 0.1*diversity_bonus`
    - Output: allocation plan per goal → executed by BankrollAllocator (modified to accept AGI goal allocations)
    - Rebalance daily: re-run optimizer, adjust allocations; respect phase-gate checks (do not reallocate during Phase Gate windows)
  - Unit tests: 3 goals with conflicting constraints → optimizer finds feasible allocation; test risk diversification enforcement

  **Must NOT do**:
  - Do NOT overallocate beyond daily bankroll cap — hard constraint
  - Do NOT concentrate >30% in single domain (diversification guardrail)
  - Do NOT override human emergency stop — if `SHADOW_MODE=false` and admin pauses, freeze all allocations

  **Recommended Agent Profile**:
  - **Category**: `ultrabrain` (constrained optimization)
  - **Skills**: `python`, `scipy`, `pytest`, `optimization`
  - Reason: Mathematical optimization with multiple hard constraints

  **Parallelization**:
  - **Can Run In Parallel**: After Task 27 (needs goal list)
  - **Parallel Group**: Wave 5
  - **Blocks**: None (advisory to BankrollAllocator)
  - **Blocked By**: Task 27

  **References**:
  - Bankroll allocator: `backend/core/bankroll_allocator.py` — daily allocation logic; extend to accept AGI goal allocations
  - Constraints: risk_profiles.py `RISK_TIER_MAX_ALLOCATION` dict
  - Optimization: `scipy.optimize` examples; simple heuristic fallback if scipy unavailable

  **Acceptance Criteria**:

  **Unit Tests**:
  - [ ] `test_multi_objective_optimizer_respects_total_cap`
  - [ ] `test_multi_objective_optimizer_enforces_domain_diversification`
  - [ ] `test_multi_objective_optimizer_balances_time_horizons`
  - `pytest` → PASS

  **QA Scenario: Diversification prevents single-domain overallocation**
    Tool: Bash (pytest)
    Preconditions: 4 goals: DomainA (expected_return 0.2, allocation_request 40%), DomainB (0.18, 40%), DomainC (0.15, 20%), DomainD (0.12, 10%); total cap=100%
    Steps:
      1. `pytest backend/agi/tests/test_multi_objective_optimizer.py::test_domain_diversification_limit -xvs`
    Expected Result: Test PASS — optimizer reduces DomainA and DomainB to ≤30% each, reallocates to C/D; total ≤100%
    Failure Indicators: Any single domain >30% or total >100%
    Evidence: `.sisyphus/evidence/task-28-diversification-works.txt`

  **Commit**: YES
    - Message: `feat(agi-optimize): MultiObjectiveOptimizer with risk diversification and daily bankroll cap`
    - Files: `backend/agi/multi_objective_optimizer.py`, `backend/agi/tests/test_multi_objective_optimizer.py`
    - Pre-commit: `pytest backend/agi/tests/test_multi_objective_optimizer.py`

- [x] 29. LongTermPlanner — horizon planning and resource scheduling (`backend/agi/long_term_planner.py`)

  **What to do**:
  - Create `LongTermPlanner`:
    - Maintains 90-day rolling plan: upcoming goals, expected resource needs (GPU hours, data acquisition, LLM calls), predicted bankroll requirements
    - `plan_horizon() → Plan` with milestones per week; flags resource conflicts (e.g., two goals needing GPU at same time)
    - Negotiates with MultiObjectiveOptimizer: if conflict, optimizer re-weights near-term vs long-term utility
    - Integrated with AGI jobs: `backend/application/agi/evolution_jobs.py` already runs periodic cycles; LongTermPlanner sets cycle parameters (mutation rate, crossover prob) based on upcoming goals
    - Reads/writes plan to `BotState.misc_data['long_term_plan']` for UI visibility
  - Unit tests: mock 90-day horizon with overlapping resource requests → plan rebalances; test milestone completion tracking

  **Must NOT do**:
  - Do NOT plan beyond 90 days — too uncertain for prediction markets
  - Do NOT lock resources rigidly — allow optimizer to override with justification
  - Do NOT hide plan from UI — all milestones visible in dashboard

  **Recommended Agent Profile**:
  - **Category**: `deep` (long-horizon planning)
  - **Skills**: `python`, `pytest`, `scheduling`, `time-series`
  - Reason: Rolling 90-day resource-constrained planning

  **Parallelization**:
  - **Can Run In Parallel**: After Task 28 (optimizer) and Task 27 (goals exist)
  - **Parallel Group**: Wave 5
  - **Blocks**: None (advisory)
  - **Blocked By**: Tasks 27, 28

  **References**:
  - AGI jobs: `backend/application/agi/evolution_jobs.py` — periodic mutation/crossover cycles
  - Resource tracking: `backend/ai/architecture_search.py` GPU budget logic (reuse pattern)
  - Planning horizon: `backend/core/bankroll_allocator.py` daily vs weekly cadence

  **Acceptance Criteria**:

  **Unit Tests**:
  - [ ] `test_long_term_planner_produces_90_day_rolling_plan`
  - [ ] `test_long_term_planner_detects_and_resolves_resource_conflicts`
  - [ ] `test_long_term_planner_milestones_visible_in_botstate`
  - `pytest` → PASS

  **QA Scenario: Planner detects GPU conflict and rebalances**
    Tool: Bash (pytest)
    Preconditions: Goal A requests 100 GPU-hr in week 3; Goal B requests 120 GPU-hr in week 3; monthly budget=180 GPU-hr; planner active
    Steps:
      1. `pytest backend/agi/tests/test_long_term_planner.py::test_detects_gpu_conflict_and_reschedules -xvs`
    Expected Result: Test PASS — plan flags conflict in week 3, reschedules Goal B to week 4, total ≤180 GPU-hr/month, milestones updated
    Failure Indicators: Conflict unresolved or budget exceeded
    Evidence: `.sisyphus/evidence/task-29-planner-rebalance.txt`

  **Commit**: YES
    - Message: `feat(agi-plan): LongTermPlanner 90-day rolling resource scheduler with conflict resolution`
    - Files: `backend/agi/long_term_planner.py`, `backend/agi/tests/test_long_term_planner.py`
    - Pre-commit: `pytest backend/agi/tests/test_long_term_planner.py`

- [x] 30. Phase Gate 5 Review — Unbounded autonomy sign-off

  **What to do**:
  - `backend/tests/integration/test_phase_gate_5.py` aggregates Tasks 25–29
  - Fail if any unit or integration test from Phase 5 fails
  - CI required check before Wave 6 (final benchmarking)

  **Recommendation**: `deep` agent; `pytest`

  **Parallelization**: NO — after Tasks 25–29
    - **Blocks**: Wave 6

  **Acceptance**:
  - [ ] Phase Gate 5 suite PASS
  - `pytest test_phase_gate_5.py -xvs` → PASS

  **Commit**: YES
    - Message: `test(gate): Phase Gate 5 — unbounded autonomy goal formation and planning`
    - Files: `backend/tests/integration/test_phase_gate_5.py`
    - Pre-commit: `pytest backend/tests/integration/test_phase_gate_5.py`

---

### Wave 6 — Phase 6: AGI Benchmarking & Certification

> Quantifiable capability thresholds: cross-domain transfer >60%, few-shot >70%, causal reasoning >80%, AGI-Score >70.
> Evals scaffold created in Phase 1 Task 6; now populate benchmarks and reporting.

- [x] 31. Cross-Domain Transfer benchmark (`backend/evals/benchmarks/cross_domain_transfer.py`)

  **What to do**:
  - Implement benchmark: measure strategy performance transfer from source domain (e.g., crypto) to target domain (e.g., weather) after seeing ≤5 examples of target-market trades
  - Test harness: `EvalsRunner.run_benchmark(benchmark_id, fixtures)` → `BenchmarkResult(score, metadata)`
  - Scenario: Take top-performing strategy from crypto domain, adapt to weather markets using 5-example few-shot prompt via ProviderRegistry, run 30 simulated trades, compute success rate improvement over random baseline
  - Threshold: transfer_success_rate >60% (i.e., adapted strategy beats random 60% of the time)
  - Report: `BenchmarkReport(benchmark_id, score, passed)` saved to `backend/evals/reports/` as JSON; also logged to `BotState.misc_data['eval_history']`
  - Phase 1 Task 6 created `backend/evals/` scaffold with `EvalsRunner`, `BenchmarkRegistry`; register this benchmark there

  **Must NOT do**:
  - Do NOT use live markets — only simulated fixtures from `backend/tests/fixtures/`
  - Do NOT count a transfer as success if strategy simply memorizes source domain — measure target-domain improvement
  - Do NOT run without SafetyMonitor gating — simulated trades still respect safety thresholds

  **Recommended Agent Profile**:
  - **Category**: `deep` (benchmark design + measurement)
  - **Skills**: `python`, `pytest`, `statistics`, `evaluation-frameworks`
  - Reason: Designing measurable cross-domain transfer test with statistical rigor

  **Parallelization**:
  - **Can Run In Parallel**: YES — after Phase 1 Task 6 (evals scaffold exists); independent of Wave 5
  - **Parallel Group**: Wave 6
  - **Blocks**: Task 35 (final AGI-Score aggregation)
  - **Blocked By**: Phase 1 Task 6; Task 4 (KnowledgeGraph cross-domain links)

  **References**:
  - Evals scaffold: `backend/evals/runner.py`, `backend/evals/registry.py` (from Phase 1 Task 6)
  - Transfer learning literature: meta-learning, MAML benchmarks
  - Statistics baseline: random_baseline_success_rate = 1/3 for ternary markets; compare against that

  **Acceptance Criteria**:

  **Integration Test**:
  - [ ] `test_cross_domain_transfer_benchmark_passes_with_adapted_strategy`
  - [ ] `test_cross_domain_transfer_fails_without_adaptation`
  - `pytest backend/evals/benchmarks/test_cross_domain_transfer.py -xvs` → PASS

  **QA Scenario: Cross-domain transfer scores 65% (passes 60% threshold)**
    Tool: Bash (pytest)
    Preconditions: Crypto-optimized strategy; weather market fixture with 5 examples; ProviderRegistry returns adapted code; sandbox available
    Steps:
      1. `pytest backend/evals/benchmarks/test_cross_domain_transfer.py::test_transfer_success_rate_above_threshold -xvs`
    Expected Result: Test PASS — score ≥0.60, report saved, threshold check OK
    Failure Indicators: score <0.60 or benchmark crashes
    Evidence: `.sisyphus/evidence/task-31-transfer-ok.txt`

  **Commit**: YES
    - Message: `feat(agi-evals): cross-domain transfer benchmark >60% threshold`
    - Files: `backend/evals/benchmarks/cross_domain_transfer.py`, `backend/evals/benchmarks/test_cross_domain_transfer.py`
    - Pre-commit: `pytest backend/evals/benchmarks/test_cross_domain_transfer.py`

- [x] 32. Few-Shot Learning benchmark (`backend/evals/benchmarks/few_shot_learning.py`)

  **What to do**:
  - Implement benchmark: given ≤3 examples of a NEW market type (e.g., sports prediction), generate viable strategy via StrategyCodeGenerator (Task 14) using those examples, then evaluate on 20 held-out trades
  - Measure: success_rate (correct predictions) and Sharpe ratio of generated strategy
  - Threshold: success_rate >70% on held-out set
  - Uses ProviderRegistry to generate strategy conditioned on examples; CodeValidator + ExecutionSandbox for safety
  - Results saved to `backend/evals/reports/few_shot_%Y.json`; trend chart in UI via new endpoint `/evals/few-shot-trend`

  **Must NOT do**:
  - Do NOT allow strategy to see test set during generation — strict train/test split
  - Do NOT accept strategies that pass by memorizing example patterns — compute out-of-distribution generalization gap
  - Do NOT bypass SafetyMonitor for generated strategies — even in benchmark, respect safety gates

  **Recommended Agent Profile**:
  - **Category**: `deep` (benchmark + generalization measurement)
  - **Skills**: `python`, `pytest`, `statistics`, `llm-prompt-engineering`
  - Reason: Few-shot learning eval requires careful few-shot prompt construction + generalization measurement

  **Parallelization**:
  - **Can Run In Parallel**: YES — with Task 31 (both depend on evals scaffold)
  - **Parallel Group**: Wave 6
  - **Blocks**: Task 35
  - **Blocked By**: Phase 1 Task 6; Task 14 (StrategyCodeGenerator); Task 4 (KnowledgeGraph for market examples)

  **References**:
  - Few-shot prompt patterns: ProviderRegistry LLM capability; reuse from `backend/core/strategy_synthesizer.py` examples
  - Evals harness: `backend/evals/runner.py` — add benchmark registration
  - Generalization metrics: classification accuracy + Sharpe for imbalanced markets

  **Acceptance Criteria**:

  **Integration Test**:
  - [ ] `test_few_shot_benchmark_generates_strategy_from_3_examples`
  - [ ] `test_few_shot_benchmark_success_rate_above_70_percent`
  - `pytest backend/evals/benchmarks/test_few_shot_learning.py -xvs` → PASS

  **QA Scenario: Few-shot learning achieves 75% success rate**
    Tool: Bash (pytest)
    Preconditions: 3 example sports prediction markets; generated strategy evaluated on 20 held-out; ProviderRegistry returns working strategy; sandbox passes
    Steps:
      1. `pytest backend/evals/benchmarks/test_few_shot_learning.py::test_seventy_five_percent_success -xvs`
    Expected Result: Test PASS — success rate ≥70%, Sharpe positive, report saved
    Failure Indicators: <70% success or invalid strategy
    Evidence: `.sisyphus/evidence/task-32-few-shot-ok.txt`

  **Commit**: YES
    - Message: `feat(agi-evals): few-shot learning benchmark >70% threshold`
    - Files: `backend/evals/benchmarks/few_shot_learning.py`, `backend/evals/benchmarks/test_few_shot_learning.py`
    - Pre-commit: `pytest backend/evals/benchmarks/test_few_shot_learning.py`

- [x] 33. Causal Reasoning benchmark (`backend/evals/benchmarks/causal_reasoning.py`)

  **What to do**:
  - Implement benchmark: given observed market event → outcome pairs, ask AGI to infer causal graph and predict outcome of intervention
  - Example: "News event X normally moves Market Y by +2% within 10 minutes; does it also affect Market Z?" — measure prediction accuracy on held-out interventions
  - Use `CausalReasoningEngine` stub (tests exist but no impl in `backend/core/causal_reasoning.py`); fully implement it:
    - `infer_causal_graph(observations: list[Event]) → Graph` — use PC algorithm or LLM-based causal discovery via ProviderRegistry
    - `predict_intervention(graph, intervention_node, intervention_value) → predicted_outcome`
    - `evaluate_accuracy(predictions, ground_truth) → float [0–1]`
  - Threshold: causal_accuracy >80% on intervention test set
  - Safety: All predictions gated by SafetyMonitor; reject high-uncertainty interventions

  **Must NOT do**:
  - Do NOT claim causality from correlation alone — benchmark measures causal inference, not association
  - Do NOT let agent peek at ground truth graph — only observations provided
  - Do NOT evaluate on trivial interventions (e.g., "no effect") — test meaningful causal queries

  **Recommended Agent Profile**:
  - **Category**: `ultrabrain` (causal inference + implementation)
  - **Skills**: `python`, `pytest`, `cryptography`, `statistics`, `causal-discovery`
  - Reason: Causal reasoning benchmark requires implementing actual causal discovery algorithm

  **Parallelization**:
  - **Can Run In Parallel**: YES — after Phase 1 Task 6 (evals scaffold)
  - **Parallel Group**: Wave 6
  - **Blocks**: Task 35
  - **Blocked By**: Phase 1 Task 6; Task 4 (KnowledgeGraph for event storage)

  **References**:
  - Causal inference: `causal-learn` package if available; else PC algorithm from stats literature
  - Existing tests: `backend/tests/test_causal_reasoning.py` (test file exists, reveals expected API)
  - Events: `backend/core/event_bus.py` or similar — where market events are logged

  **Acceptance Criteria**:

  **Integration Test**:
  - [ ] `test_causal_reasoning_benchmark_infers_correct_graph`
  - [ ] `test_causal_reasoning_benchmark_predicts_interventions_above_80_percent`
  - `pytest backend/evals/benchmarks/test_causal_reasoning.py -xvs` → PASS

  **QA Scenario: Causal accuracy hits 85% on intervention predictions**
    Tool: Bash (pytest)
    Preconditions: Synthetic causal graph (A→B→C); observations dataset; ground truth interventions; CausalReasoningEngine implemented
    Steps:
      1. `pytest backend/evals/benchmarks/test_causal_reasoning.py::test_causal_accuracy_eighty_five_percent -xvs`
    Expected Result: Test PASS — causal accuracy ≥80%, intervention predictions match ground truth
    Failure Indicators: accuracy <80% or graph inference fails
    Evidence: `.sisyphus/evidence/task-33-causal-ok.txt`

  **Commit**: YES
    - Message: `feat(agi-evals): implement causal reasoning benchmark + CausalReasoningEngine >80% accuracy`
    - Files: `backend/core/causal_reasoning.py`, `backend/evals/benchmarks/causal_reasoning.py`, `backend/evals/benchmarks/test_causal_reasoning.py`
    - Pre-commit: `pytest backend/evals/benchmarks/test_causal_reasoning.py`

- [x] 34. AGI-Score composite benchmark (`backend/evals/benchmarks/agi_score.py`)

  **What to do**:
  - Create composite AGI-Score from four sub-benchmarks:
    - cross_domain_transfer score (Task 31) — weight 0.30
    - few_shot_learning score (Task 32) — weight 0.30
    - causal_reasoning score (Task 33) — weight 0.25
    - autonomous_generation_quality (Task 14–18 integration metrics) — weight 0.15
  - `compute_agi_score(results: dict) → float [0–100]`
  - Threshold: overall AGI-Score >70 passes certification
  - Report: `/evals/agi-score` endpoint returns latest score + breakdown; UI displays gauge chart
  - Historical tracking: each benchmark run appends to `BotState.misc_data['agi_score_history']` with timestamp

  **Must NOT do**:
  - Do NOT weight any sub-benchmark to zero — all four contribute
  - Do NOT report score without passing all safety gates — if any component fails safety, overall score = 0
  - Do NOT allow manual override of thresholds — hardcoded targets per user spec (60%, 70%, 80%, 70%)

  **Recommended Agent Profile**:
  - **Category**: `deep` (composite metric design)
  - **Skills**: `python`, `pytest`, `statistics`, `weighted-averaging`
  - Reason: Weighted aggregation of heterogeneous benchmark scores

  **Parallelization**:
  - **Can Run In Parallel**: After Tasks 31, 32, 33 complete (needs all sub-scores)
  - **Parallel Group**: Wave 6
  - **Blocks**: None (final benchmark)
  - **Blocked By**: Tasks 31, 32, 33

  **References**:
  - Sub-benchmark results: `backend/evals/reports/*.json` — read latest per benchmark
  - Performance attributor: `backend/application/agi/performance_attributor.py` — weighting patterns
  - UI endpoint: `backend/api/evals.py` (new file) to expose `/evals/agi-score`

  **Acceptance Criteria**:

  **Integration Test**:
  - [ ] `test_agi_score_computes_weighted_composite`
  - [ ] `test_agi_score_returns_zero_if_any_component_fails_safety`
  - [ ] `test_agi_score_seventy_passes_threshold`
  - `pytest backend/evals/benchmarks/test_agi_score.py -xvs` → PASS

  **QA Scenario: AGI-Score reaches 72 (passes 70 threshold)**
    Tool: Bash (pytest)
    Preconditions: Sub-benchmark scores: transfer=0.68 (weight30→20.4), few-shot=0.75(30→22.5), causal=0.82(25→20.5), generation=0.85(15→12.75); safety all green
    Steps:
      1. `pytest backend/evals/benchmarks/test_agi_score.py::test_seventy_two_passes -xvs`
    Expected Result: Test PASS — AGI-Score = (20.4+22.5+20.5+12.75) = 76.15/100 = 76.15 → passes ≥70
    Failure Indicators: <70 or safety component flagged
    Evidence: `.sisyphus/evidence/task-34-agi-score-ok.txt`

  **Commit**: YES
    - Message: `feat(agi-evals): AGI-Score composite benchmark with 4-component weighting`
    - Files: `backend/evals/benchmarks/agi_score.py`, `backend/evals/benchmarks/test_agi_score.py`, `backend/api/evals.py`
    - Pre-commit: `pytest backend/evals/benchmarks/test_agi_score.py`

- [x] 35. Phase Gate 6 & Final Certification — True Full AGI verification

  **What to do**:
  - `backend/tests/integration/test_phase_gate_6.py` aggregates ALL Phase 6 benchmarks (31–34)
  - Additionally: run `backend/evals/certification_checklist.py` which verifies:
    - All 4 benchmark thresholds met (transfer>60%, few-shot>70%, causal>80%, AGI-Score>70)
    - All Phase Gate CI checks green (Gates 1–6)
    - No SafetyMonitor critical alerts in last 24h
    - All UI configuration endpoints functional (`/config/safety-thresholds`, `/config/nas-budget`, `/config/provider-chain`, `/config/benchmark-cadence`)
  - Only when Gate 6 passes + all 4 benchmark thresholds green → system certified True Full AGI
  - Record certification timestamp in `BotState.misc_data['agi_certification_timestamp']`; UI displays "AGI Certified" banner
  - Final QA: Real Manual QA (Task F3) validates UI config controls actually change behavior (not just stored)

  **Must NOT do**:
  - Do NOT certify if any benchmark below threshold — zero-tolerance
  - Do NOT ignore SafetyMonitor alerts during benchmark runs — fail if any CRITICAL alert
  - Do NOT allow partial certification — all-or-nothing

  **Recommended Agent Profile**:
  - **Category**: `oracle` (certification gate requires holistic verification)
  - **Skills**: `pytest`, `fastapi-testclient`, `oracle-review`
  - Reason: Final sign-off requires verifying all pieces work together and all thresholds met

  **Parallelization**:
  - **Can Run In Parallel**: NO — after all Phase 6 tasks complete
  - **Blocks**: None (final gate)
  - **Blocked By**: Tasks 31, 32, 33, 34; all previous Phase Gates 1–5

  **Acceptance**:
  - [ ] Phase Gate 6 suite PASS
  - [ ] AGI-Score ≥70.0
  - [ ] All 4 sub-benchmarks meet individual thresholds
  - [ ] SafetyMonitor zero CRITICAL alerts in benchmark window
  - [ ] UI config endpoints verified by QA
  - `pytest test_phase_gate_6.py -xvs` → PASS

  **Commit**: YES
    - Message: `test(gate): Phase Gate 6 — AGI certification; all benchmarks pass, True Full AGI achieved`
    - Files: `backend/tests/integration/test_phase_gate_6.py`, `backend/evals/certification_checklist.py`
    - Pre-commit: `pytest backend/tests/integration/test_phase_gate_6.py`

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)

> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.

- [x] F1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists (read file, curl endpoint, run command). For each "Must NOT Have": search codebase for forbidden patterns — reject with file:line if found. Check evidence files exist in `.sisyphus/evidence/`. Compare deliverables against plan.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [x] F2. **Code Quality Review** — `unspecified-high`
  Run `tsc --noEmit` + linter + `bun test` (frontend) and `pytest` (backend) with coverage ≥80%. Review all changed files for: `as any`/`@ts-ignore`, empty catches, console.log in prod, commented-out code, unused imports. Check AI slop: excessive comments, over-abstraction, generic names (data/result/item/temp).
  Output: `Build [PASS/FAIL] | Lint [PASS/FAIL] | Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [x] F3. **Real Manual QA** — `unspecified-high` (+ `playwright` skill if UI)
  Start from clean state. Execute EVERY QA scenario from EVERY task — follow exact steps, capture evidence. Test cross-task integration (features working together, not isolation). Test edge cases: empty state, invalid input, rapid actions. Save to `.sisyphus/evidence/final-qa/`.
  Output: `Scenarios [N/N pass] | Integration [N/N] | Edge Cases [N tested] | VERDICT`

- [x] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff (git log/diff). Verify 1:1 — everything in spec was built (no missing), nothing beyond spec was built (no creep). Check "Must NOT do" compliance. Detect cross-task contamination: Task N touching Task M's files. Flag unaccounted changes.
  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

- Group commits by wave (Wave 1 → 8 commits, Wave 2 → 6 commits, Wave 3 → 5 commits, Wave 4 → 4 commits, Wave 5 → 5 commits, Wave 6 → 4 commits, Final Wave → 4 commits)
- Total: ~36 integration commits + individual task commits (aggregated per wave for readability)
- Pre-commit hooks: `pytest backend/tests/...` per task; Phase Gate tests required before next wave merge

---

## Success Criteria

### Verification Commands
```bash
# Phase 1: SafetyMonitor + ProviderRegistry + ReasoningEngine + KnowledgeGraph + PluginManager + Evals scaffold
/home/linuxbrew/.linuxbrew/bin/python3 -m pytest backend/tests/unit/test_safety_monitor.py backend/ai/tests/test_provider_registry.py backend/core/tests/test_reasoning_engine.py backend/core/tests/test_knowledge_graph.py backend/core/tests/test_plugin_registry.py backend/evals/tests/test_runner.py -xvs

# Phase 2: LearningSystem + TransferLearner + MultiDomainOrchestrator (unit tests per task)
/home/linuxbrew/.linuxbrew/bin/python3 -m pytest backend/core/tests/test_learning_system.py backend/core/tests/test_transfer_learning.py backend/core/tests/test_multi_domain_orchestrator.py -xvs

# Phase 3: StrategyCodeGenerator + CodeValidator + ExecutionSandbox + HypothesisTester
/home/linuxbrew/.linuxbrew/bin/python3 -m pytest backend/core/tests/test_strategy_synthesizer.py backend/agi/tests/test_code_validator.py backend/agi/tests/test_extended_sandbox.py backend/agi/tests/test_hypothesis_tester.py -xvs

# Phase 4: NAS + CodeRefactorer + SelfModReasoningEngine
/home/linuxbrew/.linuxbrew/bin/python3 -m pytest backend/ai/tests/test_architecture_search.py backend/agi/tests/test_code_refactorer.py backend/core/tests/test_reasoning_engine_self_mod.py -xvs

# Phase 5: CoreValues + OpportunityFinder + GoalGenerator + MultiObjectiveOptimizer + LongTermPlanner
/home/linuxbrew/.linuxbrew/bin/python3 -m pytest backend/agi/tests/test_core_values.py backend/agi/tests/test_opportunity_finder.py backend/agi/tests/test_goal_generator.py backend/agi/tests/test_multi_objective_optimizer.py backend/agi/tests/test_long_term_planner.py -xvs

# Phase 6: Evals benchmarks (cross-domain, few-shot, causal, AGI-Score)
/home/linuxbrew/.linuxbrew/bin/python3 -m pytest backend/evals/benchmarks/test_cross_domain_transfer.py backend/evals/benchmarks/test_few_shot_learning.py backend/evals/benchmarks/test_causal_reasoning.py backend/evals/benchmarks/test_agi_score.py -xvs

# Phase Gates (aggregate each wave)
/home/linuxbrew/.linuxbrew/bin/python3 -m pytest backend/tests/integration/test_phase_gate_1.py test_phase_gate_2.py test_phase_gate_3.py test_phase_gate_4.py test_phase_gate_5.py test_phase_gate_6.py -xvs

# Final Certification
/home/linuxbrew/.linuxbrew/bin/python3 -m pytest backend/evals/certification_checklist.py -xvs && echo "✓ True Full AGI Certified"
```

### Final Checklist
- [ ] All "Must Have" present (35+ deliverables across 6 phases)
- [ ] All "Must NOT Have" absent (no direct LLM imports, safety bypasses, env-only config)
- [ ] All tests pass (169 existing + new task tests + integration tests)
- [ ] UI configuration endpoints reachable and persisting to BotState.misc_data
- [ ] InferenceProvider chain configurable with 5 backends (Runpod, Omniroute, OpenAI, HuggingFace, Ollama)
- [ ] Safety thresholds UI-configurable (min/max risk per tier, position caps)
- [ ] Benchmark schedule UI-configurable (daily/weekly/monthly cadence)
- [ ] NAS GPU budget UI-configurable (NAS_MAX_GPU_HOURS_PER_MONTH)
- [ ] ProviderRegistry priority chain and failover configurable via UI
- [ ] Zero breaking changes to existing 169 tests
- [ ] Phase Gate CI checks all passing
- [ ] AGI-Score ≥70 with all 4 sub-benchmarks meeting individual thresholds
