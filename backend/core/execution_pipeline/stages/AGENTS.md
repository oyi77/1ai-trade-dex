<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 -->

# core/execution_pipeline/stages

## Purpose
Concrete execution pipeline stage implementations. Each stage handles one phase of trade execution: validation, simulation, live execution, recording, and notification.

## Key Files
| File | Description |
|------|-------------|
| `__init__.py` | Exports all stages: `ValidationStage`, `PaperSimulationStage`, `LiveExecuteStage`, `RecordStage`, `NotifyStage` |
| `validate.py` | `ValidationStage` — pre-execution checks (bankroll, exposure limits, market validity) |
| `simulate.py` | `PaperSimulationStage` — simulates order fills in paper/shadow mode without hitting real venues |
| `execute.py` | `LiveExecuteStage` — submits orders to live venues via market provider registry |
| `record.py` | `RecordStage` — persists trade attempts and fills to database |
| `notify.py` | `NotifyStage` — sends trade notifications via the notification registry |

## For AI Agents

### Working In This Directory
- Each stage subclasses `BaseExecutionStage` and implements `manifest()` plus one or more of `validate()`, `execute()`, `record()`
- Stages declare `mode` in their manifest (e.g., "paper", "live", "all") to control when they run
- `order` in the manifest determines execution sequence (validate=10, simulate=20, execute=30, record=40, notify=50)
- `LiveExecuteStage` integrates with `backend.markets` provider registry for venue-specific order submission

## Dependencies

### Internal
- `backend.core.execution_pipeline.base` — `BaseExecutionStage`, `ExecutionStageManifest`
- `backend.markets` — market provider registry for live execution
- `backend.bot.notification` — notification registry for notify stage
- `backend.models.database` — trade persistence for record stage
