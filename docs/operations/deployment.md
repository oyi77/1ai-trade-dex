# Deployment and Operations

This document covers deployment procedures, backup strategies, and rollback processes for the Polyedge trading bot.

## Deployment Options

### Docker Compose (Recommended for Development)

**Quick Start**:
```bash
docker-compose up -d
```

**Services**:
- `app` - Backend API server (port 8100)
- `redis` - Redis cache and pub/sub (port 6379)

**Configuration**:
- Edit `docker-compose.yml` for environment variables
- Mount `.env` file for secrets
- Persistent volumes for database and logs

**Logs**:
```bash
docker-compose logs -f app
docker-compose logs -f redis
```

**Stop**:
```bash
docker-compose down
```

### Railway (Backend Production)

**Configuration**: `railway.json`

**Deployment**:
```bash
# Install Railway CLI
npm install -g @railway/cli

# Login
railway login

# Deploy
railway up
```

**Environment Variables**:
Set in Railway dashboard:
- `DATABASE_URL`
- `REDIS_URL`
- `POLYMARKET_API_KEY`
- `KALSHI_API_KEY_ID`
- `KALSHI_PRIVATE_KEY_PATH`
- `ADMIN_PASSWORD`

**Health Checks**:
Railway automatically monitors `/health` endpoint.

### Vercel (Frontend Production)

**Configuration**: `vercel.json`

**Deployment**:
```bash
cd frontend
vercel --prod
```

**Environment Variables**:
Set in Vercel dashboard:
- `VITE_API_URL` - Backend API URL

**Build Settings**:
- Build command: `npm run build`
- Output directory: `dist`
- Install command: `npm install`

### PM2 (Production Process Manager)

**Configuration**: `ecosystem.config.js`

**Processes**:
- `api` - FastAPI server (port 8100)
- `worker` - Job queue worker
- `scheduler` - Background scheduler

**Start**:
```bash
pm2 start ecosystem.config.js
```

**Monitor**:
```bash
pm2 status
pm2 logs
pm2 monit
```

**Restart**:
```bash
pm2 restart all
pm2 restart api
```

**Stop**:
```bash
pm2 stop all
pm2 delete all
```

**Auto-Start on Boot**:
```bash
pm2 startup
pm2 save
```

## Database Backups

### Automated Hourly Backups

**Script**: `scripts/backup_with_validation.sh`

**Features**:
- Creates timestamped backups: `auto_YYYYMMDD_HHMMSS.db`
- Verifies backup integrity (file size, row count, table count)
- Automatic rotation (keeps last 7 days)
- Logs all operations to `logs/backup.log`

**Installation (Cron)**:
```bash
./scripts/backup-cron.sh
```

**Cron Entry**:
```
0 * * * * /home/openclaw/projects/polyedge/scripts/backup_with_validation.sh
```

**Installation (Systemd)**:
```bash
sudo cp scripts/polyedge-backup.service /etc/systemd/system/
sudo cp scripts/polyedge-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable polyedge-backup.timer
sudo systemctl start polyedge-backup.timer
```

**Verify**:
```bash
# Cron
crontab -l | grep backup_with_validation.sh

# Systemd
sudo systemctl status polyedge-backup.timer
```

**Monitor**:
```bash
tail -f logs/backup.log
ls -lh backups/ | head -10
```

### Backup Verification

**Script**: `scripts/verify_latest_backup.sh`

**Verification Checks**:
1. Backup file exists and has size > 0
2. Backup integrity (SQLite integrity_check)
3. Dry-run restore test
4. Schema verification (PRAGMA table_info)
5. Row count verification (all tables)
6. Data integrity (sample queries)

**Run Verification**:
```bash
./scripts/verify_latest_backup.sh
```

**Hourly Job with Verification**:
```bash
./scripts/hourly_backup_job.sh
```

**Alert System**:
- Alerts logged to `logs/backup_alerts.log`
- Mail notifications on verification failure
- Specific failure reasons for debugging

### Manual Backup

**Create Backup**:
```bash
./scripts/migration_safety.sh backup
```

**Backup Location**: `backups/polyedge-YYYYMMDD_HHMMSS.db`

**Verify Backup**:
```bash
./scripts/migration_safety.sh verify backups/polyedge-20260421_054528.db
```

## Rollback Procedures

### Database Rollback

**Script**: `scripts/migration_safety.sh rollback`

