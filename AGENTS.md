<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 | Updated: 2026-05-17 -->

# 1ai-poly-trader

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