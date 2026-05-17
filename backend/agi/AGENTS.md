<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 -->

# agi

## Purpose
Autonomous General Intelligence engine for self-improving trading. Contains the graph-based pipeline orchestration, pluggable node system, code intelligence, sandboxed strategy validation, and self-improvement loops. The AGI system evolves strategies, detects market regimes, performs forensics on trade outcomes, and autonomously refactors its own codebase.

## Key Files
| File | Description |
|------|-------------|
| `__init__.py` | Exports `AgentState`, `NodeManifest`, `BaseAGINode`, `node_registry`, `GraphEngine`, `GraphDefinition` |
| `agent_state.py` | `AgentState` dataclass — immutable state bag passed through graph nodes; tracks data, errors, sandbox mode |
| `base_node.py` | `BaseAGINode` ABC + `NodeManifest` — all AGI nodes subclass this; `execute(state) -> state` contract |
| `node_registry.py` | Singleton `NodeRegistry` — auto-discovers nodes from `backend.agi.nodes`, health checks every 30s |
| `graph_engine.py` | `GraphEngine` — DAG executor with topological sort, cycle detection, sandbox-aware node skipping |
| `codebase_intelligence.py` | Code analysis: AST parsing, complexity scoring, dependency mapping for self-improvement |
| `code_refactorer.py` | Automated code refactoring engine — applies safe transformations with rollback support |
| `modification_engine.py` | Strategy modification engine — proposes and applies parameter/code changes to strategies |
| `self_improvement_loop.py` | Main AGI improvement cycle: scan, plan, modify, validate, commit |
| `self_healing.py` | Self-healing system — detects failures, proposes fixes, validates before applying |
| `long_term_planner.py` | Strategic planning engine — decomposes high-level goals into executable task graphs |
| `multi_objective_optimizer.py` | NSGA-II style multi-objective optimization for strategy parameters |
| `rollback_manager.py` | Tracks modifications and provides rollback to last known-good state |
| `core_values.py` | Core value constraints that bound AGI autonomy (risk limits, ethical guards) |
| `extended_sandbox.py` | Extended sandbox for testing strategy modifications in isolation |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `graphs/` | Predefined DAG graph definitions (market analysis, strategy evolution, forensics) |
| `nodes/` | Concrete AGI node implementations (14 nodes) |
| `sandbox/` | Sandboxed strategy validation (manager, registry, validator) |
| `tests/` | AGI-specific unit tests |

## For AI Agents

### Working In This Directory
- **All nodes are async** — `execute(state) -> state` is always `async def`. Never use sync blocking.
- **Nodes declare input/output keys via `NodeManifest`** — the graph engine validates data availability before execution. Missing keys cause a skip (not crash) in sandbox mode.
- **`node_registry` is a module-level singleton** — import it from `backend.agi`; do not instantiate `NodeRegistry()` directly.
- **Graphs are DAGs** — the engine detects cycles at registration time and raises `ValueError`.
- **Sandbox mode** — when `state.is_sandbox=True`, nodes requiring DB or live data are skipped automatically.
- **Self-improvement has rollback** — every modification is tracked; `rollback_manager.py` can revert to the previous state.

### Testing Requirements
- Tests live in `backend/agi/tests/` (AGI-specific) and `backend/tests/` (integration)
- Run: `pytest backend/agi/tests/ -v`
- Mock DB and live data dependencies for sandbox-mode tests

### Common Patterns
- Register a new node: subclass `BaseAGINode`, implement `manifest()` and `execute()`, place in `nodes/`
- Execute a graph: `engine = GraphEngine(); await engine.execute_graph("market_analysis", initial_state)`
- Run health checks: `results = await node_registry.run_health_checks()`

## Dependencies

### Internal
- `backend.core.plugin_registry` — `BasePlugin` base class for node inheritance
- `backend.strategies` — strategies are modified/evolved by AGI engines
- `backend.models.database` — persistence for AGI state and modifications

### External
- `ast` — Python AST parsing for codebase intelligence
- `numpy` — numerical optimization