**Usage**:
```bash
# List available backups
ls -lh backups/

# Rollback to specific backup
./scripts/migration_safety.sh rollback backups/polyedge-20260421_054528.db
```

**Safety Features**:
- Creates pre-rollback safety backup
- Verifies restoration (confirms row counts match)
- Prevents data loss if rollback fails

**Rollback Process**:
1. Creates safety backup: `pre-rollback-TIMESTAMP.db`
2. Stops application (if running)
3. Replaces database with backup
4. Verifies restoration
5. Restarts application

### Application Rollback

**Docker Compose**:
```bash
# Stop current version
docker-compose down

# Checkout previous version
git checkout <previous-commit>

# Rebuild and start
docker-compose up -d --build
```

**PM2**:
```bash
# Stop current version
pm2 stop all

# Checkout previous version
git checkout <previous-commit>

# Restart
pm2 restart all
```

**Railway**:
```bash
# Rollback via Railway CLI
railway rollback

# Or via Railway dashboard
# Deployments → Select previous deployment → Redeploy
```

**Vercel**:
```bash
# Rollback via Vercel CLI
vercel rollback

# Or via Vercel dashboard
# Deployments → Select previous deployment → Promote to Production
```

## Migration Safety

### Pre-Migration Checks

**Script**: `scripts/migration_safety.sh pre-check`

**Checks**:
1. Active trades (warns if >0 open positions)
2. Disk space (requires 2x DB size available)
3. Database integrity (PRAGMA check)
4. Creates pre-migration backup
5. Verifies backup integrity

**Usage**:
```bash
# Run all pre-migration checks
./scripts/migration_safety.sh pre-check

# If checks pass, run migration
alembic upgrade head

# Verify post-migration
./scripts/migration_safety.sh verify
```

### Migration Workflow

**1. Pre-Migration**:
```bash
# Create backup
./scripts/migration_safety.sh backup

# Run pre-checks
./scripts/migration_safety.sh pre-check
```

**2. Run Migration**:
```bash
# Upgrade to latest
alembic upgrade head

# Or upgrade to specific revision
alembic upgrade <revision>
```

**3. Post-Migration**:
```bash
# Verify database
./scripts/migration_safety.sh verify

# Run tests
pytest

# Check application logs
tail -f logs/app.log
```

**4. Rollback (if needed)**:
```bash
# Rollback migration
alembic downgrade -1

# Or restore from backup
./scripts/migration_safety.sh rollback backups/polyedge-20260421_054528.db
```

## Graceful Shutdown

### Shutdown Process

The application implements a 10-step graceful shutdown sequence:

1. Stop accepting new requests
2. Wait for active requests (max 5s)
3. Close WebSocket connections (code 1001)
4. Shutdown Redis pub/sub
5. Shutdown connection limiter
6. Shutdown Polymarket WebSocket
7. Shutdown TaskManager (cancel all tasks)
8. Stop scheduler
9. Grace period (3s for in-flight jobs)
10. Close database connections

**Timeout**: 30s total (configurable)

**Trigger Shutdown**:
```bash
# Send SIGTERM
kill -TERM <pid>

# Or Ctrl+C (SIGINT)
# Or via PM2
pm2 stop api
```

**Verify Shutdown**:
- Check logs for "Graceful shutdown complete"
- Exit code 0 on success
- All steps logged with elapsed time

### Zero-Downtime Deployment

**Strategy**: Rolling deployment with health checks

**Process**:
1. Start new instance
2. Wait for `/health/ready` to return 200
3. Add new instance to load balancer
4. Remove old instance from load balancer
5. Send SIGTERM to old instance
6. Wait for graceful shutdown (max 30s)
7. Terminate old instance

**Load Balancer Configuration**:
```nginx
upstream backend {
    server backend1:8100 max_fails=3 fail_timeout=30s;
    server backend2:8100 max_fails=3 fail_timeout=30s;
}

server {
    location /health {
        proxy_pass http://backend;
        proxy_connect_timeout 5s;
        proxy_read_timeout 5s;
    }
}
```

## Environment Configuration

### Required Environment Variables

