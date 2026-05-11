#!/bin/bash
# Cron job installer for hourly database backups
# Run this script once to set up the hourly backup schedule

SCRIPT_PATH="${POLYEDGE_ROOT:-.}/scripts/backup_with_validation.sh"
CRON_SCHEDULE="0 * * * * $SCRIPT_PATH"

# Check if script exists and is executable
if [ ! -x "$SCRIPT_PATH" ]; then
    echo "ERROR: Backup script not found or not executable: $SCRIPT_PATH"
    exit 1
fi

# Add cron job if not already present
if crontab -l 2>/dev/null | grep -q "backup_with_validation.sh"; then
    echo "Cron job already installed"
else
    (crontab -l 2>/dev/null; echo "$CRON_SCHEDULE") | crontab -
    echo "Cron job installed: $CRON_SCHEDULE"
fi

# Verify installation
echo "Current cron jobs:"
crontab -l | grep backup_with_validation.sh || echo "No backup cron job found"
