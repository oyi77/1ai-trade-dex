#!/bin/bash
# bot-guardian.sh — External liveness monitor for polyedge-bot
#
# Checks the heartbeat file touched by the watchdog job every 30 seconds.
# If the heartbeat file is older than HEARTBEAT_MAX_AGE seconds, the bot's
# event loop is frozen — force-restart it via PM2.
#
# This runs OUTSIDE the bot's event loop so it is not affected by freezes.

set -euo pipefail

HEARTBEAT_FILE="${POLYEDGE_ROOT:-/home/openclaw/projects/polyedge}/.omc/bot-heartbeat.tmp"
HEARTBEAT_MAX_AGE="${BOT_HEARTBEAT_MAX_AGE:-120}"
CHECK_INTERVAL="${BOT_CHECK_INTERVAL:-30}"

echo "[guardian] Starting polyedge-bot guardian (max_age=${HEARTBEAT_MAX_AGE}s, interval=${CHECK_INTERVAL}s)"
echo "[guardian] Monitoring heartbeat file: ${HEARTBEAT_FILE}"

while true; do
    sleep "${CHECK_INTERVAL}"

    if [[ ! -f "${HEARTBEAT_FILE}" ]]; then
        echo "[guardian] WARNING: Heartbeat file missing. If bot was just started, this is expected for the first ~60s."
        continue
    fi

    # Get file age in seconds
    now=$(date +%s)
    file_mtime=$(stat -c %Y "${HEARTBEAT_FILE}" 2>/dev/null || stat -c %m "${HEARTBEAT_FILE}" 2>/dev/null || echo 0)
    age=$(( now - file_mtime ))

    if [[ $age -gt ${HEARTBEAT_MAX_AGE} ]]; then
        echo "[guardian] CRITICAL: Heartbeat stale by ${age}s (max: ${HEARTBEAT_MAX_AGE}s)!"
        echo "[guardian] Bot event loop appears frozen — force-restarting polyedge-bot..."
        pm2 restart polyedge-bot --update-env
        echo "[guardian] Restart triggered. Waiting $((CHECK_INTERVAL * 2))s before next check."
        sleep $((CHECK_INTERVAL * 2))
        # Force re-touch to reset the age counter after restart
    else
        echo "[guardian] Heartbeat OK (age: ${age}s)"
    fi
done
