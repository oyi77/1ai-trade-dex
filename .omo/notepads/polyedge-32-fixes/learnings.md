# Learnings — polyedge-32-fixes

## 2026-05-08T04:21 Session Start
- Project: PolyEdge prediction market trading bot (Python FastAPI + React)
- Backend: pytest from project root, Frontend: `cd frontend && npm test`
- All 33 tasks are greenfield — previous sessions only did research/planning
- No existing probability_utils.py, no previous implementations committed
- SQLite doesn't support .with_for_update() — use CAS pattern (T9)
- Strategies in backend/strategies/, AI modules in backend/ai/, data feeds in backend/data/
- Job queue in backend/job_queue/, monitoring in backend/monitoring/
- RiskManager gates are non-bypassable (ADR-004)
- Config via backend/config.py with .env feature flags
- Tests go in backend/tests/
