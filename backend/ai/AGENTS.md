<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-09 | Updated: 2026-05-09 -->

# backend/ai

## Purpose
LLM routing, multi-agent debate, signal parsing, market analysis, and ML model training. Provides the AI layer that converts market data into trading signals and probability estimates.

## Key Files

| File | Description |
|------|-------------|
| `llm_router.py` | `LLMRouter` — routes LLM calls to the right provider by role (`debate_agent`→Groq, `judge`→Claude, `claude_escalation`→Claude) |
| `debate_engine.py` | Bull/Bear/Judge self-debate (RA-CR protocol) — Bull argues YES, Bear argues NO, Judge synthesizes consensus |
| `debate_router.py` | Routes debate requests and manages debate session lifecycle |
| `signal_parser.py` | Converts MiroFish API responses to internal `Signal` format; aggregates with strategy signals |
| `market_analyzer.py` | Market condition analysis — trend, volatility, liquidity assessment |
| `sentiment_analyzer.py` | News and social sentiment analysis |
| `narrative_engine.py` | Narrative-driven probability estimation |
| `prediction_engine.py` | Composite prediction from multiple AI sources |
| `ensemble.py` | Ensemble model combining multiple signal sources |
| `claude.py` | Anthropic Claude API client |
| `groq.py` | Groq API client (fast inference) |
| `gemini.py` | Google Gemini API client |
| `custom.py` | Custom/local model client |
| `base.py` | Base LLM client interface |
| `mirofish_client.py` | MiroFish external debate system client |
| `bayesian_optimizer.py` | Bayesian hyperparameter optimization |
| `meta_learner.py` | Meta-learning across strategy performance |
| `online_learner.py` | Online learning from trade outcomes (alias/integration point) |
| `feedback_tracker.py` | Tracks prediction accuracy for model improvement |
| `rejection_learner.py` | Learns from rejected trade signals |
| `counterfactual_scorer.py` | Scores counterfactual trade outcomes |
| `impact_measurer.py` | Measures signal impact on market prices |
| `self_review.py` | AI self-review of past decisions |
| `proposal_generator.py` | Generates strategy improvement proposals |
| `optimizer.py` | Strategy parameter optimization |
| `probability_utils.py` | Probability math utilities |
| `model_integrity.py` | ML model hash verification |
| `logger.py` | AI-specific structured logging |
| `models/` | Serialized ML model artifacts (`baseline.pkl`) |
| `providers/` | LLM provider plugins — Claude, Gemini, Groq, OpenRouter (auto-discovered) |
| `training/` | Model training pipeline — data collection, feature engineering, training, evaluation |

## For AI Agents

### Working In This Directory
- **LLM provider routing is role-based** — never hardcode a provider. Use `LLMRouter` with the appropriate role: `"debate_agent"` for cheap bulk calls, `"judge"` for synthesis, `"claude_escalation"` for high-stakes decisions.
- **MiroFish signals are advisory** — they are weighted votes, not directives. `signal_parser.py` aggregates them with strategy signals; the weight is configurable via `settings.MIROFISH_SIGNAL_WEIGHT`.
- **Debate engine is Bull/Bear/Judge** — Bull and Bear use cheap models (Groq), Judge uses the smart model (Claude when available). Do not swap roles without updating `ROLE_SETTING_MAP` in `llm_router.py`.
- Model artifacts in `models/` are versioned by hash in `model_hashes.json` — verify integrity with `model_integrity.py` before using a loaded model.
- Training scripts in `training/` are offline — they do not run during normal bot operation.
- AGI synthesis/composition code must not keep a DB session open while awaiting LLMs or backtests. Read prompt/backtest inputs with a short-lived session, close it, then await external work, and reopen a fresh session only for registration/writeback.

### Testing Requirements
- Mock all LLM API calls — never make real API calls in tests (cost + flakiness)
- Test `signal_parser.py` with malformed inputs — it must log and skip, never crash
- Test `debate_engine.py` with mocked Bull/Bear/Judge responses

### Common Patterns
- Route an LLM call: `router = LLMRouter(); response = await router.complete(role="debate_agent", prompt=...)`
- Parse a MiroFish signal: `parser = SignalParser(); signals = parser.parse_mirofish_response(response)`
- Run a debate: `engine = DebateEngine(); result = await engine.debate(market_context)`

## Dependencies

### Internal
- `backend.config` — `settings` for API keys and provider selection
- `backend.core.signals` — `Signal` dataclass
- `backend.models.database` — DB persistence for signals

### External
- `anthropic` — Claude API
- `groq` — Groq API
- `google-generativeai` — Gemini API
- `scikit-learn` — ML model training
- `numpy` / `pandas` — numerical computation
