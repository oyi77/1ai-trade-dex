#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo "=== PolyEdge Engine Stop ==="

if command -v pm2 &> /dev/null; then
    echo "[PM2] Stopping all services..."
    pm2 stop ecosystem.config.js 2>/dev/null || true
    echo "[PM2] All services stopped."
    pm2 list
else
    echo "[INFO] Stopping Python processes..."
    pkill -f "python run.py" 2>/dev/null || true
    pkill -f "backend.core.orchestrator" 2>/dev/null || true
    pkill -f "vite" 2>/dev/null || true
    echo "[DONE] All processes stopped."
fi
