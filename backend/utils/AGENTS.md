<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-09 | Updated: 2026-05-09 -->

# backend/utils

## Purpose
Utility functions and helpers shared across the backend. Contains redaction utilities for sensitive data and other cross-cutting concerns.

## Key Files

| File | Description |
|------|-------------|
| `redaction.py` | Redacts sensitive data (API keys, wallet addresses, private keys) from logs and error messages. Prevents accidental credential leakage. |

## For AI Agents

### Working In This Directory
- All log output must pass through `redaction.py` before writing to disk or sending to external services
- Add new redaction patterns to `REDACTION_PATTERNS` list
- Never log raw API keys or wallet private keys

### Common Patterns
- Use `redact_sensitive(text)` before logging any user input or API response
- Pattern matching uses regex for flexibility

## Dependencies

### External
- `re` — Regex pattern matching

<!-- MANUAL: -->