**Backend** (`.env`):
```bash
# Database
DATABASE_URL=sqlite:///./polyedge.db

# Redis (optional)
REDIS_URL=redis://localhost:6379/0

# Polymarket
POLYMARKET_API_KEY=your_api_key
POLYMARKET_PRIVATE_KEY=your_private_key
POLYMARKET_CHAIN_ID=137

# Kalshi
KALSHI_API_KEY_ID=your_key_id
KALSHI_PRIVATE_KEY_PATH=/path/to/private_key.pem

# Admin
ADMIN_PASSWORD=your_secure_password

# Trading
SHADOW_MODE=true
INITIAL_BANKROLL=10000.0

# Job Queue
JOB_WORKER_ENABLED=false
JOB_QUEUE_URL=sqlite:///./job_queue.db

# Monitoring
PROMETHEUS_ENABLED=true
```

**Frontend** (`.env`):
```bash
VITE_API_URL=http://localhost:8100
```

### Environment Validation

The application validates all required environment variables on startup:

**Implementation**: `backend/config.py`

**Validation**:
- Checks for required variables
- Validates format (URLs, paths, etc.)
- Logs warnings for missing optional variables
- Exits with error if required variables missing

**Test Validation**:
```bash
python -c "from backend.config import settings; print('Config valid')"
```

## Monitoring in Production

### Health Check Monitoring

**Uptime Monitoring**:
- Monitor `/health` endpoint every 30s
- Alert if 3 consecutive failures
- Use services like UptimeRobot, Pingdom, or StatusCake

**Readiness Monitoring**:
- Monitor `/health/ready` endpoint every 60s
- Alert if dependencies unavailable
- Use for deployment health checks

**Detailed Monitoring**:
- Monitor `/health/detailed` endpoint every 5 minutes
- Track circuit breaker states
- Track connection counts
- Track memory and disk usage

### Prometheus Monitoring

**Scrape Configuration**:
```yaml
scrape_configs:
  - job_name: 'polyedge'
    scrape_interval: 15s
    static_configs:
      - targets: ['backend:8100']
    metrics_path: '/metrics'
```

**Key Metrics to Monitor**:
- `http_request_duration_seconds` (p95, p99)
- `database_query_duration_seconds` (p95, p99)
- `websocket_connections_active`
- `circuit_breaker_state`
- `rate_limit_exceeded_total`

### Log Monitoring

**Application Logs**:
```bash
tail -f logs/app.log | jq .
```

**Backup Logs**:
```bash
tail -f logs/backup.log
```

**Alert Logs**:
```bash
tail -f logs/backup_alerts.log
```

**Centralized Logging**:
- Ship logs to ELK stack, Splunk, or Datadog
- Set up alerts for ERROR and CRITICAL level logs
- Monitor error rate trends

## Disaster Recovery

### Recovery Time Objective (RTO)

**Target**: < 15 minutes

**Process**:
1. Identify failure (via monitoring alerts)
2. Assess impact (check health endpoints)
3. Decide recovery strategy (rollback vs fix forward)
4. Execute recovery (restore backup or deploy fix)
5. Verify recovery (run health checks and tests)

### Recovery Point Objective (RPO)

**Target**: < 1 hour

**Strategy**:
- Hourly automated backups
- 7-day backup retention
- Backup verification every hour
- Off-site backup storage (optional)

### Disaster Recovery Plan

**1. Database Corruption**:
- Restore from latest verified backup
- Run integrity checks
- Verify data consistency
- Resume operations

**2. Application Failure**:
- Check logs for root cause
- Rollback to previous version if needed
- Fix issue and redeploy
- Monitor for recurrence

**3. Infrastructure Failure**:
- Failover to backup infrastructure
- Restore database from backup
- Update DNS/load balancer
- Verify all services operational

**4. Data Loss**:
- Restore from latest backup
- Sync with blockchain (for trades)
- Reconcile external trades
- Verify data integrity

## Deployment Checklist

### Pre-Deployment

- [ ] Run all tests (`pytest`)
- [ ] Create database backup
- [ ] Review recent changes (git log)
- [ ] Check environment variables
- [ ] Verify dependencies updated
- [ ] Run pre-migration checks (if schema changes)

### Deployment

- [ ] Deploy to staging first
- [ ] Run smoke tests on staging
- [ ] Deploy to production
- [ ] Monitor health endpoints
- [ ] Check application logs
- [ ] Verify key functionality

### Post-Deployment

- [ ] Monitor error rates
- [ ] Check performance metrics
- [ ] Verify backups running
- [ ] Update documentation
- [ ] Notify team of deployment
- [ ] Monitor for 24 hours

### Rollback Criteria

Rollback immediately if:
- Health checks failing
- Error rate >10/minute
- Database corruption detected
- Critical functionality broken
- Performance degradation >50%
