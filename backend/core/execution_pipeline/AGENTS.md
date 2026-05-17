<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 -->

# core/execution_pipeline

## Purpose
Pluggable trade execution pipeline. Defines the stage-based execution flow: validate, simulate, execute, record, notify. Each stage is a plugin that can be swapped or extended. The registry manages stage ordering and lifecycle.

## Key Files
| File | Description |
|------|-------------|
| `__init__.py` | Exports `BaseExecutionStage`, `ExecutionStageManifest`, `ExecutionPipelineRegistry`, `registry` |
| `base.py` | `BaseExecutionStage` ABC + `ExecutionStageManifest` — stages implement `validate()`, `execute()`, `record()`, `health_check()` |
| `registry.py` | `ExecutionPipelineRegistry` — registers stages, manages execution order, runs the full pipeline |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `stages/` | Concrete stage implementations (validate, simulate, execute, record, notify) |

## For AI Agents

### Working In This Directory
- Stages are ordered by `manifest.order` — lower order runs first
- The pipeline runs: validate -> simulate (paper mode) -> execute (live mode) -> record -> notify
- Each stage receives `(decision: dict, ctx: dict)` and returns a result dict
- The registry is a module-level singleton — use `from backend.core.execution_pipeline import registry`

### Common Patterns
- Register a stage: `registry.register(MyStage)`
- Run pipeline: `result = await registry.run_pipeline(decision, ctx)`

## Dependencies

### Internal
- `backend.core.plugin_registry` — base plugin infrastructure
- `backend.models.database` — trade persistence
