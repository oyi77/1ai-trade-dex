#!/bin/bash
# Hourly backup and verification cron job wrapper

BACKUP_SCRIPT="${POLYEDGE_ROOT:-.}/scripts/backup_with_validation.sh"
VERIFY_SCRIPT="${POLYEDGE_ROOT:-.}/scripts/verify_latest_backup.sh"
LOG_FILE="${POLYEDGE_LOG_DIR:-./logs}/backup_cron.log"
ALERT_LOG="${POLYEDGE_LOG_DIR:-./logs}/backup_alerts.log"

mkdir -p "$(dirname "$LOG_FILE")"
mkdir -p "$(dirname "$ALERT_LOG")"

log_cron() {
    local level=$1
    local msg=$2
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] [$level] $msg" >> "$LOG_FILE"
}

send_alert() {
    local msg=$1
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] CRITICAL: $msg" >> "$ALERT_LOG"
    
    if command -v mail &> /dev/null; then
        echo "Backup verification failed: $msg" | mail -s "ALERT: Backup Verification Failed" root 2>/dev/null || true
    fi
}

log_cron "INFO" "Starting hourly backup and verification cycle"

if ! bash "$BACKUP_SCRIPT" >> "$LOG_FILE" 2>&1; then
    log_cron "ERROR" "Backup creation failed"
    send_alert "Backup creation failed - check logs at $LOG_FILE"
    exit 1
fi

log_cron "INFO" "Backup created successfully, running verification"

if ! bash "$VERIFY_SCRIPT" >> "$LOG_FILE" 2>&1; then
    log_cron "ERROR" "Backup verification failed"
    send_alert "Backup verification failed - latest backup may be corrupted"
    exit 1
fi

log_cron "INFO" "Hourly backup and verification cycle completed successfully"
exit 0
