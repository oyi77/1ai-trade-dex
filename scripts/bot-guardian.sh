#!/bin/bash
# bot-guardian.sh — External liveness monitor for polyedge-bot
#
# Checks the heartbeat file touched by the watchdog job every 30 seconds.
# If the heartbeat file is older than HEARTBEAT_MAX_AGE seconds, the bot's
# event loop is frozen — force-restart it.
#
# FIXED: Uses PID file to track single instance. No PM2 dependency.
# FIXED: Kills ALL polyedge backend processes before restart.
# FIXED: Only one instance can run at a time.

set -euo pipefail

POLYEDGE_ROOT="${POLYEDGE_ROOT:-/home/openclaw/projects/polyedge}"
HEARTBEAT_FILE="${POLYEDGE_ROOT}/.omc/bot-heartbeat.tmp"
PID_FILE="${POLYEDGE_ROOT}/.omc/bot.pid"
LOCK_FILE="/tmp/polyedge-guardian.lock"
HEARTBEAT_MAX_AGE="${BOT_HEARTBEAT_MAX_AGE:-120}"
CHECK_INTERVAL="${BOT_CHECK_INTERVAL:-30}"
STARTUP_GRACE_SECONDS="${BOT_STARTUP_GRACE_SECONDS:-180}"
VENV_PYTHON="${POLYEDGE_ROOT}/venv/bin/python"
LOG_FILE="/tmp/polyedge-backend.log"

# ── Guardian lock: only one guardian can run ──
exec 200>"${LOCK_FILE}"
if ! flock -n 200; then
    echo "[guardian] ERROR: Another guardian is already running. Exiting."
    exit 1
fi

# ── Kill ALL polyedge backend processes ──
kill_all_backends() {
    echo "[guardian] Killing ALL polyedge backend processes..."
    pkill -f "python -m backend" 2>/dev/null || true
    pkill -f "python.*polyedge.*backend" 2>/dev/null || true
    sleep 2
    # Force kill survivors
    pkill -9 -f "python -m backend" 2>/dev/null || true
    pkill -9 -f "python.*polyedge.*backend" 2>/dev/null || true
    sleep 1
    # Clean up PID file
    rm -f "${PID_FILE}"
    echo "[guardian] All backend processes killed."
}

# ── Check if our managed process is alive ──
is_bot_alive() {
    if [[ ! -f "${PID_FILE}" ]]; then
        return 1
    fi
    local pid
    pid=$(cat "${PID_FILE}" 2>/dev/null)
    if [[ -z "${pid}" ]]; then
        return 1
    fi
    if kill -0 "${pid}" 2>/dev/null; then
        return 0
    fi
    # Stale PID file
    rm -f "${PID_FILE}"
    return 1
}

# ── Get managed bot PID ──
bot_pid() {
    if [[ -f "${PID_FILE}" ]]; then
        cat "${PID_FILE}" 2>/dev/null
    fi
}

# ── Get bot uptime in seconds ──
bot_uptime_seconds() {
    local pid
    pid="$(bot_pid)"
    if [[ -z "${pid}" ]]; then
        echo 0
        return
    fi
    ps -o etimes= -p "${pid}" 2>/dev/null | tr -d '[:space:]' || echo 0
}

# ── Start the bot ──
start_bot() {
    echo "[guardian] Starting polyedge-bot..."
    
    # Kill any existing processes first
    kill_all_backends
    
    # Create PID directory
    mkdir -p "$(dirname "${PID_FILE}")"
    
    # Start bot in background, capture PID
    cd "${POLYEDGE_ROOT}"
    nohup "${VENV_PYTHON}" -m backend > "${LOG_FILE}" 2>&1 &
    local new_pid=$!
    
    # Save PID
    echo "${new_pid}" > "${PID_FILE}"
    
    echo "[guardian] Bot started with PID: ${new_pid}"
    echo "[guardian] Log: ${LOG_FILE}"
    
    # Wait a moment and verify
    sleep 3
    if kill -0 "${new_pid}" 2>/dev/null; then
        echo "[guardian] Bot is running. PID: ${new_pid}"
    else
        echo "[guardian] ERROR: Bot failed to start! Check ${LOG_FILE}"
        rm -f "${PID_FILE}"
        return 1
    fi
}

# ── Restart the bot ──
restart_bot() {
    echo "[guardian] Restarting polyedge-bot..."
    start_bot
}

# ── Initial cleanup: kill zombies, start fresh ──
echo "[guardian] === POLYEDGE BOT GUARDIAN ==="
echo "[guardian] Heartbeat max age: ${HEARTBEAT_MAX_AGE}s"
echo "[guardian] Check interval: ${CHECK_INTERVAL}s"
echo "[guardian] Startup grace: ${STARTUP_GRACE_SECONDS}s"
echo "[guardian] PID file: ${PID_FILE}"
echo "[guardian] Heartbeat file: ${HEARTBEAT_FILE}"

# On guardian start: kill zombies and start fresh
if ! is_bot_alive; then
    echo "[guardian] No managed bot found. Cleaning up zombies and starting fresh..."
    start_bot
else
    echo "[guardian] Managed bot already running (PID: $(bot_pid))"
fi

# ── Main monitoring loop ──
while true; do
    sleep "${CHECK_INTERVAL}"
    
    # Check if managed process is alive
    if ! is_bot_alive; then
        echo "[guardian] CRITICAL: Bot process died! Restarting..."
        start_bot
        continue
    fi
    
    # Check uptime for grace period
    uptime="$(bot_uptime_seconds)"
    if [[ "${uptime}" -lt "${STARTUP_GRACE_SECONDS}" ]]; then
        echo "[guardian] Grace period (uptime: ${uptime}s < ${STARTUP_GRACE_SECONDS}s)"
        continue
    fi
    
    # Check heartbeat file
    if [[ ! -f "${HEARTBEAT_FILE}" ]]; then
        echo "[guardian] WARNING: Heartbeat file missing (may be normal during startup)"
        continue
    fi
    
    # Get heartbeat age
    now=$(date +%s)
    file_mtime=$(stat -c %Y "${HEARTBEAT_FILE}" 2>/dev/null || echo 0)
    age=$(( now - file_mtime ))
    
    if [[ ${age} -gt ${HEARTBEAT_MAX_AGE} ]]; then
        echo "[guardian] CRITICAL: Heartbeat stale (${age}s > ${HEARTBEAT_MAX_AGE}s). Restarting..."
        restart_bot
    else
        echo "[guardian] OK — heartbeat age: ${age}s, bot PID: $(bot_pid)"
    fi
done
