<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-09 | Updated: 2026-05-09 -->

# research

## Purpose
Automated research pipeline for strategy discovery and validation. Triggers research cycles based on market events (new market listings, regime changes, performance degradation), executes research tasks, and persists findings for the AGI improvement loop.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `models.py` | `ResearchTask`, `ResearchFinding` dataclasses — task definition, status, priority, findings with confidence scores |
| `pipeline.py` | `ResearchPipeline` — orchestrates research cycles: create tasks from triggers, execute via AI/browser, score findings, persist results; ~300 lines |
| `event_triggers.py` | Event-driven research triggers — listens for market events (new markets, price shocks, settlement anomalies) and creates `ResearchTask` entries; ~150 lines |
| `storage.py` | `ResearchStorage` — SQLite-backed persistence for research tasks and findings; CRUD operations with filtering by status/date/priority |

## For AI Agents

### Working In This Directory
- Pipeline is triggered by events, not scheduled — `event_triggers.py` creates tasks from real-time signals
- `ResearchPipeline.execute_cycle()` picks up pending tasks, runs analysis, stores findings
- Findings feed into `backend.core.forensics_integration` and `backend.core.auto_improve`
- Feature flag: `RESEARCH_PIPELINE_ENABLED` (default: false — experimental)

### Common Patterns
```python
from backend.research.pipeline import ResearchPipeline
pipeline = ResearchPipeline()
results = await pipeline.execute_cycle()  # Processes pending tasks
```

## Dependencies

### Internal
- `backend.core.event_bus` — subscribes to market/trade events
- `backend.models.database` — SQLAlchemy session
- `backend.ai` — AI analysis for research tasks
- `backend.config` — `RESEARCH_PIPELINE_ENABLED`

### External
- `httpx` — async HTTP for external research sources
