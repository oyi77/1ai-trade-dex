# PolyEdge Engine Scripts

Cross-platform scripts to start, stop, and restart the PolyEdge trading bot engine.

## Quick Start

```bash
# Start all services (backend + frontend + bot)
bash scripts/start.sh    # Linux/macOS
# or
powershell scripts\start.ps1   # Windows PowerShell

# Stop all services
bash scripts/stop.sh
# or
powershell scripts\stop.ps1

# Restart all services
bash scripts/restart.sh
# or
powershell scripts\restart.ps1
```

## Prerequisites

- **PM2** (recommended, auto-restart on crash and on boot): `npm install -g pm2`
- **Python 3.10+** with `venv` module for backend
- **Node.js 18+** for frontend
- **Git** for initial clone
- **PostgreSQL 16+** with a `polyedge` database
- **Redis** (optional, for job queue)

## First-Time Setup

```bash
# 1. Clone the repo
git clone <repo-url>
cd polyedge

# 2. Set up backend
python -m venv venv
source venv/bin/activate   # or: venv\Scripts\Activate.ps1 on Windows
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your API keys

# 3. Set up frontend
cd frontend
npm install
cd ..

# 4. Run the engine
bash scripts/start.sh
```

## Boot Persistence

After starting once via `start.sh` (which uses PM2), enable on-boot startup:

```bash
pm2 startup
# PM2 will print a command to run — execute it
# Then:
pm2 save
```

## Access Points

| Service | Default URL | Description |
|---------|-------------|-------------|
| Frontend | http://localhost:5174 | React dashboard |
| API | http://localhost:8100 | FastAPI backend |
| API Docs | http://localhost:8100/docs | Swagger UI |

## Troubleshooting

- **Port already in use**: `lsof -i :5174` / `lsof -i :8100` to find and kill the process
- **Database connection error**: Check PostgreSQL is running and the `polyedge` DB exists: `sudo -u postgres psql -c "\l"`
- **Check logs**: `tail -f .omc/logs/*-error.log`
- **Check PM2 status**: `pm2 list`
- **View full logs via PM2**: `pm2 logs polyedge-api`

## Files

| File | Description |
|------|-------------|
| `start.sh` | Start all services (Linux/macOS) |
| `stop.sh` | Stop all services (Linux/macOS) |
| `restart.sh` | Restart all services (Linux/macOS) |
| `start.ps1` | Start all services (Windows PowerShell) |
| `stop.ps1` | Stop all services (Windows PowerShell) |
| `restart.ps1` | Restart all services (Windows PowerShell) |