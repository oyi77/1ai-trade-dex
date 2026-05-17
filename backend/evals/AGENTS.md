<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 -->

# evals

## Purpose
AGI evaluation and certification framework. Runs benchmark suites to measure AGI capabilities (causal reasoning, cross-domain transfer, few-shot learning, AGI score), aggregates results into certification checklists, and generates timestamped reports.

## Key Files
| File | Description |
|------|-------------|
| `__init__.py` | Imports benchmarks and metrics packages |
| `certification_checklist.py` | `run_certification_check()` — aggregates all benchmark results, verifies threshold pass/fail, generates JSON reports |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `benchmarks/` | Individual benchmark implementations (AGI score, causal reasoning, cross-domain transfer, few-shot learning) |
| `metrics/` | Scoring metric base class (`AGIScoreMetric`) |
| `reports/` | Generated JSON report files (timestamped, gitignored contents) |
| `suites/` | Test suite definitions (empty placeholder) |
| `tests/` | Integration tests for the evals framework |

## For AI Agents

### Working In This Directory
- Run certification: `from backend.evals.certification_checklist import run_certification_check; result = run_certification_check()`
- Reports are saved to `backend/evals/reports/` with timestamp filenames
- Benchmarks return normalized 0.0-1.0 scores; thresholds defined per benchmark
- The certification checklist checks: cross_domain_transfer, causal_reasoning, few_shot_learning, agi_score

### Testing Requirements
- Run: `pytest backend/evals/tests/ -v`
- Use `custom_scores` parameter in `run_certification_check()` for deterministic testing

## Dependencies

### Internal
- `backend.evals.benchmarks` — benchmark implementations
- `backend.evals.metrics` — scoring base class
