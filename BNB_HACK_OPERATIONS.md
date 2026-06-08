# BNB HACK Bot — Operational Runbook

## Quick Start

### Start the bot in background
```bash
sudo systemctl start bnb-hack
sudo journalctl -u bnb-hack -f
```

### Stop the bot gracefully
```bash
sudo systemctl stop bnb-hack
```

### Monitor live status
```bash
curl http://localhost:8000/api/v1/hackathon/bnb-hack/status | jq .
```

### Check current signal
```bash
curl http://localhost:8000/api/v1/hackathon/bnb-hack/signal | jq .
```

### View recent trades
```bash
curl http://localhost:8000/api/v1/hackathon/bnb-hack/trades?limit=10 | jq .
```

---

## Deployment Checklist

- [ ] `.env` has `TWAK_WALLET_PASSWORD`, `TWAK_ACCESS_ID`, `TWAK_HMAC_SECRET` set
- [ ] systemd service enabled: `sudo systemctl enable bnb-hack`
- [ ] TWAK CLI installed: `which twak` (or run install script)
- [ ] Binance API accessible from network: `curl https://api.binance.com/api/v3/ticker/price?symbol=BNBUSDT`
- [ ] BSC RPC accessible (for TWAK swaps): network connectivity check
- [ ] Trade log directory exists: `mkdir -p logs/`
- [ ] Notification providers configured (optional): Telegram, Discord, Slack tokens in `.env`
- [ ] API server running: `curl http://localhost:8000/api/v1/hackathon/status`

---

## Troubleshooting

### Bot won't start
```bash
sudo systemctl status bnb-hack
sudo journalctl -u bnb-hack -n 50
```

### TWAK CLI not found
```bash
curl -fsSL https://agent-kit.trustwallet.com/install.sh | bash
```

### Binance API errors
- Check network connectivity: `ping api.binance.com`
- Check firewall: ensure port 443 is open
- Check rate limits: default is 1200 requests/minute

### Swap failing with "insufficient balance"
- Verify wallet has USDC: check via `curl http://localhost:8000/api/v1/hackathon/bnb-hack/status` → `balance`
- Verify network (BSC) is correctly configured in TWAK

### No trades happening
- Check signal: `curl http://localhost:8000/api/v1/hackathon/bnb-hack/signal`
- Check PnL/cooldowns: bot may be in cooldown after losses
- Verify SMA parameters in `.env` match backtested values

### Alerts not sending
- Check notification providers configured: `grep TELEGRAM_TOKEN .env`
- Verify provider is enabled in notification registry
- Check logs for provider errors: `journalctl -u bnb-hack | grep -i alert`

---

## Monitoring

### Key metrics to watch
```bash
# Total PnL
curl http://localhost:8000/api/v1/hackathon/bnb-hack/status | jq '.pnl.total_usd'

# Daily PnL
curl http://localhost:8000/api/v1/hackathon/bnb-hack/status | jq '.pnl.daily_usd'

# Win rate (from trade log)
tail -20 logs/bnb_hack_trades.csv | grep -c "^.*sell.*[1-9]" && echo "wins"
```

### Alerting setup

**Telegram:**
```bash
export TELEGRAM_BOT_TOKEN="<your_token>"
export TELEGRAM_CHAT_ID="<your_chat_id>"
```

**Discord:**
```bash
export DISCORD_WEBHOOK_URL="<your_webhook_url>"
```

**Slack:**
```bash
export SLACK_WEBHOOK_URL="<your_webhook_url>"
```

---

## Performance Tuning

### Adjust strategy parameters
Edit `.env`:
```bash
BNB_HACK_SMA_FAST=10         # Lower = more sensitive
BNB_HACK_SMA_SLOW=50         # Higher = smoother
BNB_HACK_CHECK_INTERVAL_SECONDS=3600  # Check every hour
```

### Adjust risk parameters
```bash
BNB_HACK_TAKE_PROFIT_PCT=3.0          # Close at +3% PnL
BNB_HACK_STOP_LOSS_PCT=3.0            # Close at -3% PnL
BNB_HACK_MAX_DAILY_LOSS_USD=5.0       # Halt at -$5 daily
BNB_HACK_COOLDOWN_MINUTES=120         # 2h cooldown after SL
BNB_HACK_MAX_CONSECUTIVE_LOSSES=3     # Halt after 3 losses
```

### Test changes in paper mode
```bash
python -m backend.bot.bnb_hack_bot --loop --paper
```

---

## Emergency Procedures

### Force stop if stuck
```bash
sudo systemctl kill -s 9 bnb-hack
```

### Emergency exit all positions
Manual swap via TWAK CLI:
```bash
twak swap <amount> BNB USDC --chain bsc --password $TWAK_WALLET_PASSWORD
```

### Rollback to previous bot version
```bash
git checkout HEAD~1 backend/bot/bnb_hack/
sudo systemctl restart bnb-hack
```

---

## Security Best Practices

1. **Never commit `.env` to git** — store secrets outside repo
2. **Use environment variables only** for sensitive data
3. **Limit wallet funds** — deploy with small capital first, scale gradually
4. **Enable alerts** — monitor for unusual activity
5. **Regular backups** — backup trade logs and state periodically
6. **Audit logs** — review `journalctl` regularly for errors

---

## Support & Escalation

**Issue Categories:**

| Issue | Action |
|-------|--------|
| Bot not starting | Check systemd logs, verify dependencies |
| API endpoint 500 | Check bot health, verify dependencies |
| No trades executing | Verify signal logic, check TWAK connectivity |
| Losses exceeding limit | Check risk parameters, consider strategy tuning |
| Notifications not sending | Verify provider tokens in `.env` |
| Network connectivity issues | Verify firewall, proxy settings, DNS resolution |

**Debug mode:**
```bash
RUST_LOG=debug python -m backend.bot.bnb_hack_bot --loop
```

---

**Last updated:** 2026-06-08
**Competition window:** June 22-28, 2026
