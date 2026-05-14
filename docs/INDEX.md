# Documentation Index

**Quick Navigation Guide to All PolyEdge Documentation**

---

## 🚨 CRITICAL: Recent Fixes

Start here if you just deployed or are investigating recent issues:

- **[ULTRAWORK_COMPLETION_SUMMARY.md](ULTRAWORK_COMPLETION_SUMMARY.md)** — Status of position consolidation bug fix [EXEC-1], what's complete, what's waiting
- **[PREVENTION_FRAMEWORK.md](PREVENTION_FRAMEWORK.md)** — Why AGI missed the position consolidation bug and how to prevent similar issues
- **[DEPLOYMENT_REPORT.md](DEPLOYMENT_REPORT.md)** — Verification checklist for [EXEC-1] deployment
- **[DEPLOYMENT.md](DEPLOYMENT.md)** — How to deploy code, restart services, verify health

---

## 📚 Getting Started

**New to PolyEdge?** Start here:

1. **[../README.md](../README.md)** — Project overview, features, setup guide
2. **[ONBOARDING.md](ONBOARDING.md)** — Detailed onboarding guide for new developers
3. **[project-structure.md](project-structure.md)** — Codebase organization and module breakdown
4. **[how-it-works.md](how-it-works.md)** — How the trading bot makes decisions

---

## 🏗️ Architecture & Design

Understanding the system design:

- **[../ARCHITECTURE.md](../ARCHITECTURE.md)** — High-level architecture with execution path invariants
- **[../AGENTS.md](../AGENTS.md)** — Agent catalog with architectural rules
- **[SYSTEM_FLOW.md](SYSTEM_FLOW.md)** — Detailed system flow and data movement
- **[../IMPLEMENTATION_GAPS.md](../IMPLEMENTATION_GAPS.md)** — Known gaps and incomplete features

---

## 🔧 Configuration & Setup

Configuring and deploying:

- **[configuration.md](configuration.md)** — All environment variables and settings
- **[config-system.md](config-system.md)** — Configuration system architecture
- **[../POLYMARKET_SETUP.md](../POLYMARKET_SETUP.md)** — Polymarket API credential setup
- **[DEPLOYMENT.md](DEPLOYMENT.md)** — How to deploy and restart services

---

## 📊 Market Data & Analysis

Data sources and market analysis:

- **[data-sources.md](data-sources.md)** — All data provider integrations
- **[mirofish-integration.md](mirofish-integration.md)** — MiroFish debate engine integration
- **[POLYMARKET_LEADERBOARD_API.md](POLYMARKET_LEADERBOARD_API.md)** — Polymarket leaderboard data API

---

## 🤖 Strategies & Signal Generation

How trading strategies work:

- **[SYSTEM_FLOW.md](SYSTEM_FLOW.md)** — Complete trading signal flow
- **[how-it-works.md](how-it-works.md)** — Strategy decision-making process
- **[RESEARCH_SUMMARY.md](RESEARCH_SUMMARY.md)** — Research findings on strategies
- **[RESEARCH_CHECKLIST.md](RESEARCH_CHECKLIST.md)** — Implementation checklist

---

## 💰 Financial & Risk

Financial calculations and risk management:

- **[fee-calculation.md](fee-calculation.md)** — How trading fees are calculated
- **[api-versioning.md](api-versioning.md)** — API versioning strategy
- **[CHANGELOG.md](CHANGELOG.md)** — Version history and changes

---

## 📖 API & Integration

API reference and integrations:

- **[api.md](api.md)** — REST API endpoint documentation
- **[mirofish-integration.md](mirofish-integration.md)** — MiroFish AI debate system
- **[api-versioning.md](api-versioning.md)** — API versioning and deprecation

---

## 🗄️ Database & Persistence

Database design and migration:

- **[postgresql-migration-plan.md](postgresql-migration-plan.md)** — PostgreSQL migration strategy
- **[validation-implementation.md](validation-implementation.md)** — Data validation rules

---

## 📋 Planning & Roadmap

Planning and future work:

- **[IMPLEMENTATION_ROADMAP_AGI_ENHANCEMENTS.md](IMPLEMENTATION_ROADMAP_AGI_ENHANCEMENTS.md)** — AI agent enhancements roadmap
- **[RESEARCH_INDEX.md](RESEARCH_INDEX.md)** — Index of research documents

---

## 🔍 Problem Investigation

Finding answers to common questions:

- **[KNOWLEDGE_BASE.md](KNOWLEDGE_BASE.md)** — Frequently encountered issues and solutions
- **[../IMPLEMENTATION_GAPS.md](../IMPLEMENTATION_GAPS.md)** — Known limitations and TODO items

---

## 🎓 Research & Analysis

Detailed analysis documents:

- **[RESEARCH_SUMMARY.md](RESEARCH_SUMMARY.md)** — Summary of research findings
- **[RESEARCH_INDEX.md](RESEARCH_INDEX.md)** — Index of all research documents
- **[PREDICTION_MARKET_ANALYSIS_REPO_FINDINGS.md](PREDICTION_MARKET_ANALYSIS_REPO_FINDINGS.md)** — Market analysis findings
- **[RESEARCH_CHECKLIST.md](RESEARCH_CHECKLIST.md)** — Implementation verification checklist

