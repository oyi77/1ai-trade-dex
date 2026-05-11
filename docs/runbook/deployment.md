# Deployment

## Pre-deployment Health Check

```bash
# Backend health
curl -f http://localhost:8100/api/health

# Frontend build
cd frontend && npm run build

# Backend tests
pytest backend/tests/ -v --tb=short

# Frontend tests
cd frontend && npm run test
```

## Backend (Railway)

1. Push to `main` branch — Railway auto-deploys
2. Verify `railway.json` is present in repo root
3. Set environment variables in Railway dashboard (see `.env.example` for full list)
4. Key env vars:
   - `TRADING_MODE=paper` for shadow, `TRADING_MODE=live` for production
   - `DATABASE_URL` — SQLite path or PostgreSQL connection string
   - `REDIS_URL` — Redis connection for job queue
   - `POLYGON_RPC_URL` — Polygon RPC endpoint
   - `CLOB_API_URL` — Polymarket CLOB endpoint
   - `ADMIN_API_KEY` — Dashboard admin password

## Frontend (Vercel)

1. Push to `main` — Vercel auto-deploys from `frontend/` directory
2. Verify `vercel.json` is present
3. Set `VITE_API_URL` to backend URL
4. Polling intervals configurable: `VITE_POLL_FAST_MS`, `VITE_POLL_NORMAL_MS`, `VITE_POLL_SLOW_MS`, `VITE_POLL_VERY_SLOW_MS`

## Docker Compose (Alternative)

```bash
docker-compose up -d                    # App + Redis
docker-compose --profile monitoring up -d  # + Grafana
docker-compose --profile prod up -d      # + PostgreSQL
```

## PM2 Process Management

```bash
pm2 start ecosystem.config.js
pm2 status
pm2 logs
pm2 restart all
```

PM2 manages: API server, queue worker, scheduler.
