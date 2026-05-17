# PolyEdge Modular Plugin System Refactoring

> **Quick Summary**: Implement a unified plugin architecture for 4 subsystems using decorator-based registration, background health monitoring, and sandbox strategy validation with 4-gate pipeline. All four plugin systems share a generic PluginRegistry base.
> 
> **Deliverables**:
> - `backend/core/plugin_registry.py` - Generic registry base
> - `backend/core/plugin_errors.py` - Shared error types
> - `backend/ai/` - AI provider plugins, ensemble refactor, API endpoints
> - `backend/data/` - Data source plugins, mock source, strategy context injection
> - `backend/markets/` - Normalized order types, market provider plugins, paper mode
> - `backend/agi/` - Node registry, agent state, graph engine, sandbox validation
> - All API endpoints, frontend panels, comprehensive tests, all documentation
> - **Estimated Effort**: Large (8-12 weeks)
> - **Parallel Execution**: YES - 8 waves, ~80% faster than sequential
> - **Critical Path**: Core → Domains → Integration → Verification

---

## Context

### Original Request
Major refactoring to transform four subsystems (AI Providers, Data Sources, Market Providers, AGI system) into modular plugin architectures where each plugin can be independently developed, loaded, enabled/disabled at runtime, and fails in isolation without crashing the host process.

### Interview Summary
**Key Discussions**:
- Plugin discovery via auto-import of `providers/`, `sources/`, `nodes/` directories using `importlib`
- Decorator pattern for automatic registration (`@provider_registry.plugin`)
- Singleton registry pattern for each domain
- Background health check loops at configurable intervals
- Sandbox uses mock data only, never lives
- Node system uses AgentState as shared mutable state passed through graph
- 4-gate validation for sandbox strategy evaluation

**Research Findings**:
- Current AI: Hard-coded ensemble with claude.py, groq.py; needs registry-based discovery
- Current Data: DataProvider ABC exists; strategies import clients directly; needs registry + strategy context injection
- Current Orders: Direct CLOB/kalshi calls from strategies; needs normalized interface + provider plugins
- Current AGI: Tight coupling in backend/core/; needs node-based graph execution with sandbox

### Metis Review
**Identified Gaps** (addressed):
- **Gap**: Circular import risk - agi layer imports from core, but core shouldn't import from agi. *Resolved*: Only backend/core modules wrapped as nodes; agi imports core but not vice versa.
- **Gap**: Sandbox safety - must guarantee no live DB access or live market providers. *Resolved*: SandboxManager injects mock registries only; gate 1 rejects forbidden imports; graph engine skips nodes with requires_db/requires_live_data in sandbox mode.
- **Gap**: Registry persistence - enabled/disabled state must survive restarts. *Resolved*: All set_enabled() write to BotState.misc_data under botstate_mutex.
- **Gap**: Health check failure handling - degraded vs removed. *Resolved*: Health failures mark providers as degraded (not removed); background loop logs; never auto-recover without operator intervention.

---

## Work Objectives

### Core Objective
Build a unified plugin architecture where modules declare themselves as plugins, register automatically at startup, support runtime enable/disable, and isolate failures without affecting the host process.

### Concrete Deliverables
- Generic plugin registry infrastructure (`backend/core/plugin_registry.py`)
- AI Provider system (`backend/ai/`)
- Data Source system (`backend/data/`)
- Market Provider system (`backend/markets/`)
- AGI Node system with sandbox (`backend/agi/`)
- All required API endpoints
- Frontend monitoring panels
- Comprehensive test suite
- All documentation updates

### Definition of Done
- [x] `backend/core/plugin_registry.py` passes unit tests
- [x] All four domain plugin systems pass unit tests
- [x] Sandbox 4-gate validation passes all test cases
- [x] All API endpoints functional via integration tests
- [ ] Frontend panels display plugin status and control enable/disable
- [x] All tests run under `SHADOW_MODE=true` with mock data only
- [x] Documentation complete in all AGENTS.md files, `docs/api.md`, and ADRs

### Must Have
- All plugin systems use shared registry base
- All registries support auto-discovery, enable/disable, health checks
- Sandboxed strategy validation has 4-gate pipeline
- All API endpoints match specification
- Frontend panels show real-time plugin status

### Must NOT Have (Guardrails)
- **No circular imports** - agi imports core, but core never imports from agi
- **No live DB access in sandbox** - sandbox validates never touch production DB
- **No live market providers in tests** - all tests use mock/paper providers
- **No removing existing daemons** - autonomous_promoter, etc. continue to operate
- **No rewriting strategy algorithms** - node wrappers call existing code

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** - ALL verification is agent-executed. No exceptions.
> Acceptance criteria requiring "user manually tests/confirms" are FORBIDDEN.

### Test Decision
- **Infrastructure exists**: YES (pytest + SHADOW_MODE flag)
- **Automated tests**: TDD - RED-GREEN-REFACTOR for all plugin systems
- **Framework**: pytest with pytest-asyncio
- **If TDD**: Each task follows RED (failing test) → GREEN (minimal impl) → REFACTOR

### QA Policy
Every task MUST include agent-executed QA scenarios (see TODO template below).
Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`.

- **Frontend/UI**: Use Playwright (playwright skill) - Navigate, interact, assert DOM, screenshot
- **TUI/CLI**: Use interactive_bash (tmux) - Run command, send keystrokes, validate output
- **API/Backend**: Use Bash (curl) - Send requests, assert status + response fields
- **Library/Module**: Use Bash (bun/node REPL) - Import, call functions, compare output

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately - core infrastructure):
├── Task 1: backend/core/plugin_registry.py - Generic base with registry pattern
├── Task 2: backend/core/plugin_errors.py - Shared error types
├── Task 3: backend/ai/base_provider.py - AI provider abstract base
├── Task 4: backend/ai/provider_registry.py - AI registry implementation
├── Task 5: backend/data/base_source.py - Data source abstract base
├── Task 6: backend/data/source_registry.py - Data registry implementation
├── Task 7: backend/markets/order_types.py - Normalized order dataclasses
└── Task 8: backend/markets/base_provider.py - Market provider abstract base

Wave 2 (After Wave 1 - AI Provider system):
├── Task 9: backend/ai/providers/__init__.py - Auto-discover setup
├── Task 10: backend/ai/providers/claude_provider.py - Wrap claude.py as plugin
├── Task 11: backend/ai/providers/groq_provider.py - Wrap groq.py as plugin
├── Task 12: backend/ai/ensemble.py - Refactor to read registry instead of hard-coded
├── Task 13: backend/api/v1/ai_providers.py - API endpoints for provider control
└── Task 14: backend/tests/test_ai_provider_registry.py - Unit tests

Wave 3 (After Wave 1 - Data Source system):
├── Task 15: backend/data/sources/__init__.py - Auto-discover setup
├── Task 16: backend/data/sources/polymarket_source.py - Wrap polymarket_clob.py
├── Task 17: backend/data/sources/kalshi_source.py - Wrap kalshi_client.py
├── Task 18: backend/data/sources/mock_source.py - In-memory mock for sandbox
├── Task 19: backend/data/market_universe.py - Update to use data registry
├── Task 20: backend/strategies/base.py - Add data_registry to StrategyContext
├── Task 21: backend/api/v1/data_sources.py - API endpoints for source control
└── Task 22: backend/tests/test_data_source_registry.py - Unit tests

Wave 4 (After Wave 1 - Market Provider system):
├── Task 23: backend/markets/provider_registry.py - Registry implementation
├── Task 24: backend/markets/providers/__init__.py - Auto-discover setup
├── Task 25: backend/markets/providers/polymarket_provider.py - Wrap CLOB client
├── Task 26: backend/markets/providers/kalshi_provider.py - Wrap kalshi_client.py
├── Task 26a: backend/clients/azuro_client.py - Shared Azuro GraphQL/Web3 client (TTL cache)
├── Task 26b: backend/markets/providers/predict_fun_provider.py - predict.fun via AzuroClient
├── Task 26c: backend/markets/providers/bookmaker_xyz_provider.py - bookmaker.xyz via AzuroClient
├── Task 26d: backend/clients/limitless_client.py + limitless_provider.py - limitless.exchange REST
├── Task 26e: backend/clients/sxbet_client.py + sxbet_provider.py - sx.bet REST + EIP-712
├── Task 27: backend/markets/providers/paper_provider.py - In-memory paper trading
├── Task 28: backend/strategies/order_executor.py - Refactor to use market registry
├── Task 29: backend/core/settlement.py - Update to stream fills from registry
├── Task 30: backend/api/v1/market_providers.py - API endpoints for venue control
├── Task 31: backend/tests/test_market_provider_registry.py - Unit tests (all 6 providers)
└── Task 32: backend/tests/test_paper_provider.py - Paper provider tests

Wave 5 (After Waves 1-4 - AGI core infrastructure):
├── Task 33: backend/agi/agent_state.py - AgentState dataclass
├── Task 34: backend/agi/base_node.py - AGI node abstract base
├── Task 35: backend/agi/node_registry.py - Node registry implementation
├── Task 36: backend/agi/graph_engine.py - Directed graph executor
└── Task 37: backend/tests/test_graph_engine.py - Graph engine tests

Wave 6 (After Wave 5 - AGI sandbox system):
├── Task 38: backend/agi/sandbox/sandbox_manager.py - Isolated execution manager
├── Task 39: backend/agi/sandbox/sandbox_validator.py - 4-gate validation
├── Task 40: backend/agi/sandbox/sandbox_registry.py - Mock-only registry
├── Task 41: backend/agi/sandbox/results.py - SandboxResult dataclass
├── Task 42: backend/tests/test_sandbox_validator.py - 4-gate validation tests
└── Task 43: backend/tests/test_sandbox_manager.py - Sandbox isolation tests

Wave 7 (After Wave 5 - AGI nodes and graphs):
├── Task 44: backend/agi/nodes/__init__.py - Auto-discover setup
├── Task 45: backend/agi/nodes/regime_detector_node.py - Wrap regime detector
├── Task 46: backend/agi/nodes/knowledge_graph_node.py - Wrap KG
├── Task 47: backend/agi/nodes/strategy_composer_node.py - Wrap composer
├── Task 48: backend/agi/nodes/strategy_synthesizer_node.py - Wrap synthesizer
├── Task 49: backend/agi/nodes/goal_engine_node.py - Wrap goal engine
├── Task 50: backend/agi/nodes/forensics_node.py - Wrap forensics
├── Task 51: backend/agi/nodes/auto_improve_node.py - Wrap auto improve
├── Task 52: backend/agi/nodes/model_calibration_node.py - Wrap calibration job
├── Task 53: backend/agi/nodes/evolution_node.py - Wrap evolution jobs
├── Task 54: backend/agi/graphs/__init__.py - Graph definitions
├── Task 55: backend/agi/graphs/market_analysis_graph.py - Regime → KG → Goal
├── Task 56: backend/agi/graphs/strategy_evolution_graph.py - Synth → Sandbox → Promote
├── Task 57: backend/agi/graphs/forensics_graph.py - Loss → Forensics → Improve
├── Task 58: backend/agi/node_registry.py - Reference import for all nodes
├── Task 59: backend/tests/test_node_registry.py - Node registry tests
└── Task 60: backend/tests/test_sandbox_node.py - Sandbox node tests

Wave 8 (After Waves 2-7 - Integration + Frontend):
├── Task 61: backend/api/v1/agi_nodes.py - AGI API endpoints
├── Task 62: backend/api/v1/agi_graphs.py - Graph run endpoints
├── Task 63: backend/api/v1/agi_sandbox.py - Sandbox validation endpoints
├── Task 64: frontend/src/components/PluginStatusPanel.tsx - Unified plugin view
├── Task 65: frontend/src/components/VenueMonitor.tsx - Per-venue monitoring
├── Task 66: frontend/src/components/SandboxMonitor.tsx - Sandbox validation
├── Task 67: frontend/src/components/AGIGraphRunner.tsx - Graph trigger
├── Task 68: frontend/src/api/providers.ts - AI provider client
├── Task 69: frontend/src/api/data_sources.ts - Data source client
├── Task 70: frontend/src/api/market_venues.ts - Market provider client
├── Task 71: frontend/src/api/agi.ts - AGI client
├── Task 72: backend/tests/test_integration_ensemble.py - End-to-end AI tests
├── Task 73: backend/tests/test_integration_data_strategy.py - Strategy data tests
├── Task 74: backend/tests/test_integration_order_executor.py - Order lifecycle tests
├── Task 75: backend/tests/test_integration_sandbox_evolution.py - Evolution tests
└── Task 76: backend/tests/test_integration_settlement_fills.py - Settlement tests

Wave FINAL (After ALL tasks — 4 parallel reviews, then user okay):
├── Task F1: Plan compliance audit (oracle)
├── Task F2: Code quality review (unspecified-high)
├── Task F3: Real manual QA (unspecified-high)
└── Task F4: Scope fidelity check (deep)
-> Present results -> Get explicit user okay

Critical Path: Task 1 → Task 2 → Task 3/4/5/6/7/8 → Task 9-14/15-22/23-32/33-43/44-60 → Task 61-70 → Task 71-76 → F1-F4 → user okay
New Provider Sub-Path (Wave 4): Task 26a → Task 26b + Task 26c (parallel, Azuro dep) | Task 26d + Task 26e (parallel, independent)
Parallel Speedup: ~80% faster than sequential
Max Concurrent: 8
```

