#!/usr/bin/env bash
# ==========================================================================
# PolyEdge Monitor Self-Wake — startup/restart script
# ==========================================================================
# Starts the autonomous monitor daemon in background.
# Can be used from: systemd, cron, command line, or AGI scheduler.
#
# Usage:
#   ./self_wake.sh start       Start monitor daemon
#   ./self_wake.sh stop        Stop monitor daemon
#   ./self_wake.sh restart     Restart monitor daemon
#   ./self_wake.sh status      Check if running
#   ./self_wake.sh once        Run a single monitor cycle (for cron/AGI)
# ==========================================================================

set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/../../.." && pwd)"
MONITOR_DIR="$APP_DIR/backend/agents/monitor"
VENV_DIR="$APP_DIR/venv"
PID_FILE="/tmp/polyedge-monitor.pid"
LOG_FILE="$APP_DIR/logs/monitor-daemon.log"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

ensure_venv() {
    if [ -f "$VENV_DIR/bin/activate" ]; then
        source "$VENV_DIR/bin/activate"
    elif [ -f "$VENV_DIR/bin/python3" ]; then
        export PATH="$VENV_DIR/bin:$PATH"
    else
        echo -e "${YELLOW}Warning: No venv found at $VENV_DIR${NC}"
    fi
}

start_daemon() {
    if [ -f "$PID_FILE" ]; then
        local pid
        pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            echo -e "${YELLOW}Monitor daemon already running (PID: $pid)${NC}"
            return 0
        fi
        echo -e "${YELLOW}Removing stale PID file${NC}"
        rm -f "$PID_FILE"
    fi

    ensure_venv

    mkdir -p "$(dirname "$LOG_FILE")"
    echo -e "${GREEN}Starting PolyEdge Monitor Daemon...${NC}"

    nohup python3 -c "
import asyncio, sys
sys.path.insert(0, '$APP_DIR')
from backend.agents.monitor.monitor_daemon import MonitorDaemon
d = MonitorDaemon(monitor_interval=900, report_interval=3600)
d.start()
asyncio.get_event_loop().run_forever()
" > "$LOG_FILE" 2>&1 &
    local pid=$!
    echo "$pid" > "$PID_FILE"
    echo -e "${GREEN}Monitor daemon started (PID: $pid)${NC}"
    echo "Log: $LOG_FILE"
}

stop_daemon() {
    if [ ! -f "$PID_FILE" ]; then
        echo -e "${YELLOW}No PID file found — daemon not running${NC}"
        return 0
    fi

    local pid
    pid=$(cat "$PID_FILE")
    echo -e "Stopping monitor daemon (PID: $pid)..."
    kill "$pid" 2>/dev/null || true
    rm -f "$PID_FILE"

    # Wait for it to die
    for _ in {1..10}; do
        if ! kill -0 "$pid" 2>/dev/null; then
            echo -e "${GREEN}Monitor daemon stopped${NC}"
            return 0
        fi
        sleep 0.5
    done

    # Force kill
    echo -e "${YELLOW}Force killing...${NC}"
    kill -9 "$pid" 2>/dev/null || true
    echo -e "${GREEN}Monitor daemon force-stopped${NC}"
}

check_status() {
    if [ -f "$PID_FILE" ]; then
        local pid
        pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            local uptime
            uptime=$(ps -o etime= -p "$pid" 2>/dev/null | xargs)
            echo -e "${GREEN}✅ Monitor daemon RUNNING (PID: $pid, Uptime: ${uptime:-?})${NC}"
            echo "Log: $LOG_FILE"
            return 0
        fi
        echo -e "${RED}Stale PID file found (PID: $pid not running)${NC}"
        rm -f "$PID_FILE"
    fi
    echo -e "${RED}❌ Monitor daemon NOT running${NC}"
    return 1
}

run_once() {
    ensure_venv
    echo -e "${GREEN}Running single monitor cycle...${NC}"
    python3 -c "
import asyncio, json, sys
sys.path.insert(0, '$APP_DIR')
from backend.agents.monitor.monitor_daemon import MonitorDaemon
d = MonitorDaemon(alert_on_startup=False)
report = asyncio.run(d.run_once())
print(json.dumps(report, indent=2, default=str))
"
}

# ── Main ──
ACTION="${1:-status}"

case "$ACTION" in
    start)
        start_daemon
        ;;
    stop)
        stop_daemon
        ;;
    restart)
        stop_daemon
        sleep 1
        start_daemon
        ;;
    status)
        check_status
        ;;
    once | run-once)
        run_once
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|once}"
        exit 1
        ;;
esac
