#!/usr/bin/env bash
# engine-daemon.sh — Auto-restart wrapper for 1ai-trade-dex orchestrator
# Runs the engine in a forever loop, logging each restart.
set -eo pipefail

cd /home/openclaw/projects/1ai-trade-dex || exit 1
LOG_DIR="logs"
mkdir -p "$LOG_DIR"

RESTART_DELAY=5
MAX_RESTARTS_PER_HOUR=6
COOLDOWN_FILE="/tmp/engine-daemon-cooldown"

cleanup() {
    echo "[engine-daemon] Caught signal, stopping engine..."
    pkill -f "backend.core.orchestrator" 2>/dev/null || true
    exit 0
}
trap cleanup SIGINT SIGTERM SIGHUP

echo "[engine-daemon] Starting 1ai-trade-dex orchestrator daemon"
echo "[engine-daemon] PID: $$"

restart_count=0
last_hour=0

while true; do
    # Rate limiting - max 6 restarts per hour
    current_hour=$(date +%H)
    if [ "$current_hour" != "$last_hour" ]; then
        restart_count=0
        last_hour=$current_hour
    fi
    
    if [ "$restart_count" -ge "$MAX_RESTARTS_PER_HOUR" ]; then
        echo "[engine-daemon] Too many restarts ($restart_count/hr), cooling down for 10 min"
        sleep 600
        restart_count=0
    fi

    echo "[engine-daemon] $(date '+%Y-%m-%d %H:%M:%S') Starting orchestrator (restart #$((restart_count+1)))"
    
    # Run the orchestrator - it will exit on its own or be killed
    .venv/bin/python -m backend.core.orchestrator 2>&1 || true
    
    exit_code=$?
    echo "[engine-daemon] $(date '+%Y-%m-%d %H:%M:%S') Orchestrator exited (code=$exit_code)"
    
    restart_count=$((restart_count + 1))
    sleep "$RESTART_DELAY"
done
