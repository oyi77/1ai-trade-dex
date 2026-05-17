<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 -->

# agi/tests

## Purpose
Unit tests for AGI subsystem components: code refactoring, long-term planning, multi-objective optimization, and sandbox hardening.

## Key Files
| File | Description |
|------|-------------|
| `test_code_refactorer.py` | Tests for the automated code refactoring engine (13K) |
| `test_long_term_planner.py` | Tests for the strategic planning engine |
| `test_multi_objective_optimizer.py` | Tests for NSGA-II multi-objective optimization |
| `test_sandbox_hardening.py` | Tests for sandbox safety validation and hardening |

## For AI Agents

### Testing Requirements
- Run all: `pytest backend/agi/tests/ -v`
- Run specific: `pytest backend/agi/tests/test_sandbox_hardening.py -v`
- These tests use mocked dependencies — no DB or live data required

## Dependencies

### Internal
- `backend.agi` — all AGI modules under test
- `pytest` — test framework
