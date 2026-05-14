# Deployment & Service Management Guide

**Last Updated:** 2026-05-15  
**Purpose:** Instructions for deploying PolyEdge and restarting services

---

## Quick Start: Restart Service

### Using PM2 (Production)

```bash
# Restart the main app service
pm2 restart polyedge

# Restart all services
pm2 restart all

# Check service status
pm2 status

# View logs
pm2 logs polyedge

# View recent logs with tail
pm2 logs polyedge --lines 100
```

### Using Docker (Container Setup)

```bash
# Rebuild and restart
docker-compose down
docker-compose build
docker-compose up -d

# Check container logs
docker-compose logs -f app

# Restart just the app
docker-compose restart app
```

---

## Deployment Workflow

### 1. Merge Code to Main

```bash
# Ensure your branch is up to date
git checkout main
git pull origin main

# Verify latest code is there
git log --oneline -5
```

### 2. Run Tests Before Deployment

```bash
# Run all tests
pytest backend/tests/ -v

# Run specific test for critical fix
pytest -k duplicate_position -v

# Run integration tests
pytest backend/tests/integration/ -v

# Check code quality
mypy --strict backend/core/hft_executor.py
mypy --strict backend/core/auto_trader.py
```

### 3. Deploy to Staging (If Available)

```bash
# Deploy to staging environment
# (assumes staging config in .env.staging)

export ENV=staging
docker-compose -f docker-compose.staging.yml down
docker-compose -f docker-compose.staging.yml up -d

# Verify staging is running
curl -s http://staging:8000/api/v1/health | jq .
```

### 4. Run Smoke Tests

```bash
# Test critical execution paths
python backend/tests/smoke_tests/test_execution_paths.py

# Verify duplicate position blocking works
pytest -k "test_duplicate_position_blocked" -v

# Check MiroFish service is up
curl -s http://localhost:8100/api/v1/health/mirofish | jq .
```

### 5. Deploy to Production

```bash
# Pull latest code
git pull origin main

# Restart service (PM2)
pm2 restart polyedge

# OR restart with Docker
docker-compose down
docker-compose up -d

# Verify service is running
pm2 status
# OR
docker-compose ps
```

### 6. Monitor Logs After Deployment

```bash
# Watch logs for errors
pm2 logs polyedge --tail 100

# Look for duplicate position blocks (expected)
pm2 logs polyedge | grep "Duplicate position"

# Check for any errors
pm2 logs polyedge | grep -i error
```

---

## Health Checks

### Endpoints to Verify

```bash
# General health
curl -s http://localhost:8100/api/v1/health | jq .

# MiroFish debate engine
curl -s http://localhost:8100/api/v1/health/mirofish | jq .

# Dashboard available
curl -s http://localhost:3000 | head -20

# Database connectivity
curl -s http://localhost:8100/api/v1/health/db | jq .
```

### Expected Healthy Responses

```json
// /api/v1/health
{
  "status": "healthy",
  "version": "...",
  "database": "connected",
  "redis": "connected_or_not_required",
  "uptime_seconds": 12345
}

// /api/v1/health/mirofish
{
  "service": "mirofish",
  "status": "running",
  "circuit_breaker": "closed",
  "latency_ms": 45,
  "success_rate": 0.98
}
```

---

## Critical Fix: Position Consolidation [EXEC-1]

### What Changed

**Files Modified:**
- `backend/core/hft_executor.py` — Added duplicate position check
- `backend/core/auto_trader.py` — Added duplicate position validation
- `AGENTS.md` — Added architectural rules
- `ARCHITECTURE.md` — Added execution path invariants

### How to Verify Fix is Working

```bash
# Check logs for duplicate blocking
pm2 logs polyedge | grep "Duplicate position blocked"

# Run duplicate position test
pytest -k test_duplicate_position_blocked -v

# Expected output:
# PASSED test_duplicate_position_blocked[HFTExecutor]
# PASSED test_duplicate_position_blocked[AutoTrader]
# PASSED test_duplicate_position_blocked[StrategyExecutor]

# Verify duplicate positions don't exist in database
psql $DATABASE_URL -c "SELECT market_id, COUNT(*) as count FROM trades WHERE settled=false GROUP BY market_id HAVING COUNT(*) > 2;"

# Should return: (no rows - max 2 per market is expected for edge cases)
```

### What to Expect

