<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 -->

# agi/sandbox

## Purpose
Isolated strategy validation sandbox. Tests strategy modifications and new strategies in a sandboxed environment before they touch real capital. Provides a manager, registry, validator, and result types.

## Key Files
| File | Description |
|------|-------------|
| `__init__.py` | Exports `SandboxResult`, `SandboxManager`, `SandboxNodeRegistry`, `SandboxValidator` |
| `results.py` | `SandboxResult` dataclass — outcome of a sandbox validation run |
| `sandbox_manager.py` | `SandboxManager` — orchestrates sandbox runs, manages lifecycle of sandboxed executions |
| `sandbox_registry.py` | `SandboxNodeRegistry` — registry for sandbox-specific node overrides |
| `sandbox_validator.py` | `SandboxValidator` — validates that modifications pass safety checks before promotion |

## For AI Agents

### Working In This Directory
- The sandbox is the safety boundary between AGI modifications and live trading
- All strategy modifications MUST pass sandbox validation before being applied to live strategies
- `SandboxManager` creates isolated `AgentState` instances with `is_sandbox=True`
- The graph engine automatically skips nodes with `requires_db=True` or `requires_live_data=True` in sandbox mode

### Testing Requirements
- Run: `pytest backend/agi/tests/test_sandbox_hardening.py -v`
- Test that sandbox validation catches unsafe modifications

### Common Patterns
- Validate a modification: `validator = SandboxValidator(); result = await validator.validate(modification)`
- Run sandbox: `manager = SandboxManager(); result = await manager.run(strategy, params)`

## Dependencies

### Internal
- `backend.agi.agent_state` — `AgentState` with sandbox flag
- `backend.agi.graph_engine` — executes graphs in sandbox mode
- `backend.strategies` — strategies being validated
