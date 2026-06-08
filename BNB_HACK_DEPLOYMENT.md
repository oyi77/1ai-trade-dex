# BNB HACK Bot — Deployment Guide

## Pre-Deployment Requirements

### System Requirements
- OS: Linux (Ubuntu 20.04+ recommended)
- Python: 3.10+
- Storage: 1 GB minimum (for logs, data)
- Network: 10 Mbps+ stable connection
- Ports: 8000 (API), 443 (TWAK/Binance)

### Software Dependencies
```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install -y python3.10 python3.10-venv python3.10-dev git

# Install TWAK CLI
curl -fsSL https://agent-kit.trustwallet.com/install.sh | bash

# Verify installations
python3 --version  # Should be 3.10+
twak --version     # Should show TWAK version
```

### Environment Setup
```bash
# Clone repo
git clone <repo_url>
cd 1ai-poly-trader

# Create venv
python3 -m venv .venv
source .venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt

# Configure secrets
cp .env.example .env
# Edit .env with:
#   TWAK_WALLET_PASSWORD
#   TWAK_ACCESS_ID
#   TWAK_HMAC_SECRET
#   (optional) TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
```

---

## Installation Steps

### Step 1: Verify Core Bot
```bash
cd /path/to/1ai-poly-trader

# Test single cycle
python -m backend.bot.bnb_hack_bot

# Expected output:
# ════════════════════════════════════════════════════════════
# BNB HACK Bot — SMA(10/50) 1h TP:3% SL:3%
# Capital: $34 | Paper: False | Chain: bsc
# Competition: 2026-06-22T00:00:00Z → 2026-06-28T23:59:59Z
# ════════════════════════════════════════════════════════════
# [signal output]
```

### Step 2: Test Paper Mode (No Real Swaps)
```bash
# Run 10 cycles in paper mode
timeout 30 python -m backend.bot.bnb_hack_bot --loop --paper

# Expected: bot logs signal checks without executing swaps
```

### Step 3: Deploy systemd Service
```bash
# Copy service file
sudo cp scripts/bnb-hack.service /etc/systemd/system/

# Copy wrapper script
sudo cp scripts/run_bnb_hack.sh /usr/local/bin/
sudo chmod +x /usr/local/bin/run_bnb_hack.sh

# Reload systemd
sudo systemctl daemon-reload

# Test service
sudo systemctl start bnb-hack
sleep 5
sudo systemctl status bnb-hack

# Expected: "Active: active (running)"
```

### Step 4: Enable Auto-Start
```bash
sudo systemctl enable bnb-hack

# Verify it persists across reboot:
# sudo reboot
# sudo systemctl status bnb-hack  # Should be running
```

### Step 5: Configure Monitoring
```bash
# Set up log rotation (optional)
sudo tee /etc/logrotate.d/bnb-hack > /dev/null <<EOF
/path/to/logs/bnb_hack_trades.csv {
    daily
    rotate 30
    compress
    delaycompress
}
EOF

# Set up notifications (optional)
# Add to .env:
# TELEGRAM_BOT_TOKEN=<your_token>
# TELEGRAM_CHAT_ID=<your_chat_id>
```

---

## Verification Checklist

Run the deployment verification script:

```bash
#!/bin/bash
set -e

echo "=== BNB HACK Deployment Verification ==="

echo "1. Check Python and dependencies..."
python3 -c "import asyncio, httpx, loguru; print('  ✓ Python deps OK')"

echo "2. Check TWAK CLI..."
twak --version > /dev/null && echo "  ✓ TWAK CLI found"

echo "3. Test Binance API..."
curl -s https://api.binance.com/api/v3/ticker/price?symbol=BNBUSDT | jq .price > /dev/null
echo "  ✓ Binance API accessible"

echo "4. Check systemd service..."
sudo systemctl is-active bnb-hack > /dev/null && echo "  ✓ Service running" || echo "  ✗ Service not running"

echo "5. Check API endpoint..."
curl -s http://localhost:8000/api/v1/hackathon/status | jq .status > /dev/null && echo "  ✓ API responding" || echo "  ⚠ API not responding"

echo "6. Test signal generation..."
python -m backend.bot.bnb_hack_bot 2>&1 | grep -q "Signal" && echo "  ✓ Signal generation working"

echo "=== All checks passed ==="
```

