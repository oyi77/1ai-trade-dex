<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 -->

# core/tests

## Purpose
Unit tests for core subsystem components: agent council, learning system, reasoning engine, and safety monitor.

## Key Files
| File | Description |
|------|-------------|
| `test_agent_council.py` | Tests for multi-agent council (ADR-012): 6 typed agents, MessageBus routing, AuthorityHierarchy |
| `test_learning_system.py` | Tests for post-settlement feedback loop (ADR-013): forensics, lesson extraction, brain storage |
| `test_reasoning_engine.py` | Tests for cognitive reasoning engine |
| `test_safety_monitor.py` | Tests for safety monitor and circuit breaker logic |

## For AI Agents

### Testing Requirements
- Run all: `pytest backend/core/tests/ -v`
- Run specific: `pytest backend/core/tests/test_agent_council.py -v`
- These tests use mocked dependencies — no DB or live data required

## Dependencies

### Internal
- `backend.core` — core modules under test
- `pytest` — test framework
