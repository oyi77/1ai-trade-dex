<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 -->

# evals/benchmarks

## Purpose
Individual AGI benchmark implementations. Each benchmark tests a specific AGI capability and returns normalized scores for certification.

## Key Files
| File | Description |
|------|-------------|
| `__init__.py` | Empty |
| `agi_score.py` | Composite AGI score — aggregates all benchmark scores into a single capability metric |
| `causal_reasoning.py` | Causal reasoning benchmark — tests ability to identify cause-effect relationships in market data |
| `cross_domain_transfer.py` | Cross-domain transfer benchmark — tests knowledge transfer between market types |
| `few_shot_learning.py` | Few-shot learning benchmark — tests adaptation from limited examples |

## For AI Agents

### Working In This Directory
- Each benchmark returns a dict with `score` (0.0-1.0) and metadata
- Benchmarks are called by `certification_checklist.py` in `backend/evals/`
- Scores below threshold fail certification — thresholds are defined per benchmark

## Dependencies

### Internal
- `backend.evals.metrics` — `AGIScoreMetric` base class for scoring
