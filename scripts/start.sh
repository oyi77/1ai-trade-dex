#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo "=== PolyEdge Engine Start ==="
echo "Project: $PROJECT_DIR"

if command -v pm2 &> /dev/null; then
    echo "[PM2] Starting all services..."
    pm2 start ecosystem.config.js
    pm2 save
    echo "[PM2] All services started:"
    pm2 list
else
    echo "[WARN] PM2 not found. Install with: npm install -g pm2"
    echo "[INFO] Starting services manually..."

    if [ ! -d "venv" ]; then
        echo "[INFO] Creating Python venv..."
        python3 -m venv venv
    fi

    source venv/bin/activate

    echo "[INFO] Starting polyedge-api (backend)..."
    DISABLE_TRADING_SCHEDULER=true PYTHONPATH="$PROJECT_DIR" nohup python run.py > .omc/logs/polyedge-api-out.log 2>&1 &

    echo "[INFO] Starting polyedge-bot (orchestrator)..."
    PYTHONPATH="$PROJECT_DIR" nohup python -m backend.core.orchestrator > .omc/logs/polyedge-bot-out.log 2>&1 &

    if [ -d "frontend" ]; then
        echo "[INFO] Starting polyedge-frontend..."
        (cd frontend && nohup npm run dev > ../.omc/logs/polyedge-frontend-out.log 2>&1 &)
    fi

    echo "[DONE] All services started."
fi
