#!/usr/bin/env bash
# Auto-restart wrapper for PolyEdge bot processes.
# Restarts the process on crash with exponential backoff.
#
# Usage:
#   backend/scripts/auto_restart.sh [command...]
#   backend/scripts/auto_restart.sh python run.py
#   backend/scripts/auto_restart.sh python -m backend.core.orchestrator
#
# Environment variables:
#   MAX_RETRIES      - Max consecutive restarts before giving up (default: 10)
#   INITIAL_BACKOFF  - Initial backoff in seconds (default: 1)
#   MAX_BACKOFF      - Maximum backoff in seconds (default: 30)
#   RESET_AFTER      - Seconds of uptime before resetting retry counter (default: 60)

set -euo pipefail

MAX_RETRIES="${MAX_RETRIES:-10}"
INITIAL_BACKOFF="${INITIAL_BACKOFF:-1}"
MAX_BACKOFF="${MAX_BACKOFF:-30}"
RESET_AFTER="${RESET_AFTER:-60}"

if [ $# -eq 0 ]; then
    echo "Usage: $0 <command...>"
    echo "Example: $0 python run.py"
    exit 1
fi

attempt=0
backoff="$INITIAL_BACKOFF"

while true; do
    attempt=$((attempt + 1))
    echo "[auto_restart] Starting attempt $attempt: $*"
    start_time=$(date +%s)

    # Run the command; capture exit code
    "$@" &
    pid=$!
    wait "$pid" || true
    exit_code=$?

    end_time=$(date +%s)
    uptime=$((end_time - start_time))

    echo "[auto_restart] Process exited with code $exit_code after ${uptime}s"

    # Reset counter if process ran long enough (considered stable)
    if [ "$uptime" -ge "$RESET_AFTER" ]; then
        attempt=0
        backoff="$INITIAL_BACKOFF"
        echo "[auto_restart] Process was stable for ${uptime}s, resetting retry counter"
    fi

    # Check max retries
    if [ "$attempt" -ge "$MAX_RETRIES" ]; then
        echo "[auto_restart] Max retries ($MAX_RETRIES) reached. Giving up."
        exit "$exit_code"
    fi

    echo "[auto_restart] Restarting in ${backoff}s (attempt $attempt/$MAX_RETRIES)..."
    sleep "$backoff"

    # Exponential backoff, capped at MAX_BACKOFF
    backoff=$((backoff * 2))
    if [ "$backoff" -gt "$MAX_BACKOFF" ]; then
        backoff="$MAX_BACKOFF"
    fi
done