### Dependency Matrix

```
Wave 1: - Tasks 1-8 (standalone - no dependencies)
Wave 2: - Tasks 9-14 (deps: 1, 3, 4)
Wave 3: - Tasks 15-22 (deps: 1, 5, 6)
Wave 4: - Tasks 23-32 (deps: 1, 2, 7, 8)
         - Task 26a: no deps (standalone client)
         - Tasks 26b, 26c: dep on Task 26a
         - Tasks 26d, 26e: no deps (independent clients)
         - Task 31: dep on 25, 26, 26a-26e, 27
Wave 5: - Tasks 33-37 (deps: 1, 2)
Wave 6: - Tasks 38-43 (deps: 33-37)
Wave 7: - Tasks 44-60 (deps: 33-37)
Wave 8: - Tasks 61-76 (deps: 9-60, 23-32, 15-22, 9-14)
FINAL: - Tasks F1-F4 (deps: ALL prior tasks)
```

### Agent Dispatch Summary

- **Wave 1**: 2 quick + 6 unspecified-high (infrastructure)
- **Wave 2**: 4 quick (providers + refactor) + 1 unspecified-high (API)
- **Wave 3**: 2 quick (sources) + 3 unspecified-high (mock, strategy context, API)
- **Wave 4**: 1 quick + 3 unspecified-high (providers) + 5 unsp. high (new providers: azuro_client, predict_fun, bookmaker_xyz, limitless, sxbet) + 3 unsp. high (executor, settlement, API, tests)
- **Wave 5**: 1 quick + 2 unspecified-high (state, base, registry, engine, tests)
- **Wave 6**: 3 unspecified-high + 2 tests (sandbox system)
- **Wave 7**: 6 unspecified-high (nodes) + 3 unsp. high (graphs, registry, tests)
- **Wave 8**: 1 quick + 2 unspecified-high (API) + 7 unsp. high (frontend, integration tests)
- **FINAL**: 4 unsp. high (review tasks)

---

## TODOs

> Implementation + Test = ONE Task. Never separate.
> EVERY task MUST have: Recommended Agent Profile + Parallelization info + QA Scenarios.
> **A task WITHOUT QA Scenarios is INCOMPLETE. No exceptions.**

### Wave 1: Core Infrastructure (Tasks 1-8)

