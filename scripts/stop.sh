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
else
    echo "[WARNING] PM2 not found. To stop processes manually, find their PIDs and kill them."
fi