---

## 📁 File Organization

```
polyedge/
├── README.md                           (Project overview)
├── ARCHITECTURE.md                     (High-level architecture)
├── AGENTS.md                           (Agent catalog + rules)
├── IMPLEMENTATION_GAPS.md              (Known gaps)
├── POLYMARKET_SETUP.md                 (Polymarket setup)
├── docs/
│   ├── INDEX.md                        ← You are here
│   ├── ULTRAWORK_COMPLETION_SUMMARY.md (Status of critical fixes)
│   ├── PREVENTION_FRAMEWORK.md         (Why AGI missed [EXEC-1] bug)
│   ├── DEPLOYMENT_REPORT.md            (Verification checklist)
│   ├── DEPLOYMENT.md                   (How to deploy)
│   ├── ONBOARDING.md                   (New developer guide)
│   ├── SYSTEM_FLOW.md                  (Complete system flow)
│   ├── configuration.md                (Env variables)
│   ├── api.md                          (API reference)
│   ├── how-it-works.md                 (Strategy logic)
│   └── ... (30+ other docs)
├── backend/
│   ├── core/
│   │   ├── hft_executor.py             (HFT trading executor)
│   │   ├── auto_trader.py              (Automated trader)
│   │   ├── strategy_executor.py        (Strategy runner)
│   │   └── ...
│   └── ...
└── ... (config, tests, frontend, etc)
```

---

## 🎯 Common Tasks

**I want to...**

### Deploy the application
→ Read [DEPLOYMENT.md](DEPLOYMENT.md)

### Understand how trading works
→ Read [how-it-works.md](how-it-works.md) then [SYSTEM_FLOW.md](SYSTEM_FLOW.md)

### Add a new trading strategy
→ Read [SYSTEM_FLOW.md](SYSTEM_FLOW.md) then look at existing strategies in `backend/core/`

### Configure the system
→ Read [configuration.md](configuration.md) and [../POLYMARKET_SETUP.md](../POLYMARKET_SETUP.md)

### Fix a bug or issue
→ Check [KNOWLEDGE_BASE.md](KNOWLEDGE_BASE.md) then [../IMPLEMENTATION_GAPS.md](../IMPLEMENTATION_GAPS.md)

### Investigate why position consolidation bug happened
→ Read [PREVENTION_FRAMEWORK.md](PREVENTION_FRAMEWORK.md)

### Verify deployment of critical fix [EXEC-1]
→ Read [DEPLOYMENT_REPORT.md](DEPLOYMENT_REPORT.md)

### Understand architectural rules
→ Read [../AGENTS.md](../AGENTS.md) (Architectural Rules section)
→ Read [../ARCHITECTURE.md](../ARCHITECTURE.md) (Execution Path Invariants section)

---

## 📞 Quick Reference

### Critical Fix [EXEC-1] Status
- **What:** Position consolidation bug (15+ duplicate positions)
- **Status:** Fixed and documented
- **Details:** [ULTRAWORK_COMPLETION_SUMMARY.md](ULTRAWORK_COMPLETION_SUMMARY.md)
- **Prevention:** [PREVENTION_FRAMEWORK.md](PREVENTION_FRAMEWORK.md)
- **Deployment:** [DEPLOYMENT_REPORT.md](DEPLOYMENT_REPORT.md)

### Key Files to Know
- `backend/core/hft_executor.py` — HFT trading execution
- `backend/core/auto_trader.py` — Automated trading signals
- `backend/core/strategy_executor.py` — Strategy orchestration
- `backend/core/autonomous_promoter.py` — Strategy lifecycle management
- `backend/models/database.py` — Data models

### Important Environment Variables
- `TRADING_MODE` — `paper` or `live`
- `DATABASE_URL` — PostgreSQL connection string
- `MIROFISH_ENABLED` — Enable debate engine
- `REDIS_URL` — Cache backend
- See [configuration.md](configuration.md) for complete list

---

## 📈 Documentation Statistics

- **Total Documents:** 30+
- **Lines of Documentation:** 5,000+
- **Critical Fixes Documented:** 1 ([EXEC-1])
- **Architecture Rules:** 1 (Execution Path Consistency)
- **Deployment Guides:** 2 (DEPLOYMENT.md + DEPLOYMENT_REPORT.md)
- **Prevention Patterns:** 4 (in PREVENTION_FRAMEWORK.md)

---

## 🔄 Keeping Documentation Updated

When you make changes:

1. Update relevant documentation in `/docs/`
2. Update root `README.md` if it's major
3. Update `ARCHITECTURE.md` if it affects system design
4. Update `AGENTS.md` if it affects agent behavior
5. Update this `INDEX.md` if you add new docs

---

**Last Updated:** 2026-05-15  
**Status:** Complete and organized  
**Maintainer:** Development team
