#!/bin/bash
# PolyEdge System Health Check
# Run this periodically via cron to monitor system health

set -e

echo "=== PolyEdge Health Check ==="
echo "Time: $(date)"

POLYEDGE_ROOT="${POLYEDGE_ROOT:-$(dirname "$0"/..)}"
cd "$POLYEDGE_ROOT"

# Check PM2 processes
echo ""
echo "--- PM2 Status ---"
pm2 list | grep -E "polyedge|status" || echo "No polyedge processes!"

# Check API health
echo ""
echo "--- API Health ---"
API_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8100/api/health 2>/dev/null || echo "000")
if [ "$API_STATUS" = "200" ]; then
    echo "API: OK"
else
    echo "API: FAIL (code: $API_STATUS)"
    echo "Attempting restart..."
    pm2 restart polyedge-api
fi

# Check frontend
echo ""
echo "--- Frontend Status ---"
FE_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:5174 2>/dev/null || echo "000")
if [ "$FE_STATUS" = "200" ]; then
    echo "Frontend: OK"
else
    echo "Frontend: FAIL (code: $FE_STATUS)"
    echo "Attempting restart..."
    pm2 restart polyedge-frontend
fi

# Check bot
echo ""
echo "--- Bot Status ---"
BOT_UPTIME=$(pm2 list | grep polyedge-bot | awk '{print $8}' || echo "0")
if [ "$BOT_UPTIME" != "0" ]; then
    echo "Bot: OK (uptime: ${BOT_UPTIME}m)"
else
    echo "Bot: DOWN"
    echo "Attempting restart..."
    pm2 restart polyedge-bot
fi

# Check open trades
echo ""
echo "--- Open Trades ---"
OPEN_COUNT=$(sqlite3 "${POLYEDGE_ROOT}/tradingbot.db" "SELECT COUNT(*) FROM trades WHERE settled=0;" 2>/dev/null || echo "0")
echo "Open trades: $OPEN_COUNT"

# Warn if too many open
if [ "$OPEN_COUNT" -gt 30 ]; then
    echo "WARNING: High number of open trades!"
fi

# Check recent settlement
echo ""
echo "--- Recent Settlements ---"
LAST_SETTLE=$(sqlite3 "${POLYEDGE_ROOT}/tradingbot.db" "SELECT datetime(MAX(timestamp)) FROM trades WHERE settled=1;" 2>/dev/null || echo "none")
echo "Last settlement: $LAST_SETTLE"

echo ""
echo "=== Health Check Complete ==="