**Normal operation:**
- 0-1 duplicate blocks per hour (occasional rapid signal bursts)
- 1-3 active positions per market
- No undefined method errors related to `_persist_to_db`

**If you see too many duplicates:**
- Check signal generation (debate engine, multiple strategies)
- Review recent trading signals in logs
- Check if market is particularly volatile (rapid probability changes)

---

## Rollback Procedures

If something goes wrong:

```bash
# Get recent commit hashes
git log --oneline -10

# Rollback to previous stable commit
git checkout <previous_stable_commit>

# Restart service
pm2 restart polyedge

# Verify service is running
pm2 status
```

---

## Environment Variables (Key for Deployment)

See `.env.example` for complete list. Key ones:

```bash
# Trading mode
TRADING_MODE=live  # or 'paper' for safer testing

# Database
DATABASE_URL=postgresql://user:pass@localhost/polyedge

# Redis (optional)
REDIS_URL=redis://localhost:6379

# API
API_HOST=0.0.0.0
API_PORT=8000

# Logging
LOG_LEVEL=INFO  # or DEBUG for more verbosity

# MiroFish debate service
MIROFISH_ENABLED=true
MIROFISH_API_KEY=<key>
MIROFISH_API_URL=https://api.mirofish.ai

# Trading parameters
AUTO_APPROVE_MIN_CONFIDENCE=0.65
MAX_CONCURRENT_POSITIONS=10
POSITION_SIZE_MULTIPLIER=1.0
```

---

## Monitoring Commands

```bash
# Real-time service status
watch -n 2 'pm2 status'

# Monitor CPU/memory
pm2 monit

# Show service ecosystem
pm2 show polyedge

# Show recent restarts/errors
pm2 logs polyedge --err
```

---

## Emergency Procedures

### Service Crashed

```bash
# Check what happened
pm2 logs polyedge --lines 50

# Restart service
pm2 restart polyedge --force

# If that doesn't work, kill and restart
pm2 delete polyedge
pm2 start ecosystem.config.js

# Verify it's running
pm2 status
```

### Database Connection Failed

```bash
# Check if database is running
psql $DATABASE_URL -c "SELECT 1;"

# If database is down, wait for it to recover
# Service will automatically retry connections

# Check database logs (varies by setup)
# Docker: docker-compose logs db
```

### Memory Leak Detected

```bash
# Check memory usage
pm2 monit

# If memory keeps growing:
pm2 restart polyedge

# Or set up auto-restart on memory threshold
pm2 set polyedge restart_max_memory 1000M
```

---

## Post-Deployment Checklist

- [ ] Service is running: `pm2 status` shows 'online'
- [ ] Health check passes: `curl http://localhost:8100/api/v1/health`
- [ ] MiroFish is up: `curl http://localhost:8100/api/v1/health/mirofish`
- [ ] Dashboard accessible: `curl http://localhost:3000`
- [ ] Logs are clean: `pm2 logs polyedge` shows no errors
- [ ] Duplicate position test passes: `pytest -k duplicate_position -v`
- [ ] No database connection errors in logs
- [ ] No undefined method errors (especially `_persist_to_db`)
- [ ] Trading signals are being processed
- [ ] No unusual error rates in logs

---

## Configuration After [EXEC-1] Fix

Make sure these are set correctly:

```bash
# CRITICAL: Must be set to prevent duplicate position creation
# (The new duplicate checks will still work, but these control behavior)

MAX_CONCURRENT_POSITIONS=10     # Max positions total
POSITION_CONSOLIDATION_ENABLED=true  # Enable duplicate check

# If you see too many duplicates blocked, check:
SIGNAL_GENERATION_RATE=...      # How many signals per minute?
DEBATE_ENGINE_CONFIDENCE=...    # Is it too low, generating noise?
HFT_ENABLED=true                # Is HFT competing with other strategies?
```

---

## References

- [PREVENTION_FRAMEWORK.md](PREVENTION_FRAMEWORK.md) — Why [EXEC-1] happened and how to prevent it
- [ARCHITECTURE.md](../ARCHITECTURE.md) — Execution Path Invariants (duplicate checks)
- [AGENTS.md](../AGENTS.md) — Architectural rules section
- [IMPLEMENTATION_GAPS.md](../IMPLEMENTATION_GAPS.md) — Status of fixes

---

**Last Updated:** 2026-05-15 | **Critical Fix:** Position Consolidation [EXEC-1]
