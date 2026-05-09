<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-09 | Updated: 2026-05-09 -->

# backend/integrations

## Purpose
External system integrations. Provides connectors to third-party services and platforms.

## Key Files

| File | Description |
|------|-------------|
| `bk_brain.py` | bk-brain memory service connector. Integrates with the external brain service for persistent memory and context sharing across sessions. |

## For AI Agents

### Working In This Directory
- All integrations use async HTTP clients with timeout and retry logic
- API keys are read from environment variables, never hardcoded
- Handle integration failures gracefully — fall back to local state if external service is unavailable

### Common Patterns
- Use `httpx.AsyncClient` with 10s timeout for external API calls
- Wrap calls in try/except and log failures without crashing

## Dependencies

### Internal
- `backend.config` — API key and endpoint configuration

### External
- `httpx` — Async HTTP client

<!-- MANUAL: -->