---

## Day-1 Production Checklist (June 22, 2026)

**Morning (00:00 UTC):**
- [ ] Service is running: `sudo systemctl status bnb-hack`
- [ ] Latest code deployed: `git log --oneline -1`
- [ ] `.env` secrets are set and correct
- [ ] Notifications are configured and tested
- [ ] API endpoints responding: `curl http://localhost:8000/api/v1/hackathon/status`

**Throughout competition (June 22-28):**
- [ ] Monitor daily PnL: `curl http://localhost:8000/api/v1/hackathon/bnb-hack/status | jq '.pnl.daily_usd'`
- [ ] Check trade history: `tail -5 logs/bnb_hack_trades.csv`
- [ ] Review error logs: `sudo journalctl -u bnb-hack --since "1 hour ago" | grep -i error`
- [ ] Verify wallet balance: `curl http://localhost:8000/api/v1/hackathon/bnb-hack/status | jq '.balance'`

**End of competition (June 28, 23:59 UTC):**
- [ ] Stop bot gracefully: `sudo systemctl stop bnb-hack`
- [ ] Archive trade logs: `cp logs/bnb_hack_trades.csv logs/bnb_hack_trades_final.csv`
- [ ] Collect final metrics for submission

---

## Troubleshooting Deployment Issues

### Issue: "twak: command not found"
```bash
# Install TWAK CLI
curl -fsSL https://agent-kit.trustwallet.com/install.sh | bash
source ~/.bashrc  # Reload shell
twak --version
```

### Issue: "ModuleNotFoundError: No module named 'backend.bot.bnb_hack'"
```bash
# Ensure you're in the repo root
cd /path/to/1ai-poly-trader

# Reinstall dependencies
pip install -r requirements.txt

# Test import
python -c "from backend.bot.bnb_hack import BnbHackBot; print('OK')"
```

### Issue: "Address already in use" (port 8000)
```bash
# Find process using port 8000
sudo lsof -i :8000

# Kill it and restart
sudo systemctl restart bnb-hack
```

### Issue: "Connection refused" (Binance API)
```bash
# Test connectivity
curl -v https://api.binance.com/api/v3/ticker/price?symbol=BNBUSDT

# If it fails, check:
# - Network connectivity: ping 8.8.8.8
# - DNS: nslookup api.binance.com
# - Firewall: check corporate/ISP firewall rules
```

---

## Rollback Procedures

### If bot crashes or behaves unexpectedly
```bash
# Stop immediately
sudo systemctl stop bnb-hack

# Revert to last known good version
git checkout HEAD~1 backend/bot/bnb_hack/

# Restart
sudo systemctl start bnb-hack

# Verify
sudo journalctl -u bnb-hack -n 10
```

### If API is broken
```bash
# Restart API server
sudo systemctl restart polyedge-api
# or
pkill -f "python.*api"
cd /path/to/1ai-poly-trader && python run.py &
```

---

## Post-Deployment Monitoring

### Key Metrics Dashboard (manual)
```bash
#!/bin/bash
while true; do
  clear
  echo "=== BNB HACK Bot Status ==="
  echo "Time: $(date)"
  echo ""
  echo "PnL:"
  curl -s http://localhost:8000/api/v1/hackathon/bnb-hack/status 2>/dev/null | jq '.pnl' || echo "API unavailable"
  echo ""
  echo "Position:"
  curl -s http://localhost:8000/api/v1/hackathon/bnb-hack/status 2>/dev/null | jq '.position' || echo "API unavailable"
  echo ""
  sleep 60
done
```

### Logs
```bash
# Follow live logs
sudo journalctl -u bnb-hack -f

# Filter errors
sudo journalctl -u bnb-hack | grep -i error

# Count trades by day
grep "^[^#]" logs/bnb_hack_trades.csv | cut -d',' -f1 | cut -dT -f1 | uniq -c
```

---

**Deployment Completed:** [TIMESTAMP]
**Deployed By:** [NAME]
**Version:** [GIT COMMIT]
