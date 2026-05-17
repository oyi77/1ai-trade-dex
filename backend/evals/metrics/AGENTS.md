<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 -->

# evals/metrics

## Purpose
Base scoring metric class for AGI evaluation benchmarks. Provides the abstract interface that all benchmark metrics implement.

## Key Files
| File | Description |
|------|-------------|
| `__init__.py` | Exports `AGIScoreMetric` — ABC with `score()`, `thresholds()`, and `normalize()` methods |

## For AI Agents

### Working In This Directory
- `AGIScoreMetric` is the base class for all evaluation metrics
- `score(result) -> float` computes raw score
- `thresholds() -> dict` returns pass/fail boundaries (e.g., `{"fail": 0.3, "pass": 0.6, "excellent": 0.9}`)
- `normalize(score) -> float` clamps to 0.0-1.0

## Dependencies

### Internal
- None (standalone base class)
