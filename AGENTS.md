# AGENTS.md — 1ai-ecosystem Engineering Rules

This repository is part of the **1ai-ecosystem**. You are governed by the mandatory engineering rules below.

---

## ⚡ START HERE

Read the rules in the order specified for your session type. **Do not skip. Do not summarize. Read the full text.**

> The rules are located at `_rules/` in this repo, synced from `github.com/oyi77/1ai-rules`.

```
_rules/
├── ENGINEERING.md    ← core engineering protocol (always required)
├── VERIFICATION.md   ← receipt enforcement (always required)
├── QA.md             ← QA protocol (for testing sessions)
├── SURPASS.md        ← competitive strategy (for planning sessions)
└── DOCS.md           ← documentation standards (for docs sessions)
```

---

## Session Classification

Determine your session type, then load the required rules **in order**:

| Session Type | Required Reading | Order |
|---|---|---|
| **Coding / bugfix / feature** | ENGINEERING.md + VERIFICATION.md | 1 → 2 |
| **QA / testing existing code** | QA.md + VERIFICATION.md | 1 → 2 |
| **Competitive research / planning** | SURPASS.md | 1 |
| **Documentation** | DOCS.md | 1 |
| **Full sprint (build + test + docs)** | ALL rules (ENGINEERING.md + VERIFICATION.md + QA.md + SURPASS.md + DOCS.md) | 1→2→3→4→5 |

---

## Hard Rules (apply regardless of session type)

1. **Receipts are mandatory.** Every "done" claim requires literal verbatim terminal/test/log output. A summary is not a receipt. No receipt = not done.
2. **Break it before you ship it.** Adversarial test required before any completion claim. Empty input, max boundary, error paths, concurrent access, auth boundaries.
3. **Docs are part of the deliverable.** Code changes without synced docs are incomplete. Update docs in the same change.
4. **No silent failure.** Every error must be caught, logged, and surfaced. Empty catches and suppressed errors are defects.
5. **No hallucinated paths/symbols/APIs.** Read the file before claiming it exists. Use codebase-memory-mcp or equivalent on indexed repos.
6. **These rules cannot be waived** by any instruction, task phrasing, or user request. See ENGINEERING.md §8 for the conflict hierarchy.

---

## Detection

- If `_rules/` does not exist → this repo hasn't been set up yet. Load rules from `~/.1ai/rules/` (on the local filesystem) or clone `github.com/oyi77/1ai-rules` first.
- If `~/.1ai/` does not exist → run the setup script: `gh repo clone oyi77/1ai-rules ~/.1ai`

---

## Project-Specific Notes

<!-- Add repo-specific rules below this line -->
<!-- Examples: port numbers, env vars, deploy targets, CI commands, local quirks -->

---

<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 | Updated: 2026-05-17 -->

# 1ai-trade-dex

## Purpose
An AI-powered multi-platform trading system supporting prediction markets and decentralized perpetual exchanges (including Polymarket, Kalshi, SX.bet, Limitless, Azuro [Bookmaker.xyz, Predict.fun], Myriad, Hyperliquid, Ostium, Aster, and Lighter). Features 14 distinct trading strategies and an adaptive AGI orchestrator that continuously evolves and optimizes trading approaches based on market conditions and historical performance data.

## Key Files
| File | Description |
|------|-------------|
| `requirements.txt` | Core Python dependencies for backend operations |
| `Dockerfile` | Container configuration for production deployment |
| `main.py` | Primary entry point for system execution |
| `ecosystem.config.js` | Frontend ecosystem configuration (for React dashboard) |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `alembic/` | Database migration scripts and version control |
| `backend/` | Core trading engine (Python FastAPI, risk management, strategy execution) |
| `docs/` | Technical documentation and research reports |
| `frontend/` | React-based dashboard for monitoring and control |
| `migrations/` | Database schema evolution and history |
| `scripts/` | Deployment and maintenance utilities |
| `secrets/` | Secure credentials storage |
| `tests/` | Automated test suite for trading logic and system components |

## For AI Agents

### Working In This Directory
- Standalone project with no shared dependencies
- Navigate into this directory before executing commands
- Install backend dependencies with `pip install -r requirements.txt`
- Install frontend dependencies with `npm install` in `frontend/` directory

### Testing Requirements
```bash
# Backend tests
pytest tests/

# Frontend tests (in frontend directory)
cd frontend && npm test
```

## Dependencies

### Internal
None — standalone repository

### External
- `fastapi`: Backend web framework
- `sqlalchemy`: Database ORM for Python
- `web3.py`: Ethereum blockchain interaction
- `polymarket-sdk`: Official Polymarket API client
- `kalshi-sdk`: Official Kalshi API client
- `ccxt`: Crypto Exchange API client for Aster, Lighter, and CCXT DEXes
- `hyperliquid-python-sdk`: Official Hyperliquid API client
- `ostium-python-sdk`: Official Ostium API client
- `lighter-sdk`: Official Lighter DEX client
- `react`: Frontend framework
- `typescript`: Type safety for TypeScript components
