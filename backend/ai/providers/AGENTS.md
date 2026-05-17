<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 -->

# ai/providers

## Purpose
LLM provider plugin implementations. Each provider wraps a specific AI API (Claude, Gemini, Groq, OpenRouter) behind a common interface. Auto-discovered and registered by the provider registry on import.

## Key Files
| File | Description |
|------|-------------|
| `__init__.py` | Triggers auto-discovery via `provider_registry.auto_discover("backend.ai.providers")` |
| `claude_provider.py` | Anthropic Claude API provider — used for high-stakes judgments and synthesis |
| `gemini_provider.py` | Google Gemini API provider |
| `groq_provider.py` | Groq API provider — fast inference for bulk debate calls |
| `openrouter_provider.py` | OpenRouter API provider — routes to multiple LLM backends |

## For AI Agents

### Working In This Directory
- Providers are auto-discovered — adding a new file with a `BaseLLMProvider` subclass is sufficient
- Each provider declares a manifest with role mappings (e.g., `debate_agent` -> Groq, `judge` -> Claude)
- Provider selection is role-based via `LLMRouter` in `backend/ai/llm_router.py`
- Never hardcode provider URLs — use `settings` from `backend.config`

### Testing Requirements
- Mock all API calls — never make real LLM calls in tests
- Test provider health checks with simulated failures

### Common Patterns
- Route a call: `router = LLMRouter(); response = await router.complete(role="debate_agent", prompt=...)`
- Register a provider: subclass `BaseLLMProvider`, implement `manifest()` and `complete()`

## Dependencies

### Internal
- `backend.ai.provider_registry` — `provider_registry` singleton
- `backend.config` — `settings` for API keys

### External
- `anthropic` — Claude API
- `google-generativeai` — Gemini API
- `groq` — Groq API
- `httpx` — HTTP client for OpenRouter