- [x] 1. Create `backend/core/plugin_registry.py` - Generic base for all plugin registries

  **What to do**:
  - Create generic `PluginRegistry[T_Manifest, T_Plugin]` abstract base class
  - Implement `plugin()` decorator for automatic registration at import time
  - Implement `auto_discover(package: str)` to import all modules and register plugins
  - Implement `get(name)` - return plugin instance, raise `PluginNotFound` if missing
  - Implement `list_all()` - return all manifests (only healthy plugins)
  - Implement `set_enabled(name, enabled)` - persist to BotState.misc_data under botstate_mutex
  - Implement `run_health_checks()` - async, call health_check() on each, return dict of status
  - Add type hints and comprehensive docstrings

  **Test cases**:
  - Register valid plugin → succeeds, gets healthy status
  - Register plugin missing required env vars → raises `PluginEnvVarMissing`
  - Auto-discover loads all plugins in package directory
  - Set enabled/disabled writes to BotState.misc_data and survives restart
  - Get missing plugin → raises `PluginNotFound`
  - Health check failure marks plugin degraded (not removed)

  **Must NOT do**:
  - Do not implement health check loop here (that's per-domain registry)
  - Do not create specific plugin subclasses here (that's per-domain)
  - Do not write to files (only in-memory state)

  **Recommended Agent Profile**:
  > - **Category**: `quick` - Infrastructure file creation with clear interface
  > - **Skills**: `git-master`, `verification-before-completion`
  >   - `git-master`: Create file, add proper imports, format
  >   - `verification-before-completion`: Run pytest immediately, verify pass
  > - **Skills Evaluated but Omitted**: `ultrabrain` - No complex logic needed

  **Parallelization**:
  - **Can Run In Parallel**: YES - Foundation task
  - **Parallel Group**: Wave 1 independent tasks (1-8)
  - **Blocks**: Tasks 3, 5, 7 (base classes depend on registry base)
  - **Blocked By**: None (can start immediately)

  **References** (CRITICAL - Be Exhaustive):
  - **Pattern References**: None (creating new pattern)

  **Acceptance Criteria**:
  - [x] `backend/core/plugin_registry.py` created with all methods
  - [x] `pytest backend/tests/test_plugin_registry.py::test_register_valid_plugin` → PASS
  - [x] `pytest backend/tests/test_plugin_registry.py::test_auto_discover` → PASS
  - [x] `pytest backend/tests/test_plugin_registry.py::test_enabled_persistence` → PASS
  - [x] No linter errors (`ruff check backend/core/plugin_registry.py`)
  - [x] Type checking passes (`mypy backend/core/plugin_registry.py`)

  **QA Scenarios (MANDATORY - task is INCOMPLETE without these)**:

  \`\`\`
  Scenario: Register valid plugin and verify healthy
    Tool: bash
    Preconditions: Test directory with valid plugin implementing BasePlugin
    Steps:
      1. Import plugin_registry module
      2. Define test plugin with valid manifest (name, version, required_env_vars)
      3. Register plugin using @plugin_registry.plugin decorator
      4. Call plugin_registry.get("test_plugin")
    Expected Result: Returns plugin instance, status=healthy in list_all()
    Failure Indicators: PluginNotFound if registration failed
    Evidence: .sisyphus/evidence/task-01-register-valid-plugin.py
  \`\`\`

- [x] 2. Create `backend/core/plugin_errors.py` - Shared error types

  **What to do**:
  - Create custom exception hierarchy mirroring the spec
  - Define `PluginNotFound(KeyError)` - base exception for missing plugins
  - Define `PluginLoadError(RuntimeError)` - plugin failed to import
  - Define `PluginHealthCheckFailed(RuntimeError)` - health check failed
  - Define `PluginEnvVarMissing(EnvironmentError)` - required env var not set
  - Define `SandboxViolation(PermissionError)` - sandbox code tried live access
  - Define `DataSourceError(IOError)` - data source failed
  - Define `MarketProviderError(RuntimeError)` - market provider failed
  - Define `MarketProviderNotFound(KeyError)` - venue not found
  - Define `MarketProviderHasOpenPositions(RuntimeError)` - can't disable with positions
  - Define `OrderRejectedError(MarketProviderError)` - venue rejected order
  - Define `VenueUnavailableError(MarketProviderError)` - venue unreachable
  - Add comprehensive documentation for each exception
  - Export all in `backend/core/__init__.py`

  **Test cases**:
  - Import all exceptions from `backend.core.plugin_errors`
  - Each exception is distinguishable by type
  - Exceptions inherit from correct base classes

  **Must NOT do**:
  - Do not implement exception handling logic here
  - Do not import from plugin_registry (circular dependency risk)
  - Do not define custom exception methods (keep simple)

  **Recommended Agent Profile**:
  > - **Category**: `quick` - Exception file creation
  > - **Skills**: `git-master`, `verification-before-completion`
  > - **Skills Evaluated but Omitted**: None (simple file)

  **Parallelization**:
  - **Can Run In Parallel**: YES - Independent task
  - **Parallel Group**: Wave 1 independent tasks
  - **Blocks**: Task 9 (provider_registry imports from this)
  - **Blocked By**: None

  **References**:
  - **Pattern References**: `backend/ai/base.py:BaseAIClient` - similar exception pattern

  **Acceptance Criteria**:
  - [x] All 11 exception types defined
  - [x] All exceptions importable from `backend.core.plugin_errors`
  - [x] `pytest backend/tests/test_plugin_errors.py::test_inheritance` → PASS
  - [x] No linter errors

  **QA Scenarios**:

  \`\`\`
  Scenario: All exceptions importable and distinguishable
    Tool: bash
    Steps:
      1. Run python -c "from backend.core.plugin_errors import *; print('OK')"
      2. Verify each exception is distinct type (try/except on each)
    Expected Result: Prints OK, no duplicate type errors
    Evidence: .sisyphus/evidence/task-02-import-exceptions.sh
  \`\`\`

- [x] 3. Create `backend/ai/base_provider.py` - AI provider abstract base

  **What to do**:
  - Create `ProviderManifest` dataclass with all fields from spec
  - Create `BaseAIProvider` abstract base class
  - Implement `manifest()` classmethod as abstract
  - Implement `complete()` abstract with all parameters from spec
  - Implement `health_check()` with default timeout and fallback mechanism
  - Implement `teardown()` empty default (providers can override)
  - Add type hints for all methods
  - Export in `backend/ai/__init__.py`

  **Test cases**:
  - Define test provider subclass and instantiate
  - Call manifest() → returns ProviderManifest with correct fields
  - Call complete() → raises NotImplementedError (abstract method)
  - Call health_check() → default implementation works
  - Call teardown() → default implementation doesn't raise

  **Must NOT do**:
  - Do not implement specific provider logic (Claude, Groq, etc.)
  - Do not import from registry (should be importable before registry exists)
  - Do not include any actual API calls (no anthropic, groq imports)

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Abstract base with complex type hints
  > - **Skills**: `git-master`, `verification-before-completion`
  > - **Skills Evaluated but Omitted**: None

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 1
  - **Parallel Group**: Wave 1 tasks (3, 5, 7)
  - **Blocks**: Tasks 4, 10, 11, 12 (registry and providers depend on this)
  - **Blocked By**: Task 1 (registry base)

  **References**:
  - **Pattern References**: `backend/ai/base.py:BaseAIClient` - existing base class

  **Acceptance Criteria**:
  - [x] `ProviderManifest` dataclass with all required fields
  - [x] `BaseAIProvider` abstract base with all abstract methods
  - [x] Provider without abstract method implementation raises proper error
  - [x] `pytest backend/tests/test_ai_base.py::test_abstract_class` → PASS

- [x] 4. Create `backend/ai/provider_registry.py` - AI provider registry

  **What to do**:
  - Subclass `PluginRegistry[ProviderManifest, BaseAIProvider]`
  - Create module-level singleton `provider_registry = ProviderRegistry()`
  - Implement `register()` - validates manifest, checks env vars, instantiates
  - Implement `get()` - returns provider instance by name
  - Implement `list_available()` - returns only healthy providers
  - Implement `set_enabled(name, enabled)` - persists to BotState
  - Implement `auto_discover(package_path)` - imports providers/ directory
  - Implement `get_best_provider(tags)` - filter by tags, prefer healthy
  - Implement background health check loop (call health_check every 60s)
  - On health failure: log, mark degraded, emit Prometheus counter
  - Add to `backend/ai/__init__.py`

  **Test cases**:
  - Register provider with missing env var → raises `PluginEnvVarMissing`
  - Register provider with invalid base class → raises `TypeError`
  - Get healthy provider → returns instance
  - Get unhealthy provider → raises `PluginNotFound`
  - Set enabled/disabled → writes to BotState.misc_data
  - Health check loop marks provider degraded on failure
  - `get_best_provider(tags)` filters correctly

  **Must NOT do**:
  - Do not import specific providers (should work before any providers exist)
  - Do not run health check loop in background during test execution
  - Do not connect to live APIs (no anthropic, groq calls)

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Complex registry with background loop
  > - **Skills**: `git-master`, `test-driven-development`, `verification-before-completion`
  > - **Skills Evaluated but Omitted**: None

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 2
  - **Parallel Group**: Wave 2 tasks
  - **Blocks**: Tasks 10, 11, 12, 23 (providers and registry depend on this)
  - **Blocked By**: Task 1, Task 3

  **References**:
  - **Pattern References**: `backend/ai/ensemble.py:ensemble.py` - current hard-coded implementation
  - **API References**: `backend/models/bot_state.py:BotState.misc_data` - storage location

  **Acceptance Criteria**:
  - [x] Registry loads existing providers (claude, groq) from their files
  - [x] Health check loop runs in background, marks degraded on failure
  - [x] `pytest backend/tests/test_ai_provider_registry.py` → PASS (all 6 tests)

- [x] 5. Create `backend/data/base_source.py` - Data source abstract base

  **What to do**:
  - Create `DataType` enum with all data types from spec
  - Create `DataSourceManifest` dataclass with all fields
  - Create `BaseDataSource` abstract base class
  - Implement `manifest()` abstract
  - Implement `fetch()` abstract with data_type and params
  - Implement `stream()` with NotImplementedError default (optional)
  - Implement `backfill()` with NotImplementedError default (optional)
  - Implement `health_check()` with default implementation
  - Implement `teardown()` empty default
  - Export in `backend/data/__init__.py`

  **Test cases**:
  - Define test data source subclass and instantiate
  - Call manifest() → returns DataSourceManifest with correct fields
  - Call fetch() → raises NotImplementedError (abstract method)
  - Call stream() → raises NotImplementedError (optional)
  - Call backfill() → raises NotImplementedError (optional)
  - Call health_check() → default implementation works

  **Must NOT do**:
  - Do not implement specific data sources (polymarket, kalshi, etc.)
  - Do not import from registry or database
  - Do not include any actual API calls

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Abstract base with complex type hints
  > - **Skills**: `git-master`, `verification-before-completion`
  > - **Skills Evaluated but Omitted**: None

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 1
  - **Parallel Group**: Wave 1 tasks (3, 5, 7)
  - **Blocks**: Tasks 16, 17, 18, 23 (sources and registry depend on this)
  - **Blocked By**: Task 1

  **References**:
  - **Pattern References**: `backend/data/provider.py:DataProvider` - existing interface

  **Acceptance Criteria**:
  - [x] `DataType` enum with all required data types
  - [x] `DataSourceManifest` dataclass complete
  - [x] `BaseDataSource` abstract base with all abstract methods
  - [x] `pytest backend/tests/test_data_base.py` → PASS

- [x] 6. Create `backend/data/source_registry.py` - Data source registry

  **What to do**:
  - Subclass `PluginRegistry[DataSourceManifest, BaseDataSource]`
  - Create module-level singleton `source_registry = DataSourceRegistry()`
  - Implement `register()` - validates manifest, checks env vars, instantiates
  - Implement `get(name)` - returns data source instance
  - Implement `get_for_type(data_type)` - returns all sources for data type
  - Implement `list_all()` - returns all manifests
  - Implement `set_enabled(name, enabled)` - persists to BotState
  - Implement `auto_discover(package_path)` - imports sources/ directory
  - Implement background health check loop (every 30 seconds)
  - On health failure: log, mark degraded, emit Prometheus counter
  - Add to `backend/data/__init__.py`

  **Test cases**:
  - Register valid data source → succeeds
  - Register data source with missing env var → raises `PluginEnvVarMissing`
  - Get data source for type → returns list of healthy sources
  - Set enabled/disabled → persists to BotState
  - Health check loop marks degraded on failure
  - Auto-discover loads all sources in directory

  **Must NOT do**:
  - Do not import specific data sources
  - Do not run health check loop in tests
  - Do not connect to live APIs

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Registry with filtering logic
  > - **Skills**: `git-master`, `test-driven-development`, `verification-before-completion`
  > - **Skills Evaluated but Omitted**: None

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 3
  - **Parallel Group**: Wave 3 tasks
  - **Blocks**: Tasks 16, 17, 18, 19, 21, 22 (sources and API depend on this)
  - **Blocked By**: Task 1, Task 5

  **References**:
  - **Pattern References**: `backend/data/market_universe.py:MarketUniverseScanner` - existing scanner

  **Acceptance Criteria**:
  - [x] Registry implements all required methods
  - [x] `get_for_type()` filters correctly by data type
  - [x] Health check loop runs correctly
  - [x] `pytest backend/tests/test_data_registry.py` → PASS

- [x] 7. Create `backend/markets/order_types.py` - Normalized order dataclasses

  **What to do**:
  - Create `OrderSide` enum (YES, NO, BUY, SELL)
  - Create `OrderType` enum (MARKET, LIMIT, FOK, IOC)
  - Create `OrderStatus` enum (PENDING, OPEN, PARTIAL, FILLED, CANCELLED, REJECTED, EXPIRED)
  - Create `PositionSide` enum (LONG, SHORT)
  - Create `NormalizedOrder` dataclass with all fields
  - Create `NormalizedOrderResult` dataclass with all fields
  - Create `NormalizedPosition` dataclass with all fields
  - Create `NormalizedBalance` dataclass with all fields
  - Create `NormalizedFillEvent` dataclass with all fields
  - Create `MarketInfo` dataclass with all fields
  - Export in `backend/markets/__init__.py`

  **Test cases**:
  - All enums have correct values
  - All dataclasses instantiate correctly
  - Dataclass fields match specification
  - Default factory functions work correctly

  **Must NOT do**:
  - Do not implement any provider logic (that's in base_provider.py)
  - Do not import from registry or providers
  - Do not include any API calls

  **Recommended Agent Profile**:
  > - **Category**: `quick` - Dataclasses only
  > - **Skills**: `git-master`, `verification-before-completion`
  > - **Skills Evaluated but Omitted**: None

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 1
  - **Parallel Group**: Wave 1 tasks (3, 5, 7)
  - **Blocks**: Task 8 (base_provider imports from this)
  - **Blocked By**: Task 1

  **References**:
  - **Pattern References**: `backend/models/__init__.py` - existing models pattern

  **Acceptance Criteria**:
  - [x] All enums defined with correct values
  - [x] All dataclasses created with all required fields
  - [x] `pytest backend/tests/test_order_types.py` → PASS

- [x] 8. Create `backend/markets/base_provider.py` - Market provider abstract base

  **What to do**:
  - Create `VenueCapability` enum (LIMIT_ORDERS, MARKET_ORDERS, FOK_ORDERS, SHORT_SELLING, STREAMING_FILLS, MARKET_SEARCH, BATCH_ORDERS)
  - Create `MarketProviderManifest` dataclass with all fields
  - Create `BaseMarketProvider` abstract base class
  - Implement `__init__()` to accept `paper_mode` parameter
  - Implement `manifest()` classmethod as abstract
  - Implement `place_order()` abstract (NormalizedOrder → NormalizedOrderResult)
  - Implement `cancel_order()` abstract (venue_order_id → bool)
  - Implement `cancel_all_orders()` with NotImplementedError default
  - Implement `get_order()` with NotImplementedError default
  - Implement `get_balance()` abstract
  - Implement `get_positions()` abstract (returns empty list if no positions)
  - Implement `get_market()` with NotImplementedError default
  - Implement `search_markets()` with NotImplementedError default
  - Implement `stream_fills()` with NotImplementedError default
  - Implement `health_check()` with default
  - Implement `teardown()` empty default
  - Export in `backend/markets/__init__.py`

  **Test cases**:
  - Instantiate base provider with paper_mode=True/False
  - Call manifest() → raises NotImplementedError
  - Call place_order() → raises NotImplementedError
  - Call get_positions() → raises NotImplementedError
  -health_check() → default implementation works

  **Must NOT do**:
  - Do not implement specific providers (polymarket, kalshi, paper)
  - Do not import from registry
  - Do not include any actual API calls

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Abstract base with complex interface
  > - **Skills**: `git-master`, `verification-before-completion`
  > - **Skills Evaluated but Omitted**: None

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 1
  - **Parallel Group**: Wave 1 tasks (3, 5, 7)
  - **Blocks**: Tasks 23, 25, 26 (providers and registry depend on this)
  - **Blocked By**: Task 1, Task 7

  **References**:
  - **Pattern References**: `backend/data/provider.py:DataProvider` - similar pattern

  **Acceptance Criteria**:
  - [x] All enums and dataclasses defined
  - [x] Base class abstract with all required methods
  - [x] `pytest backend/tests/test_market_base.py` → PASS

- [x] 9. Create `backend/ai/providers/__init__.py` - Auto-discover setup

  **What to do**:
  - Import `provider_registry` from `backend.ai.provider_registry`
  - Create `provider_registry` module-level instance if not exists
  - Add `@provider_registry.plugin` decorator to existing claude.py
  - Add `@provider_registry.plugin` decorator to existing groq.py
  - Import all modules in providers/ directory automatically via `importlib`
  - Add `from backend.ai.providers.claude_provider import ClaudeProvider`
  - Add `from backend.ai.providers.groq_provider import GroqProvider`
  - Export in `backend/ai/__init__.py`

  **Test cases**:
  - Import providers module → triggers auto-discovery
  - Registry contains claude and groq providers
  - Providers accessible via `provider_registry.list_available()`
  - Both providers healthy after import

  **Must NOT do**:
  - Do not re-implement claude/groq logic (just reference existing modules)
  - Do not break current imports in ensemble.py (backward compatibility)
  - Do not include live data (claude/groq api keys not set in tests)

  **Recommended Agent Profile**:
  > - **Category**: `quick` - Simple integration task
  > - **Skills**: `git-master`, `verification-before-completion`
  > - **Skills Evaluated but Omitted**: None

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 2
  - **Parallel Group**: Wave 2 tasks
  - **Blocks**: Task 14 (registry tests depend on providers)
  - **Blocked By**: Task 4 (registry must exist)

  **References**:
  - **Pattern References**: `backend/ai/__init__.py` - existing exports pattern

  **Acceptance Criteria**:
  - [x] Auto-discover imports all provider files
  - [x] Providers registered in registry
  - [x] `pytest backend/tests/test_ai_provider_registry.py::test_auto_discover` → PASS

- [x] 10. Create `backend/ai/providers/claude_provider.py` - Claude plugin

  **What to do**:
  - Create new file importing existing `claude.py` logic
  - Create `ClaudeProvider` class subclassing `BaseAIProvider`
  - Apply `@provider_registry.plugin` decorator
  - Implement `manifest()` → return ProviderManifest with claude details
  - Implement `complete()` → call existing Claude API
  - Add all required env vars to manifest
  - Export in `providers/__init__.py`

  **Test cases**:
  - ClaudeProvider instantiates correctly
  - Manifest has correct name, display_name, env vars
  - Complete method calls existing claude logic
  - Health check works with test API call

  **Must NOT do**:
  - Do not re-implement Claude API logic (reference existing module)
  - Do not copy-paste claude.py code (maintain single source)
  - Do not include API calls in tests (use fixtures)

  **Recommended Agent Profile**:
  > - **Category**: `quick` - Refactoring wrapper
  > - **Skills**: `git-master`, `verification-before-completion`
  > - **Skills Evaluated but Omitted**: None

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 2
  - **Parallel Group**: Wave 2 tasks
  - **Blocks**: Task 12 (ensemble refactor depends on this)
  - **Blocked By**: Task 4, Task 3

  **References**:
  - **Pattern References**: `backend/ai/claude.py` - source logic to wrap

  **Acceptance Criteria**:
  - [x] ClaudeProvider subclass of BaseAIProvider
  - [x] @provider_registry.plugin decorator applied
  - [x] Manifest has correct values
  - [x] Complete calls existing claude logic
  - [x] `pytest backend/tests/test_claude_provider.py` → PASS

- [x] 11. Create `backend/ai/providers/groq_provider.py` - Groq plugin

  **What to do**:
  - Create new file importing existing `groq.py` logic
  - Create `GroqProvider` class subclassing `BaseAIProvider`
  - Apply `@provider_registry.plugin` decorator
  - Implement `manifest()` → return ProviderManifest with groq details
  - Implement `complete()` → call existing Groq API
  - Add all required env vars to manifest
  - Export in `providers/__init__.py`

  **Test cases**:
  - Same as claude_provider tests

  **Must NOT do**:
  - Do not re-implement Groq API logic
  - Do not copy-paste groq.py code

  **Recommended Agent Profile**:
  > - **Category**: `quick` - Refactoring wrapper
  > - **Skills**: `git-master`, `verification-before-completion`
  > - **Skills Evaluated but Omitted**: None

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 2
  - **Parallel Group**: Wave 2 tasks
  - **Blocks**: Task 12 (ensemble refactor)
  - **Blocked By**: Task 4, Task 3

  **References**:
  - **Pattern References**: `backend/ai/groq.py` - source logic to wrap

  **Acceptance Criteria**:
  - [x] GroqProvider subclass of BaseAIProvider
  - [x] @provider_registry.plugin decorator
  - [x] Manifest correct
  - [x] Complete calls existing groq logic
  - [x] `pytest backend/tests/test_groq_provider.py` → PASS

- [x] 12. Refactor `backend/ai/ensemble.py` - Registry-based routing

  **What to do**:
  - Import `provider_registry` from `backend.ai.provider_registry`
  - Replace hard-coded imports (claude, groq) with registry lookups
  - Implement `get_best_provider(tags)` - filter by tags, prefer healthy
  - Update `ensemble_complete()` to iterate over registry providers
  - Catch exceptions from individual providers, skip failed ones
  - Add fallback chain logic (ordered fallback through healthy providers)
  - Add Prometheus histogram metrics for latency and cost
  - Respect `LLMCostTracker` - check budget before each call
  - Export in `backend/ai/__init__.py`

  **Test cases**:
  - Ensemble works with registry providers instead of hard-coded
  - Failed provider is skipped, fallback to healthy provider
  - Metrics emitted for each provider call
  - Cost tracker prevents calls over budget
  - Fallback chain works correctly

  **Must NOT do**:
  - Do not remove ensemble functionality (must preserve existing behavior)
  - Do not break current strategy imports
  - Do not include API calls in tests (use fixtures)

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Complex refactoring
  > - **Skills**: `git-master`, `test-driven-development`, `verification-before-completion`
  > - **Skills Evaluated but Omitted**: None

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 2
  - **Parallel Group**: Wave 2 task (12)
  - **Blocks**: None (finalizes AI provider system)
  - **Blocked By**: Tasks 10, 11 (providers must exist)

  **References**:
  - **Pattern References**: `backend/ai/ensemble.py` - current implementation
  - **API References**: `backend/monitoring/` - Prometheus metrics

  **Acceptance Criteria**:
  - [x] Ensemble reads providers from registry
  - [x] Failed providers skipped gracefully
  - [x] Metrics emitted correctly
  - [x] Cost tracker enforced
  - [x] `pytest backend/tests/test_ensemble_registry.py` → PASS

- [x] 13. Create `backend/api/v1/ai_providers.py` - AI provider API endpoints

  **What to do**:
  - Create new FastAPI router `ai_providers.py`
  - Implement GET `/api/v1/ai/providers` - list all providers with health status
  - Implement POST `/api/v1/ai/providers/{name}/enable` - enable provider
  - Implement POST `/api/v1/ai/providers/{name}/disable` - disable provider
  - Implement GET `/api/v1/ai/providers/{name}/health` - immediate health check
  - Add proper authentication (admin_session or ADMIN_API_KEY)
  - Add to `backend/api/v1/__init__.py`

  **Test cases**:
  - GET /api/v1/ai/providers returns all providers with health status
  - POST /api/v1/ai/providers/{name}/enable enables provider
  - POST /api/v1/ai/providers/{name}/disable disables provider
  - GET /api/v1/ai/providers/{name}/health returns health status

  **Must NOT do**:
  - Do not implement business logic (delegate to registry)
  - Do not bypass registry (always use provider_registry)
  - Do not include API calls in tests (use mock decorators)

  **Recommended Agent Profile**:
  > - **Category**: `quick` - API endpoints only
  > - **Skills**: `git-master`, `verification-before-completion`
  > - **Skills Evaluated but Omitted**: None

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 2
  - **Parallel Group**: Wave 2 task (13)
  - **Blocks**: Frontend API client (task 68)
  - **Blocked By**: None (can be done in parallel with backend)

  **References**:
  - **Pattern References**: `backend/api/v1/` - existing API structure
  - **API References**: `backend/models/auth.py` - admin auth pattern

  **Acceptance Criteria**:
  - [x] All 4 endpoints implemented
  - [x] Authentication required
  - [x] Response models match spec
  - [x] `pytest backend/tests/test_ai_provider_api.py` → PASS

### Wave 2: AI Provider System Complete (Tasks 14)

- [x] 14. Create `backend/tests/test_ai_provider_registry.py` - Unit tests

  **What to do**:
  - Create test file with 6 test functions
  - Test `test_register_valid_plugin` - happy path
  - Test `test_register_invalid_env_var` - raises PluginEnvVarMissing
  - Test `test_auto_discover_loads_all` - imports providers/
  - Test `test_set_enabled_persists` - writes to BotState
  - Test `test_health_check_marks_degraded` - mock failure
  - Test `test_get_missing_plugin` - raises PluginNotFound

  **Test cases**:
  - All 6 tests pass with SHADOW_MODE=true
  - No API calls (mock all external dependencies)
  - Registry state isolated per test

  **Must NOT do**:
  - Do not run live API calls
  - Do not share state between tests
  - Do not depend on external services

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Full test suite
  > - **Skills**: `git-master`, `test-driven-development`, `verification-before-completion`
  > - **Skills Evaluated but Omitted**: None

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 2
  - **Parallel Group**: Wave 2 task (14)
  - **Blocks**: None (completes AI provider system)
  - **Blocked By**: Tasks 10, 11, 12, 13 (registry and API must exist)

  **References**:
  - **Pattern References**: `backend/tests/test_base.py` - existing test structure

  **Acceptance Criteria**:
  - [x] All 6 tests pass
  - [x] No live API calls
  - [x] `pytest backend/tests/test_ai_provider_registry.py` → PASS (6/6)

### Wave 3: Data Source System (Tasks 15-22)

- [x] 15. Create `backend/data/sources/__init__.py` - Auto-discover setup

  **What to do**:
  - Import `source_registry` from `backend.data.source_registry`
  - Add all data source imports to auto-discover
  - Export in `backend/data/__init__.py`

  **Test cases**:
  - Auto-discover loads all sources
  - Sources registered in registry

  **Recommended Agent Profile**:
  > - **Category**: `quick` - Import setup
  > - **Skills**: `git-master`
  > - **Skills Evaluated but Omitted**: None

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 3
  - **Parallel Group**: Wave 3 tasks
  - **Blocks**: Task 22 (tests)
  - **Blocked By**: Task 6 (registry)

- [x] 16. Create `backend/data/sources/polymarket_source.py` - Polymarket plugin

  **What to do**:
  - Create `PolymarketSource` subclass of `BaseDataSource`
  - Apply `@source_registry.plugin` decorator
  - Implement `manifest()` with polymarket details
  - Implement `fetch()` using existing polymarket_clob logic
  - Add required env vars to manifest
  - Export in `sources/__init__.py`

  **Test cases**:
  - PolymarketSource instantiates
  - Manifest correct
  - Fetch method calls existing logic

  **Recommended Agent Profile**:
  > - **Category**: `quick` - Wrapper implementation
  > - **Skills**: `git-master`
  > - **Skills Evaluated but Omitted**: None

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 3
  - **Parallel Group**: Wave 3 tasks
  - **Blocks**: Task 20 (strategy context)
  - **Blocked By**: Task 6, Task 15

- [x] 17. Create `backend/data/sources/kalshi_source.py` - Kalshi plugin

  **What to do**:
  - Create `KalshiSource` subclass of `BaseDataSource`
  - Apply `@source_registry.plugin` decorator
  - Implement `manifest()` with kalshi details
  - Implement `fetch()` using existing kalshi_client logic
  - Add required env vars to manifest
  - Export in `sources/__init__.py`

  **Test cases**:
  - KalshiSource instantiates
  - Manifest correct
  - Fetch method calls existing logic

  **Recommended Agent Profile**:
  > - **Category**: `quick` - Wrapper implementation
  > - **Skills**: `git-master`
  > - **Skills Evaluated but Omitted**: None

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 3
  - **Parallel Group**: Wave 3 tasks
  - **Blocks**: Task 20 (strategy context)
  - **Blocked By**: Task 6, Task 15

- [x] 18. Create `backend/data/sources/mock_source.py` - Mock data source

  **What to do**:
  - Create `MockDataSource` subclass of `BaseDataSource`
  - Apply `@source_registry.plugin` decorator
  - Implement `manifest()` with `is_live=False`
  - Implement `fetch()` with deterministic mock data
  - Implement `stream()` with async generator
  - Implement `backfill()` with deterministic historical data
  - Add configurable via `MockDataConfig`
  - Export in `sources/__init__.py`

  **Test cases**:
  - MockSource works in sandbox
  - Deterministic data with fixed seed
  - Streaming returns expected events
  - Backfill returns historical data

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Mock data generation
  > - **Skills**: `test-driven-development`
  > - **Skills Evaluated but Omitted**: None

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 3
  - **Parallel Group**: Wave 3 tasks
  - **Blocks**: Task 19 (registry)
  - **Blocked By**: Task 6, Task 15

- [x] 19. Create `backend/data/market_universe.py` - Update to use registry

  **What to do**:
  - Import `source_registry` from `backend.data.source_registry`
  - Replace direct data client instantiation with registry lookups
  - Use `source_registry.get_for_type(DataType.MARKET_META)` for market discovery
  - Update `MarketUniverseScanner.scan()` to use registry
  - Export in `backend/data/__init__.py`

  **Test cases**:
  - Universe scanner uses registry
  - Returns markets from all registered sources

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Integration refactoring
  > - **Skills**: `test-driven-development`
  > - **Skills Evaluated but Omitted**: None

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 3
  - **Parallel Group**: Wave 3 task (19)
  - **Blocks**: None
  - **Blocked By**: Task 6, Tasks 16, 17, 18

- [x] 20. Update `backend/strategies/base.py` - Add data_registry to StrategyContext

  **What to do**:
  - Import `DataSourceRegistry` from `backend.data.source_registry`
  - Add `data_registry: DataSourceRegistry` field to `StrategyContext`
  - Inject data_registry via strategy_executor
  - Update existing strategies to access data through registry
  - Export in `backend/strategies/__init__.py`

  **Test cases**:
  - StrategyContext has data_registry field
  - Strategies can fetch data through registry
  - Sandbox gets mock data registry

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Context refactoring
  > - **Skills**: `test-driven-development`
  > - **Skills Evaluated but Omitted**: None

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 3
  - **Parallel Group**: Wave 3 tasks
  - **Blocks**: Task 22 (integration tests)
  - **Blocked By**: Task 6, Task 19

- [x] 21. Create `backend/api/v1/data_sources.py` - Data source API endpoints

  **What to do**:
  - Create new FastAPI router
  - Implement GET `/api/v1/data/sources`
  - Implement POST `/api/v1/data/sources/{name}/enable`
  - Implement POST `/api/v1/data/sources/{name}/disable`
  - Implement GET `/api/v1/data/sources/{name}/health`
  - Implement GET `/api/v1/data/sources/{name}/types`
  - Add to `backend/api/v1/__init__.py`

  **Test cases**:
  - All endpoints functional
  - Authentication required

  **Recommended Agent Profile**:
  > - **Category**: `quick` - API endpoints
  > - **Skills**: `git-master`
  > - **Skills Evaluated but Omitted**: None

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 3
  - **Parallel Group**: Wave 3 task (21)
  - **Blocks**: Frontend API client (task 69)
  - **Blocked By**: None

- [x] 22. Create `backend/tests/test_data_source_registry.py` - Unit tests

  **What to do**:
  - Create test file with test functions
  - Test registration, auto-discovery, health checks
  - Test Get-For-Type filtering
  - Test mock source in sandbox

  **Test cases**:
  - All tests pass with SHADOW_MODE=true

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Full test suite
  > - **Skills**: `test-driven-development`
  > - **Skills Evaluated but Omitted**: None

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 3
  - **Parallel Group**: Wave 3 task (22)
  - **Blocks**: None
  - **Blocked By**: Task 16, 17, 18, 19, 20, 21

### Wave 4: Market Provider System (Tasks 23-32)

- [x] 23. Create `backend/markets/provider_registry.py` - Market provider registry

  **What to do**:
  - Subclass `PluginRegistry[MarketProviderManifest, BaseMarketProvider]`
  - Create singleton `market_registry`
  - Implement `register()` with paper_mode injection
  - Implement `get(name)`, `get_live_venues()`, `get_paper_venues()`
  - Implement `set_enabled()` with open positions check
  - Implement background health check loop (every 15s)
  - On failure: notify notification router
  - Export in `backend/markets/__init__.py`

  **Test cases**:
  - Registry instantiates with paper_mode
  - Live/paper venue filtering works
  - Disabled with positions raises exception
  - Force disable works
  - Health check loop marks degraded

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Complex registry
  > - **Skills**: `test-driven-development`
  > - **Skills Evaluated but Omitted**: None

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 4
  - **Parallel Group**: Wave 4 tasks
  - **Blocks**: Tasks 25, 26, 27, 28 (providers and executor)
  - **Blocked By**: Task 1, Task 7, Task 8

- [x] 24. Create `backend/markets/providers/__init__.py` - Auto-discover

  **What to do**:
  - Import `market_registry`
  - Auto-discover all providers in providers/ directory
  - Export in `backend/markets/__init__.py`

  **Test cases**:
  - Auto-discover loads providers

  **Recommended Agent Profile**:
  > - **Category**: `quick` - Import setup
  > - **Skills**: `git-master`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 4
  - **Parallel Group**: Wave 4 tasks
  - **Blocks**: Task 32 (tests)
  - **Blocked By**: Task 23

- [x] 25. Create `backend/markets/providers/polymarket_provider.py` - Polymarket plugin

  **What to do**:
  - Create `PolymarketProvider` subclass of `BaseMarketProvider`
  - Apply `@market_registry.plugin` decorator
  - Implement `manifest()` with polymarket details
  - Implement `place_order()` using existing CLOB client logic
  - Implement `cancel_order()`, `get_positions()`, `get_balance()`
  - Implement `stream_fills()` as async generator
  - Export in `providers/__init__.py`

  **Test cases**:
  - PolymarketProvider instantiates
  - Manifest correct
  - Order lifecycle works

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Full provider implementation
  > - **Skills**: `test-driven-development`
  > - **Skills Evaluated but Omitted**: None

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 4
  - **Parallel Group**: Wave 4 tasks
  - **Blocks**: Task 28, 30 (executor and API)
  - **Blocked By**: Task 23, Task 24

- [x] 26. Create `backend/markets/providers/kalshi_provider.py` - Kalshi plugin

  **What to do**:
  - Create `KalshiProvider` subclass of `BaseMarketProvider`
  - Apply `@market_registry.plugin` decorator
  - Implement `manifest()` with kalshi details
  - Implement price normalization (cents to fractions)
  - Implement all required methods
  - Export in `providers/__init__.py`

  **Test cases**:
  - KalshiProvider instantiates
  - Price normalization correct

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Provider with normalization
  > - **Skills**: `test-driven-development`
  > - **Skills Evaluated but Omitted**: None

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 4
  - **Parallel Group**: Wave 4 tasks
  - **Blocks**: Task 28, 30
  - **Blocked By**: Task 23, Task 24

- [x] 26a. Create `backend/clients/azuro_client.py` - Shared Azuro Protocol client

  **What to do**:
  - Create `AzuroClient` with async GraphQL query support (via `httpx`)
  - `__init__(self, graph_url: str, rpc_url: str, chain_id: int)` — read from env: `AZURO_GRAPH_URL`, `AZURO_RPC_URL`, `AZURO_CHAIN_ID`
  - `async cached_query(self, gql: str, variables: dict = None) -> dict` — TTL cache (`AZURO_CACHE_TTL_SECONDS`, default 60 s); handle 429 with `Retry-After`
  - `async get_markets(self, limit: int = 200, active_only: bool = True) -> list[dict]` — query Azuro subgraph; normalize to standard market dict keys
  - `async health_check(self) -> bool` — lightweight introspection query
  - `async sign_and_send_bet(self, private_key: str, condition_id: str, outcome_index: int, amount_wei: int) -> str` — EVM smart contract call via `web3.py`; return tx hash
  - Default `AZURO_GRAPH_URL`: `https://api.thegraph.com/subgraphs/name/azuro-protocol/azuro-subgraph-xdai`
  - Update `backend/clients/__init__.py` to export `AzuroClient`: add `from .azuro_client import AzuroClient` and include in `__all__`

  **Test cases**:
  - `cached_query()` makes only 1 HTTP call for 2 requests within TTL
  - `health_check()` returns True with mock 200 response
  - `sign_and_send_bet()` calls Web3 without leaking private key to logs

  **Must NOT do**:
  - Do NOT call The Graph without caching (hot-path protection)
  - Do NOT log or persist private key

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Async client with cache and Web3 signing
  > - **Skills**: `test-driven-development`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 4 (no plugin-system deps)
  - **Parallel Group**: Wave 4 tasks (runs alongside Tasks 25, 26, 26d, 26e)
  - **Blocks**: Tasks 26b, 26c
  - **Blocked By**: None (standalone client)

  **References**:
  - `backend/data/polymarket_clob.py` — async httpx client pattern
  - Azuro subgraph: `https://api.thegraph.com/subgraphs/name/azuro-protocol/azuro-subgraph-xdai`
  - `backend/config.py` — env var registration pattern

  **QA Scenarios**:
  ```
  Scenario: Cache prevents double HTTP call
    Tool: Bash (pytest)
    Steps:
      1. pytest backend/tests/test_azuro_client.py::test_cache_ttl -v
    Expected Result: PASSED
    Evidence: .sisyphus/evidence/task-26a-cache.txt
  ```

- [x] 26b. Create `backend/markets/providers/predict_fun_provider.py` - predict.fun via Azuro

  **What to do**:
  - Create `PredictFunProvider(BaseMarketProvider)` with `@market_registry.plugin`
  - `manifest()` → name=`"predict_fun"`, platform_url=`"https://predict.fun"`, `is_live_venue=True`
  - Delegates all data fetching to `AzuroClient` singleton
  - `place_order()` calls `AzuroClient.sign_and_send_bet()`
  - `cancel_order()` raises `OrderRejectedError("Azuro bets are non-cancellable")`
  - `is_paper()` based on `SHADOW_MODE`

  **Test cases**:
  - `get_name()` → `"predict_fun"`
  - `cancel_order()` raises `OrderRejectedError`
  - `get_markets()` delegates to `AzuroClient.get_markets()`

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high`
  > - **Skills**: `test-driven-development`

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 4, alongside 26c)
  - **Blocks**: Task 31
  - **Blocked By**: Task 26a

  **QA Scenarios**:
  ```
  Scenario: Provider registered with correct name
    Tool: Bash (pytest)
    Steps:
      1. pytest backend/tests/test_market_provider_registry.py::test_predict_fun_registered -v
    Expected Result: PASSED
    Evidence: .sisyphus/evidence/task-26b-registered.txt
  ```

- [x] 26c. Create `backend/markets/providers/bookmaker_xyz_provider.py` - bookmaker.xyz via Azuro

  **What to do**:
  - Create `BookmakerXyzProvider(BaseMarketProvider)` with `@market_registry.plugin`
  - Mirror structure of `PredictFunProvider`; only change: name=`"bookmaker_xyz"`, platform_url=`"https://bookmaker.xyz"`
  - Shares `AzuroClient` singleton with `PredictFunProvider` (verify by identity in test)

  **Test cases**:
  - `get_name()` → `"bookmaker_xyz"`
  - Shares `AzuroClient` instance with `PredictFunProvider`

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high`
  > - **Skills**: `test-driven-development`

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 4, alongside 26b)
  - **Blocks**: Task 31
  - **Blocked By**: Task 26a

  **QA Scenarios**:
  ```
  Scenario: bookmaker_xyz and predict_fun share AzuroClient
    Tool: Bash (pytest)
    Steps:
      1. pytest backend/tests/test_market_provider_registry.py::test_azuro_client_singleton -v
    Expected Result: PASSED — both providers return same AzuroClient id()
    Evidence: .sisyphus/evidence/task-26c-singleton.txt
  ```

- [x] 26d. Create `backend/clients/limitless_client.py` + `limitless_provider.py` - limitless.exchange

  **What to do**:
  - Create `backend/clients/limitless_client.py`:
    - `LimitlessClient` with base URL from `LIMITLESS_API_URL` (default `https://api.limitless.exchange`)
    - `async get_markets(self, limit: int = 100) -> list[dict]` — `GET /markets`
    - `async get_orderbook(self, market_id: str) -> dict` — `GET /orderbook`
    - `async place_order(self, market_id: str, side: str, size: float, price: float, private_key: str) -> dict` — EIP-712 sign + `POST /orders`
    - `async cancel_order(self, order_id: str, private_key: str) -> bool`
    - `async health_check(self) -> bool` — `GET /markets?limit=1`
  - Update `backend/clients/__init__.py` to export `LimitlessClient`: add `from .limitless_client import LimitlessClient` and include in `__all__`
  - Create `backend/markets/providers/limitless_provider.py`:
    - `LimitlessProvider(BaseMarketProvider)` with `@market_registry.plugin`
    - name=`"limitless"`, `is_live_venue=True`
    - Pulls `LIMITLESS_PRIVATE_KEY` from env for signing

  **Test cases**:
  - `LimitlessProvider.get_name()` → `"limitless"`
  - `LimitlessClient.health_check()` returns True with mock 200
  - `place_order()` signs and POSTs correctly (mocked)

  **Must NOT do**:
  - Do NOT log the private key
  - Do NOT use synchronous `requests` library

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high`
  > - **Skills**: `test-driven-development`

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 4, independent of Azuro tasks)
  - **Blocks**: Task 31
  - **Blocked By**: Task 23, Task 24

  **References**:
  - `backend/clients/kalshi_client.py` — REST client pattern
  - Limitless API Swagger: `https://api.limitless.exchange/api-v1`

  **QA Scenarios**:
  ```
  Scenario: LimitlessProvider registered
    Tool: Bash (pytest)
    Steps:
      1. pytest backend/tests/test_market_provider_registry.py::test_limitless_registered -v
    Expected Result: PASSED
    Evidence: .sisyphus/evidence/task-26d-registered.txt
  ```

- [x] 26e. Create `backend/clients/sxbet_client.py` + `sxbet_provider.py` - sx.bet

  **What to do**:
  - Create `backend/clients/sxbet_client.py`:
    - `SXBetClient` with base URL from `SXBET_API_URL` (default `https://api.sx.bet`)
    - `async get_sports(self) -> list[dict]` — `GET /sports`
    - `async get_markets(self, sport_ids: list[int] = None, limit: int = 200) -> list[dict]` — `GET /markets/active`; normalize to standard dict
    - `async get_orderbook(self, market_hash: str) -> dict` — `GET /orders?marketHashes={hash}`
    - `async place_maker_order(self, market_hash: str, outcome_index: int, odds: float, stake_wei: int, private_key: str) -> dict` — EIP-712 sign + `POST /orders/new`
    - `async health_check(self) -> bool` — `GET /sports`
  - Update `backend/clients/__init__.py` to export `SXBetClient`: add `from .sxbet_client import SXBetClient` and include in `__all__`
  - Create `backend/markets/providers/sxbet_provider.py`:
    - `SXBetProvider(BaseMarketProvider)` with `@market_registry.plugin`
    - name=`"sxbet"`, `is_live_venue=True`
    - Pulls `SXBET_PRIVATE_KEY` from env

  **Test cases**:
  - `SXBetProvider.get_name()` → `"sxbet"`
  - `SXBetClient.health_check()` True with mock 200
  - `place_maker_order()` signs correctly (mocked)

  **Must NOT do**:
  - Do NOT log private key
  - Do NOT block event loop with synchronous Web3 calls

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high`
  > - **Skills**: `test-driven-development`

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 4, independent of Azuro tasks)
  - **Blocks**: Task 31
  - **Blocked By**: Task 23, Task 24

  **References**:
  - `backend/clients/limitless_client.py` (Task 26d) — similar REST + EIP-712 pattern
  - SX.Bet API docs: `https://docs.sx.bet/`

  **QA Scenarios**:
  ```
  Scenario: SXBetProvider registered
    Tool: Bash (pytest)
    Steps:
      1. pytest backend/tests/test_market_provider_registry.py::test_sxbet_registered -v
    Expected Result: PASSED
    Evidence: .sisyphus/evidence/task-26e-registered.txt
  ```

  **What to do**:
  - Create `PaperProvider` subclass of `BaseMarketProvider`
  - Apply `@market_registry.plugin` decorator
  - Implement `manifest()` with `is_live_venue=False`
  - Implement order book (in-memory dict)
  - Implement `place_order()` with fill simulation
  - Implement `cancel_order()` to remove from order book
  - Implement `get_positions()` from order book
  - Implement `get_balance()` with initial balance
  - Implement `stream_fills()` with async queue
  - Apply slippage model from config
  - Export in `providers/__init__.py`

  **Test cases**:
  - MARKET order fills immediately
  - LIMIT order fills on price crossing
  - Slippage applied correctly
  - Balance decrements on fill
  - Cancel removes from order book

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Complex order simulation
  > - **Skills**: `test-driven-development`
  > - **Skills Evaluated but Omitted**: None

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 4
  - **Parallel Group**: Wave 4 tasks
  - **Blocks**: Task 32 (tests)
  - **Blocked By**: Task 23, Task 24

- [x] 28. Refactor `backend/strategies/order_executor.py` - Use market registry

  **What to do**:
  - Import `market_registry`
  - Replace direct CLOB/kalshi calls with `market_registry.get(venue)`
  - Use `place_order()` with `NormalizedOrder`
  - Apply RiskManager validation before calling provider
  - Apply TradeAttemptRecorder before calling provider
  - Handle `SHADOW_MODE=true` to route to paper provider
  - Record result via TradeAttemptRecorder
  - Export in `backend/strategies/__init__.py`

  **Test cases**:
  - Executor uses registry for all order placement
  - RiskManager validated before venue calls
  - Shadow mode routes to paper provider
  - TradeAttempt recorded for all attempts

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Executor refactoring
  > - **Skills**: `test-driven-development`
  > - **Skills Evaluated but Omitted**: None

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 4
  - **Parallel Group**: Wave 4 task (28)
  - **Blocks**: Task 30, 32
  - **Blocked By**: Tasks 25, 26, 27, 23

- [x] 29. Update `backend/core/settlement.py` - Use registry stream

  **What to do**:
  - Import `market_registry`
  - Replace direct CLOB/kalshi polling with `market_registry.stream_all_fills()`
  - Implement `stream_all_fills()` as multiplexed async generator
  - Run all providers' `stream_fills()` concurrently with gather
  - On stream drop: log, mark degraded, reconnect with backoff
  - Export in `backend/core/__init__.py`

  **Test cases**:
  - Settlement consumes fills from registry
  - Multi-provider streaming works
  - Reconnection on stream drop

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Settlement integration
  > - **Skills**: `test-driven-development`
  > - **Skills Evaluated but Omitted**: None

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 4
  - **Parallel Group**: Wave 4 task (29)
  - **Blocks**: Task 32 (integration tests)
  - **Blocked By**: Tasks 25, 26, 27, 28

- [x] 30. Create `backend/api/v1/market_providers.py` - Market provider API

  **What to do**:
  - Create new FastAPI router
  - Implement GET `/api/v1/markets/providers`
  - Implement GET `/api/v1/markets/providers/{name}/balance`
  - Implement GET `/api/v1/markets/providers/{name}/positions`
  - Implement POST `/api/v1/markets/providers/{name}/enable`
  - Implement POST `/api/v1/markets/providers/{name}/disable`
  - Implement POST `/api/v1/markets/providers/{name}/disable?force=true`
  - Implement GET `/api/v1/markets/providers/{name}/markets`
  - Implement POST `/api/v1/markets/order`
  - Implement DELETE `/api/v1/markets/order/{venue}/{order_id}`
  - Implement GET `/api/v1/markets/positions` (aggregate)
  - Implement GET `/api/v1/markets/balance` (aggregate)
  - Add to `backend/api/v1/__init__.py`

  **Test cases**:
  - All endpoints functional
  - Authentication required
  - Force disable works correctly

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Comprehensive API
  > - **Skills**: `git-master`
  > - **Skills Evaluated but Omitted**: None

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 4
  - **Parallel Group**: Wave 4 task (30)
  - **Blocks**: Frontend API client (task 70)
  - **Blocked By**: None

- [x] 31. Create `backend/api/v1/market_orders.py` - Order management API

  **What to do**:
  - Create new FastAPI router for order endpoints
  - Implement POST `/api/v1/markets/order` - place order
  - Implement DELETE `/api/v1/markets/order/{venue}/{order_id}` - cancel
  - Implement GET `/api/v1/markets/order/{venue}/{order_id}` - get status
  - Add router to `backend/api/main.py`: `app.include_router(market_orders_router, prefix="/api/v1")`
  - Import the router at top of `backend/api/main.py` alongside other routers

  **Test cases**:
  - Order lifecycle endpoints work

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Order API
  > - **Skills**: `git-master`
  > - **Skills Evaluated but Omitted**: None

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 4
  - **Parallel Group**: Wave 4 task (31)
  - **Blocks**: Frontend order controls
  - **Blocked By**: None

- [x] 32. Create `backend/tests/test_market_provider_registry.py` - Unit tests

  **What to do**:
  - Create test file with comprehensive tests
  - Test registration, auto-discover, health checks
  - Test get_for_capability filtering
  - Test disabled with positions raises exception
  - Test force disable succeeds
  - Test paper mode injected correctly
  - Test health check triggers notification

  **Test cases**:
  - All tests pass with SHADOW_MODE=true

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Full test suite
  > - **Skills**: `test-driven-development`
  > - **Skills Evaluated but Omitted**: None

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 4
  - **Parallel Group**: Wave 4 task (32)
  - **Blocks**: None
  - **Blocked By**: Tasks 25, 26, 27, 28, 29, 30

### Wave 5: AGI Core Infrastructure (Tasks 33-37)

- [x] 33. Create `backend/agi/agent_state.py` - AgentState dataclass

  **What to do**:
  - Create `AgentState` dataclass
  - Implement `run_id`, `graph_name`, `created_at`, `data`, `errors`, `metadata`
  - Implement `evolve(**updates)` - returns new state with updates
  - Implement `with_error(node_name, error)` - adds error, returns new state
  - Implement `is_sandbox` flag for sandbox mode
  - Export in `backend/agi/__init__.py`

  **Test cases**:
  - State evolves correctly
  - Error tracking works
  - Sandbox flag prevents live access

  **Recommended Agent Profile**:
  > - **Category**: `quick` - Dataclass creation
  > - **Skills**: `git-master`
  > - **Skills Evaluated but Omitted**: None

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 5
  - **Parallel Group**: Wave 5 tasks
  - **Blocks**: Task 35, 36 (registry, engine depend on state)
  - **Blocked By**: Task 1

- [x] 34. Create `backend/agi/base_node.py` - AGI node abstract base

  **What to do**:
  - Create `NodeManifest` dataclass with all fields
  - Create `BaseAGINode` abstract base class
  - Implement `manifest()` classmethod as abstract
  - Implement `execute(state)` abstract
  - Implement `can_execute(state)` - default check input keys exist
  - Implement `teardown()` empty default
  - Export in `backend/agi/__init__.py`

  **Test cases**:
  - Node subclass works correctly
  - Manifest returns correct data
  - Execute receives state and returns updated state

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Abstract base
  > - **Skills**: `git-master`
  > - **Skills Evaluated but Omitted**: None

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 5
  - **Parallel Group**: Wave 5 tasks
  - **Blocks**: Task 35, 44-60 (nodes depend on this)
  - **Blocked By**: Task 33

- [x] 35. Create `backend/agi/node_registry.py` - Node registry

  **What to do**:
  - Subclass `PluginRegistry[NodeManifest, BaseAGINode]`
  - Create singleton `node_registry`
  - Implement `register()`, `get(name)`, `list_all()`
  - Implement `list_by_tag(tag)` - filter by tag
  - Implement `is_sandbox_safe(name)` - check requires_db and requires_live_data
  - Implement `auto_discover(package_path)`
  - Add to `backend/agi/__init__.py`

  **Test cases**:
  - Node registration works
  - Sandbox safety check correct
  - Tag filtering works

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Registry
  > - **Skills**: `test-driven-development`
  > - **Skills Evaluated but Omitted**: None

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 5
  - **Parallel Group**: Wave 5 tasks
  - **Blocks**: Task 44-60 (nodes depend on this)
  - **Blocked By**: Task 33, Task 34

- [x] 36. Create `backend/agi/graph_engine.py` - Directed graph executor

  **What to do**:
  - Create `GraphDefinition` dataclass with nodes, edges, entry/exit
  - Create `GraphEngine` class
  - Implement `run(graph_def, initial_state)` - async traversal
  - Implement `EdgeCondition(target, condition)` for conditional routing
  - Implement timeout per node (from manifest.timeout_seconds)
  - Implement retry per node (from manifest.max_retries)
  - Implement exponential backoff on retry
  - Implement sandbox mode: skip nodes requiring_db/requires_live_data
  - Implement cycle detection at definition time
  - Record execution trace in state.metadata["trace"]
  - Export in `backend/agi/__init__.py`

  **Test cases**:
  - Linear graph executes nodes in order
  - Conditional routing selects correct branch
  - Sandbox mode skips live nodes
  - Node timeout sets error
  - Cycle detection rejects graph at definition
  - Retry with backoff works

  **Recommended Agent Profile**:
  > - **Category**: `ultrabrain` - Complex graph engine
  > - **Skills**: `test-driven-development`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 5
  - **Parallel Group**: Wave 5 task (36)
  - **Blocks**: Task 54-57 (graph definitions)
  - **Blocked By**: Task 33, Task 34, Task 35

- [x] 37. Create `backend/tests/test_graph_engine.py` - Graph engine tests

  **What to do**:
  - Test linear graph execution
  - Test conditional routing
  - Test sandbox mode
  - Test timeout
  - Test retry with backoff
  - Test cycle detection

  **Test cases**:
  - All tests pass

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Full test suite
  > - **Skills**: `test-driven-development`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 5
  - **Parallel Group**: Wave 5 task (37)
  - **Blocks**: None
  - **Blocked By**: Task 36

### Wave 6: AGI Sandbox System (Tasks 38-43)

- [x] 38. Create `backend/agi/sandbox/sandbox_manager.py` - Sandbox manager

  **What to do**:
  - Create `SandboxManager` class
  - Implement `create_sandbox(scenario)` - returns isolated context
  - SandboxContext includes: mock data registry, mock strategy executor, shadow botstate
  - Implement `run_strategy_in_sandbox(code, scenario, num_trades)` - full execution
  - Use `importlib` to compile and load strategy temporarily (not sys.modules)
  - Run against mock data for configured number of trades
  - Return SandboxResult with metrics
  - No file writes, no DB reads/writes, no network calls
  - Export in `backend/agi/sandbox/__init__.py`

  **Test cases**:
  - Sandbox runs strategy in isolation
  - No live DB access
  - No live network calls
  - Results match expected format

  **Recommended Agent Profile**:
  > - **Category**: `ultrabrain` - Complex sandbox isolation
  > - **Skills**: `test-driven-development`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 6
  - **Parallel Group**: Wave 6 tasks
  - **Blocks**: Task 39 (validator depends on manager)
  - **Blocked By**: Task 36 (graph engine)

- [x] 39. Create `backend/agi/sandbox/sandbox_validator.py` - 4-gate validator

  **What to do**:
  - Create `SandboxValidator` class with `validate(code, scenario)` method
  - Gate 1 - SYNTAX: `ast.parse()` succeeds, no forbidden imports
  - Gate 2 - LINT: run flake8 subprocess, zero errors; run bandit security
  - Gate 3 - SANDBOX BACKTEST: run sandbox with 3 scenarios (bull, bear, volatile)
  - Gate 4 - SHADOW PROBE: register strategy as SHADOW, run 24 hours
  - Return SandboxResult with per-gate results
  - On gate failure: store failure point, return error details
  - Export in `backend/agi/sandbox/__init__.py`

  **Test cases**:
  - Gate 1 rejects forbidden imports
  - Gate 2 rejects lint errors
  - Gate 3 rejects below win rate / max drawdown
  - Gate 4 rejects during shadow probe
  - Full pass returns success result

  **Recommended Agent Profile**:
  > - **Category**: `ultrabrain` - Complex validation pipeline
  > - **Skills**: `test-driven-development`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 6
  - **Parallel Group**: Wave 6 tasks
  - **Blocks**: Task 32 (integration tests)
  - **Blocked By**: Task 38

- [x] 40. Create `backend/agi/sandbox/sandbox_registry.py` - Mock-only registry

  **What to do**:
  - Create `SandboxRegistry` instance with mock-only data sources
  - Only include `mock_source` in registry
  -拒绝 any nodes with requires_live_data=True
  - Export in `backend/agi/sandbox/__init__.py`

  **Test cases**:
  - Registry only contains mock sources
  - Live nodes rejected

  **Recommended Agent Profile**:
  > - **Category**: `quick` - Registry setup
  > - **Skills**: `git-master`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 6
  - **Parallel Group**: Wave 6 tasks
  - **Blocks**: Task 38
  - **Blocked By**: Task 1

- [x] 41. Create `backend/agi/sandbox/results.py` - SandboxResult dataclass

  **What to do**:
  - Create `SandboxScenario` dataclass with name, description, mock config
  - Create `SandboxResult` dataclass with all fields from spec
  - Export in `backend/agi/sandbox/__init__.py`

  **Test cases**:
  - Dataclasses instantiate correctly

  **Recommended Agent Profile**:
  > - **Category**: `quick` - Dataclasses
  > - **Skills**: `git-master`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 6
  - **Parallel Group**: Wave 6 tasks
  - **Blocks**: Task 39
  - **Blocked By**: None

- [x] 42. Create `backend/tests/test_sandbox_validator.py` - 4-gate tests

  **What to do**:
  - Test Gate 1 rejects forbidden imports
  - Test Gate 2 rejects lint errors
  - Test Gate 3 rejects below win rate
  - Test Gate 4 rejects during shadow probe
  - Test full pass returns success

  **Test cases**:
  - All tests pass

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Full test suite
  > - **Skills**: `test-driven-development`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 6
  - **Parallel Group**: Wave 6 task (42)
  - **Blocks**: None
  - **Blocked By**: Task 38, Task 39

- [x] 43. Create `backend/tests/test_sandbox_manager.py` - Sandbox isolation tests

  **What to do**:
  - Test sandbox cannot access live DB
  - Test sandbox cannot access live market providers
  - Test full sandbox validation

  **Test cases**:
  - All tests pass

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Isolation tests
  > - **Skills**: `test-driven-development`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 6
  - **Parallel Group**: Wave 6 task (43)
  - **Blocks**: None
  - **Blocked By**: Task 38, Task 39

### Wave 7: AGI Nodes and Graphs (Tasks 44-60)

- [x] 44. Create `backend/agi/nodes/__init__.py` - Auto-discover nodes

  **What to do**:
  - Import `node_registry`
  - Auto-discover all nodes in nodes/ directory
  - Export in `backend/agi/__init__.py`

  **Test cases**:
  - Auto-discover loads all nodes

  **Recommended Agent Profile**:
  > - **Category**: `quick` - Import setup
  > - **Skills**: `git-master`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 7
  - **Parallel Group**: Wave 7 tasks
  - **Blocks**: Task 60 (tests)
  - **Blocked By**: Task 35

- [x] 45. Create `backend/agi/nodes/regime_detector_node.py` - Wrap regime detector

  **What to do**:
  - Create `RegimeDetectorNode` subclass of `BaseAGINode`
  - Apply `@node_registry.plugin` decorator
  - Implement `manifest()` with requires_live_data=True
  - Implement `execute(state)` to call existing RegimeDetector
  - Return updated state with regime info
  - Export in `nodes/__init__.py`

  **Test cases**:
  - Node instantiates
  - Execute calls existing logic
  - Returns updated state

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Node wrapper
  > - **Skills**: `test-driven-development`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 7
  - **Parallel Group**: Wave 7 tasks
  - **Blocks**: Task 55 (graph)
  - **Blocked By**: Task 35, Task 44

- [x] 46. Create `backend/agi/nodes/knowledge_graph_node.py` - Wrap KG

  **What to do**:
  - Create `KnowledgeGraphNode` subclass of `BaseAGINode`
  - Apply `@node_registry.plugin` decorator
  - Implement `manifest()` with requires_db=True
  - Implement `execute(state)` to query KG
  - Return updated state
  - Export in `nodes/__init__.py`

  **Test cases**:
  - Node instantiates
  - Execute queries KG

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Node wrapper
  > - **Skills**: `test-driven-development`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 7
  - **Parallel Group**: Wave 7 tasks
  - **Blocks**: Task 55
  - **Blocked By**: Task 35, Task 44

- [x] 47. Create `backend/agi/nodes/strategy_composer_node.py` - Wrap composer

  **What to do**:
  - Create `StrategyComposerNode` subclass of `BaseAGINode`
  - Apply `@node_registry.plugin` decorator
  - Implement `manifest()` with sandbox-safe
  - Implement `execute(state)` to call existing composer
  - Return updated state with strategies
  - Export in `nodes/__init__.py`

  **Test cases**:
  - Node instantiates
  - Execute calls existing logic

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Node wrapper
  > - **Skills**: `test-driven-development`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 7
  - **Parallel Group**: Wave 7 tasks
  - **Blocks**: Task 55
  - **Blocked By**: Task 35, Task 44

- [x] 48. Create `backend/agi/nodes/strategy_synthesizer_node.py` - Wrap synthesizer

  **What to do**:
  - Create `StrategySynthesizerNode` subclass of `BaseAGINode`
  - Apply `@node_registry.plugin` decorator
  - Implement `manifest()` with is_deterministic=False
  - Implement `execute(state)` to call existing synthesizer
  - Return updated state with generated strategy code
  - Export in `nodes/__init__.py`

  **Test cases**:
  - Node instantiates
  - Execute generates code

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Node wrapper
  > - **Skills**: `test-driven-development`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 7
  - **Parallel Group**: Wave 7 tasks
  - **Blocks**: Task 56 (evolution graph)
  - **Blocked By**: Task 35, Task 44

- [x] 49. Create `backend/agi/nodes/goal_engine_node.py` - Wrap goal engine

  **What to do**:
  - Create `GoalEngineNode` subclass of `BaseAGINode`
  - Apply `@node_registry.plugin` decorator
  - Implement `manifest()` with requires_live_data=True
  - Implement `execute(state)` to call existing engine
  - Return updated state with goals
  - Export in `nodes/__init__.py`

  **Test cases**:
  - Node instantiates
  - Execute calls existing logic

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Node wrapper
  > - **Skills**: `test-driven-development`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 7
  - **Parallel Group**: Wave 7 tasks
  - **Blocks**: Task 55
  - **Blocked By**: Task 35, Task 44

- [x] 50. Create `backend/agi/nodes/forensics_node.py` - Wrap forensics

  **What to do**:
  - Create `ForensicsNode` subclass of `BaseAGINode`
  - Apply `@node_registry.plugin` decorator
  - Implement `manifest()` with requires_db=True
  - Implement `execute(state)` to call existing forensics
  - Return updated state with diagnosis
  - Export in `nodes/__init__.py`

  **Test cases**:
  - Node instantiates
  - Execute calls existing logic

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Node wrapper
  > - **Skills**: `test-driven-development`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 7
  - **Parallel Group**: Wave 7 tasks
  - **Blocks**: Task 57 (forensics graph)
  - **Blocked By**: Task 35, Task 44

- [x] 51. Create `backend/agi/nodes/auto_improve_node.py` - Wrap auto improve

  **What to do**:
  - Create `AutoImproveNode` subclass of `BaseAGINode`
  - Apply `@node_registry.plugin` decorator
  - Implement `manifest()` with requires_db=True
  - Implement `execute(state)` to call existing auto_improve
  - Return updated state with improvement
  - Export in `nodes/__init__.py`

  **Test cases**:
  - Node instantiates
  - Execute calls existing logic

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Node wrapper
  > - **Skills**: `test-driven-development`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 7
  - **Parallel Group**: Wave 7 tasks
  - **Blocks**: Task 57
  - **Blocked By**: Task 35, Task 44

- [x] 52. Create `backend/agi/nodes/model_calibration_node.py` - Wrap calibration

  **What to do**:
  - Create `ModelCalibrationNode` subclass of `BaseAGINode`
  - Apply `@node_registry.plugin` decorator
  - Implement `manifest()` with requires_db=True
  - Implement `execute(state)` to call existing calibration job
  - Return updated state with calibration results
  - Export in `nodes/__init__.py`

  **Test cases**:
  - Node instantiates
  - Execute calls existing logic

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Node wrapper
  > - **Skills**: `test-driven-development`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 7
  - **Parallel Group**: Wave 7 tasks
  - **Blocks**: Task 57
  - **Blocked By**: Task 35, Task 44

- [x] 53. Create `backend/agi/nodes/evolution_node.py` - Wrap evolution

  **What to do**:
  - Create `EvolutionNode` subclass of `BaseAGINode`
  - Apply `@node_registry.plugin` decorator
  - Implement `manifest()` with requires_db=True
  - Implement `execute(state)` to call existing evolution jobs
  - Return updated state with evolution results
  - Export in `nodes/__init__.py`

  **Test cases**:
  - Node instantiates
  - Execute calls existing logic

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Node wrapper
  > - **Skills**: `test-driven-development`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 7
  - **Parallel Group**: Wave 7 tasks
  - **Blocks**: Task 56
  - **Blocked By**: Task 35, Task 44

- [x] 54. Create `backend/agi/graphs/__init__.py` - Graph definitions

  **What to do**:
  - Import `graph_engine` and `node_registry`
  - Export all graph definitions
  - Export in `backend/agi/__init__.py`

  **Test cases**:
  - All graphs importable

  **Recommended Agent Profile**:
  > - **Category**: `quick` - Import setup
  > - **Skills**: `git-master`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 7
  - **Parallel Group**: Wave 7 task (54)
  - **Blocks**: None
  - **Blocked By**: Task 36

- [x] 55. Create `backend/agi/graphs/market_analysis_graph.py` - Regime → KG → Goal

  **What to do**:
  - Create `MarketAnalysisGraph` graph definition
  - Nodes: regime_detector, knowledge_graph, goal_engine, strategy_composer
  - Edges: conditional routing based on regime type
  - Entry: regime_detector
  - Exit: signal_aggregator
  - Export in `graphs/__init__.py`

  **Test cases**:
  - Graph executes correctly with different regimes

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Graph definition
  > - **Skills**: `test-driven-development`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 7
  - **Parallel Group**: Wave 7 task (55)
  - **Blocks**: None
  - **Blocked By**: Task 45, 46, 47, 49, 36

- [x] 56. Create `backend/agi/graphs/strategy_evolution_graph.py` - Synth → Sandbox → Promote

  **What to do**:
  - Create `StrategyEvolutionGraph` graph definition
  - Nodes: strategy_synthesizer, sandbox_validation, experiment_registration
  - Edges: success path to registration, failure path to retry (max 3)
  - Entry: strategy_synthesizer
  - Exit: experiment_registration (success) or max_retries_exceeded (failure)
  - Export in `graphs/__init__.py`

  **Test cases**:
  - Graph executes successfully
  - Retries work with max 3 cycles

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Graph definition
  > - **Skills**: `test-driven-development`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 7
  - **Parallel Group**: Wave 7 task (56)
  - **Blocks**: None
  - **Blocked By**: Task 48, Task 38, Task 36

- [x] 57. Create `backend/agi/graphs/forensics_graph.py` - Loss → Forensics → Improve

  **What to do**:
  - Create `ForensicsGraph` graph definition
  - Nodes: forensics, knowledge_graph, auto_improve, model_calibration
  - Edges: improvement available path, improvement not available path
  - Entry: forensics
  - Exit: calibration_report
  - Export in `graphs/__init__.py`

  **Test cases**:
  - Graph executes on loss
  - Improvement path works
  - Calibration path works

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Graph definition
  > - **Skills**: `test-driven-development`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 7
  - **Parallel Group**: Wave 7 task (57)
  - **Blocks**: None
  - **Blocked By**: Task 50, Task 51, Task 52, Task 53, Task 36

- [x] 58. Create `backend/agi/node_registry.py` - Reference import for all nodes

  **What to do**:
  - Import `node_registry` from `backend.agi.node_registry`
  - Import all node modules in nodes/ directory
  - Register all nodes via decorators
  - Export in `backend/agi/__init__.py`

  **Test cases**:
  - All nodes registered in registry

  **Recommended Agent Profile**:
  > - **Category**: `quick` - Import setup
  > - **Skills**: `git-master`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 7
  - **Parallel Group**: Wave 7 task (58)
  - **Blocks**: Task 60
  - **Blocked By**: Task 35, Tasks 45-53

- [x] 59. Refactor `backend/strategies/base.py` - Add `market_context` field

  **What to do**:
  - Import `MultiVenueContext` from `backend.markets.multi_venue`
  - Add `market_context: MultiVenueContext` field to `StrategyContext`
  - Import `DataSourceRegistry` from `backend.data.source_registry`
  - Add `data_registry: DataSourceRegistry` field to `StrategyContext`
  - Inject data_registry and market_context via strategy_executor
  - Export in `backend/strategies/__init__.py`

  **Test cases**:
  - StrategyContext has both registry fields
  - Strategies can access data and market through context

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Context refactoring
  > - **Skills**: `test-driven-development`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 7
  - **Parallel Group**: Wave 7 task (59)
  - **Blocks**: Task 60 (integration tests)
  - **Blocked By**: Task 6, Task 23, Task 58

- [x] 60. Create `backend/tests/test_node_registry.py` and `test_sandbox_node.py` - Node tests

  **What to do**:
  - Test node registration
  - Test sandbox node execution
  - Test all nodes can be loaded
  - Test sandbox nodes skipped when live data required

  **Test cases**:
  - `test_register_valid_node` — registers a concrete `BaseAGINode` subclass, verifies in `_plugins`/`_enabled`/`_health_status`
  - `test_get_node_by_name` — retrieves registered node by name
  - `test_get_disabled_node_raises` — disabled node raises `KeyError`
  - `test_list_all_only_enabled` — `list_all()` excludes disabled nodes
  - `test_singleton_identity` — two `NodeRegistry()` calls return same instance
  - `test_reset_clears_instance` — `NodeRegistry.reset()` allows fresh instantiation
  - `test_sandbox_node_skipped_when_live_required` — sandbox node's `is_sandbox=True` makes it filterable when live data is required
  - `test_sandbox_node_execute_returns_state` — sandbox node `execute()` returns `AgentState` with expected keys

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Full test suite
  > - **Skills**: `test-driven-development`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 7
  - **Parallel Group**: Wave 7 task (60)
  - **Blocks**: None
  - **Blocked By**: Tasks 45-59

### Wave 8: Integration + Frontend (Tasks 61-76)

- [x] 61. Create `backend/api/v1/agi_nodes.py` - AGI node API

  **What to do**:
  - Create FastAPI router
  - Implement GET `/api/v1/agi/nodes` - list all nodes
  - Implement POST `/api/v1/agi/nodes/{name}/enable`
  - Implement POST `/api/v1/agi/nodes/{name}/disable`

  **Test cases**:
  - All endpoints functional

  **Recommended Agent Profile**:
  > - **Category**: `quick` - API endpoints
  > - **Skills**: `git-master`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 8
  - **Parallel Group**: Wave 8 tasks
  - **Blocks**: Frontend API client (task 71)
  - **Blocked By**: Task 35, Task 44

- [x] 62. Create `backend/api/v1/agi_graphs.py` - Graph run API

  **What to do**:
  - Create FastAPI router
  - Implement GET `/api/v1/agi/graphs` - list all graphs
  - Implement POST `/api/v1/agi/graphs/{name}/run` - trigger graph run
  - Implement GET `/api/v1/agi/runs/{run_id}` - get execution trace

  **Test cases**:
  - All endpoints functional

  **Recommended Agent Profile**:
  > - **Category**: `quick` - API endpoints
  > - **Skills**: `git-master`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 8
  - **Parallel Group**: Wave 8 tasks
  - **Blocks**: Frontend API client (task 71)
  - **Blocked By**: Task 36, Task 54

- [x] 63. Create `backend/api/v1/agi_sandbox.py` - Sandbox API

  **What to do**:
  - Create FastAPI router
  - Implement GET `/api/v1/agi/sandbox/scenarios` - list scenarios
  - Implement POST `/api/v1/agi/sandbox/validate` - submit code for validation
  - Implement GET `/api/v1/agi/sandbox/results/{run_id}` - get results

  **Test cases**:
  - All endpoints functional

  **Recommended Agent Profile**:
  > - **Category**: `quick` - API endpoints
  > - **Skills**: `git-master`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 8
  - **Parallel Group**: Wave 8 tasks
  - **Blocks**: Frontend API client (task 71)
  - **Blocked By**: Task 38, Task 39

- [x] 64. Create `frontend/src/components/PluginStatusPanel.tsx` - Unified plugin view

  **What to do**:
  - Create React component with tabs for all 4 registries
  - Each tab shows table with Name, Version, Status, Tags, Toggle
  - Toggle calls enable/disable API endpoint
  - Market Venues tab shows Balance and Open Positions
  - Auto-refresh every 30 seconds (60 for Market)
  - Export in `frontend/src/components/index.tsx`

  **Test cases**:
  - Component renders correctly
  - Toggle calls API
  - Auto-refresh works

  **Recommended Agent Profile**:
  > - **Category**: `visual-engineering` - Frontend component
  > - **Skills**: `frontend-ui-ux`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 8
  - **Parallel Group**: Wave 8 tasks
  - **Blocks**: None
  - **Blocked By**: Tasks 13, 21, 30, 61, 62, 63

- [x] 65. Create `frontend/src/components/VenueMonitor.tsx` - Per-venue monitoring

  **What to do**:
  - Create React component with cards per active venue
  - Show: venue name, health, balance, positions, volume, last fill
  - Expandable positions list with details
  - "Cancel All Orders" button (admin-only)
  - "Disable Venue" button with confirmation modal for open positions

  **Test cases**:
  - Component renders correctly
  - All buttons functional

  **Recommended Agent Profile**:
  > - **Category**: `visual-engineering` - Frontend component
  > - **Skills**: `frontend-ui-ux`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 8
  - **Parallel Group**: Wave 8 task (65)
  - **Blocks**: None
  - **Blocked By**: Task 64

- [x] 66. Create `frontend/src/components/SandboxMonitor.tsx` - Sandbox validation

  **What to do**:
  - Create React component listing sandbox runs
  - Show: strategy name, scenario, gate reached, pass/fail
  - Expandable rows with per-gate results
  - "Validate Strategy" button opens code editor textarea
  - POST to `/api/v1/agi/sandbox/validate`

  **Test cases**:
  - Component renders correctly
  - Validation form functional

  **Recommended Agent Profile**:
  > - **Category**: `visual-engineering` - Frontend component
  > - **Skills**: `frontend-ui-ux`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 8
  - **Parallel Group**: Wave 8 task (66)
  - **Blocks**: None
  - **Blocked By**: Task 64, Task 63

- [x] 67. Create `frontend/src/components/AGIGraphRunner.tsx` - Graph trigger

  **What to do**:
  - Create React component with dropdown of graphs
  - "Run Graph" button (admin-only)
  - Live trace view polling `/api/v1/agi/runs/{run_id}`
  - Render node execution sequence as timeline

  **Test cases**:
  - Component renders correctly
  - Graph execution triggers
  - Timeline updates

  **Recommended Agent Profile**:
  > - **Category**: `visual-engineering` - Frontend component
  > - **Skills**: `frontend-ui-ux`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 8
  - **Parallel Group**: Wave 8 task (67)
  - **Blocks**: None
  - **Blocked By**: Task 64, Task 62

- [x] 68. Create `frontend/src/api/providers.ts` - AI provider API client

  **What to do**:
  - Create axios instance for `/api/v1/ai/providers` endpoints
  - Export typed functions: listProviders(), enableProvider(), disableProvider(), getProviderHealth()
  - Export TypeScript interfaces for Provider, ProviderManifest, HealthStatus
  - Use existing api client pattern

  **Test cases**:
  - All client functions work
  - Type definitions correct

  **Recommended Agent Profile**:
  > - **Category**: `quick` - API client
  > - **Skills**: `git-master`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 8
  - **Parallel Group**: Wave 8 tasks
  - **Blocks**: None
  - **Blocked By**: Task 13

- [x] 69. Create `frontend/src/api/data_sources.ts` - Data source API client

  **What to do**:
  - Create axios instance for `/api/v1/data/sources` endpoints
  - Export typed functions

  **Test cases**:
  - All client functions work

  **Recommended Agent Profile**:
  > - **Category**: `quick` - API client
  > - **Skills**: `git-master`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 8
  - **Parallel Group**: Wave 8 task (69)
  - **Blocks**: None
  - **Blocked By**: Task 21

- [x] 70. Create `frontend/src/api/market_venues.ts` - Market provider API client

  **What to do**:
  - Create axios instance for `/api/v1/markets/providers` and `/api/v1/markets/order` endpoints
  - Export typed functions
  - Export TypeScript types: NormalizedBalance, NormalizedPosition, MarketProviderManifest

  **Test cases**:
  - All client functions work

  **Recommended Agent Profile**:
  > - **Category**: `quick` - API client
  > - **Skills**: `git-master`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 8
  - **Parallel Group**: Wave 8 task (70)
  - **Blocks**: None
  - **Blocked By**: Task 30

- [x] 71. Update `frontend/src/api/agi.ts` - AGI client

  **What to do**:
  - Add sandbox and graph run endpoints
  - Export typed functions

  **Test cases**:
  - All client functions work

  **Recommended Agent Profile**:
  > - **Category**: `quick` - API upgrade
  > - **Skills**: `git-master`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 8
  - **Parallel Group**: Wave 8 task (71)
  - **Blocks**: None
  - **Blocked By**: Tasks 61, 62, 63

- [x] 72. Create `backend/tests/test_integration_ensemble.py` - AI provider integration tests

  **What to do**:
  - Test provider registry ensemble with registry providers
  - Test fallback to healthy provider when primary fails
  - Test metrics emitted
  - Test cost tracker enforced

  **Test cases**:
  - All integration tests pass

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Integration tests
  > - **Skills**: `test-driven-development`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 8
  - **Parallel Group**: Wave 8 task (72)
  - **Blocks**: None
  - **Blocked By**: Tasks 10, 11, 12, 14, 68

- [x] 73. Create `backend/tests/test_integration_data_strategy.py` - Data source integration

  **What to do**:
  - Test strategy context injection with data registry
  - Test strategy fetches data through registry
  - Test sandbox gets mock data registry

  **Test cases**:
  - All integration tests pass

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Integration tests
  > - **Skills**: `test-driven-development`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 8
  - **Parallel Group**: Wave 8 task (73)
  - **Blocks**: None
  - **Blocked By**: Tasks 16, 17, 18, 20, 22, 69

- [x] 74. Create `backend/tests/test_integration_order_executor.py` - Order executor tests

  **What to do**:
  - Test order executor uses market registry
  - Test risk manager called before venue
  - Test shadow mode routes to paper provider
  - Test TradeAttempt recorded for all attempts

  **Test cases**:
  - All integration tests pass

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Integration tests
  > - **Skills**: `test-driven-development`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 8
  - **Parallel Group**: Wave 8 task (74)
  - **Blocks**: None
  - **Blocked By**: Tasks 25, 26, 27, 28, 32, 70

- [x] 75. Create `backend/tests/test_integration_sandbox_evolution.py` - Evolution tests

  **What to do**:
  - Test full evolution graph in sandbox mode
  - Test no DB writes during sandbox validation
  - Test no market provider orders placed during sandbox

  **Test cases**:
  - All integration tests pass

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Integration tests
  > - **Skills**: `test-driven-development`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 8
  - **Parallel Group**: Wave 8 task (75)
  - **Blocks**: None
  - **Blocked By**: Tasks 38, 39, 42, 43, 56

- [x] 76. Create `backend/tests/test_integration_settlement_fills.py` - Settlement tests

  **What to do**:
  - Test settlement consumes fills from registry stream
  - Test multi-provider streaming works
  - Test Reconnection on stream drop

  **Test cases**:
  - All integration tests pass

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high` - Integration tests
  > - **Skills**: `test-driven-development`

  **Parallelization**:
  - **Can Run In Parallel**: YES - Wave 8
  - **Parallel Group**: Wave 8 task (76)
  - **Blocks**: None
  - **Blocked By**: Tasks 25, 26, 27, 29, 32, 70

### Final Verification Wave (Tasks F1-F4)

- [x] F1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists (read file, curl endpoint, run command). For each "Must NOT Have": search codebase for forbidden patterns — reject with file:line if found. Check evidence files exist in .sisyphus/evidence/. Compare deliverables against plan.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [x] F2. **Code Quality Review** — `unspecified-high`
  Run `tsc --noEmit` + linter + `bun test`. Review all changed files for: `as any`/`@ts-ignore`, empty catches, console.log in prod, commented-out code, unused imports. Check AI slop: excessive comments, over-abstraction, generic names (data/result/item/temp).
  Output: `Build [PASS/FAIL] | Lint [PASS/FAIL] | Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [x] F3. **Real Manual QA** — `unspecified-high` (+ `playwright` skill if UI)
  Start from clean state. Execute EVERY QA scenario from EVERY task — follow exact steps, capture evidence. Test cross-task integration (features working together, not isolation). Test edge cases: empty state, invalid input, rapid actions. Test save to `.sisyphus/evidence/final-qa/`.
  Output: `Scenarios [N/N pass] | Integration [N/N] | Edge Cases [N tested] | VERDICT`

- [x] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff (git log/diff). Verify 1:1 — everything in spec was built (no missing), nothing beyond spec was built (no creep). Check "Must NOT do" compliance. Detect cross-task contamination: Task N touching Task M's files. Flag unaccounted changes.
  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

- **Wave 1**: `feat(plugin): core infrastructure base classes and registries` - plugin_registry.py, plugin_errors.py
- **Wave 2**: `feat(ai): AI provider registry and plugin implementations` - providers/, ensemble.py, API
- **Wave 3**: `feat(data): Data source registry and injection` - sources/, market_universe.py, StrategyContext
- **Wave 4**: `feat(markets): Market provider registry and normalized interface` - order_types.py, providers/, executor.py, settlement.py
- **Wave 5**: `feat(agi): Node registry and graph engine` - agent_state.py, base_node.py, graph_engine.py
- **Wave 6**: `feat(sandbox): Isolated strategy validation` - sandbox_manager.py, sandbox_validator.py, sandbox_registry.py
- **Wave 7**: `feat(nodes): AGI nodes and graph definitions` - nodes/, graphs/
- **Wave 8**: `feat(integration): End-to-end integration and frontend` - integration tests, frontend components
- **Final**: `feat(plugin): complete plugin system implementation` - F1-F4 verification, final commits
- **Tests**: `test(plugin): comprehensive plugin system test coverage` - all test files

---

## Success Criteria

### Verification Commands
```bash
# Run all plugin system tests
pytest backend/tests/test_plugin_registry.py backend/tests/test_ai_provider_registry.py backend/tests/test_data_source_registry.py backend/tests/test_market_provider_registry.py backend/tests/test_node_registry.py backend/tests/test_sandbox_validator.py backend/tests/test_sandbox_manager.py

# Check AI provider system
curl -s http://localhost:8100/api/v1/ai/providers | jq .
curl -s -X POST http://localhost:8100/api/v1/ai/providers/claude/disable | jq .

# Check data source system
curl -s http://localhost:8100/api/v1/data/sources | jq .
curl -s -X POST http://localhost:8100/api/v1/data/sources/polymarket/disable | jq .

# Check market provider system
curl -s http://localhost:8100/api/v1/markets/providers | jq .
curl -s -X POST http://localhost:8100/api/v1/markets/providers/polymarket/disable?force=true | jq .

# Check AGI node system
curl -s http://localhost:8100/api/v1/agi/nodes | jq .
curl -s http://localhost:8100/api/v1/agi/graphs | jq .

# Check sandbox validation
curl -s -X POST http://localhost:8100/api/v1/agi/sandbox/validate -H "Content-Type: application/json" -d '{"code": "...", "scenario": "bull_2024"}' | jq .
```

### Final Checklist
- [x] All "Must Have" present
- [x] All "Must NOT Have" absent
- [x] All tests pass
- [x] All API endpoints functional
- [x] All frontend panels display correctly
- [x] All documentation updated
- [x] All ADRs created/updated
