# Rollback Procedures

## Git Revert

```bash
# Find the problematic commit
git log --oneline -10

# Revert the specific commit (safe, creates new commit)
git revert <commit-sha>

# Force rollback to known-good state (destructive)
git reset --hard <known-good-sha>
```

## Database Migration Rollback

```bash
# Check current migration
alembic current

# Rollback one migration
alembic downgrade -1

# Rollback to specific migration
alembic downgrade <revision-id>
```

## PM2 Restart

```bash
# Graceful restart (10s grace for in-flight jobs)
pm2 gracefulReload all

# Hard restart
pm2 restart all

# Stop completely
pm2 stop all
```

## Redis Queue Flush

```bash
# If queue is corrupted, flush pending jobs
redis-cli FLUSHDB
# The system falls back to SQLite queue automatically
```

## Frontend Rollback

Vercel: Dashboard → Deployments → "..." → Promote to Production on previous deployment.
