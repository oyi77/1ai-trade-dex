#!/bin/bash
# Automated backup with validation, verification, and rotation

set -e

BACKUP_DIR="${POLYEDGE_BACKUP_DIR:-./backups}"
LOG_FILE="${POLYEDGE_LOG_DIR:-./logs}/backup.log"
VERIFICATION_LOG="${POLYEDGE_LOG_DIR:-./logs}/backup_verification.log"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/auto_$TIMESTAMP.db"
DB_FILE="${POLYEDGE_DB_FILE:-./tradingbot.db}"
RETENTION_DAYS=7
TEMP_RESTORE_DB="/tmp/backup_restore_test_$TIMESTAMP.db"

# Ensure directories exist
mkdir -p "$BACKUP_DIR"
mkdir -p "$(dirname "$LOG_FILE")"
mkdir -p "$(dirname "$VERIFICATION_LOG")"

# Logging function
log_message() {
    local level=$1
    local msg=$2
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] [$level] $msg" >> "$LOG_FILE"
}

# Verification logging function
log_verification() {
    local level=$1
    local msg=$2
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] [$level] $msg" >> "$VERIFICATION_LOG"
}

# Error handler
error_exit() {
    log_message "ERROR" "$1"
    # Clean up temp restore DB if it exists
    rm -f "$TEMP_RESTORE_DB"
    exit 1
}

verify_row_counts() {
    local original_db=$1
    local backup_db=$2
    local verification_passed=true
    
    log_verification "INFO" "Starting row count verification"
    
    local tables=$(sqlite3 "$original_db" "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;" 2>/dev/null)
    
    while IFS= read -r table; do
        [ -z "$table" ] && continue
        
        local orig_count=$(sqlite3 "$original_db" "SELECT COUNT(*) FROM \"$table\";" 2>/dev/null || echo "-1")
        local backup_count=$(sqlite3 "$backup_db" "SELECT COUNT(*) FROM \"$table\";" 2>/dev/null || echo "-1")
        
        if [ "$orig_count" = "-1" ] || [ "$backup_count" = "-1" ]; then
            log_verification "ERROR" "Failed to count rows in table: $table"
            verification_passed=false
        elif [ "$orig_count" != "$backup_count" ]; then
            log_verification "ERROR" "Row count mismatch in table '$table': original=$orig_count, backup=$backup_count"
            verification_passed=false
        else
            log_verification "INFO" "Table '$table': $orig_count rows (verified)"
        fi
    done <<< "$tables"
    
    if [ "$verification_passed" = true ]; then
        log_verification "INFO" "Row count verification passed"
        return 0
    else
        log_verification "ERROR" "Row count verification failed"
        return 1
    fi
}

verify_schemas() {
    local original_db=$1
    local backup_db=$2
    local verification_passed=true
    
    log_verification "INFO" "Starting schema verification"
    
    local tables=$(sqlite3 "$original_db" "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;" 2>/dev/null)
    
    while IFS= read -r table; do
        [ -z "$table" ] && continue
        
        local orig_schema=$(sqlite3 "$original_db" "PRAGMA table_info(\"$table\");" 2>/dev/null)
        local backup_schema=$(sqlite3 "$backup_db" "PRAGMA table_info(\"$table\");" 2>/dev/null)
        
        if [ "$orig_schema" != "$backup_schema" ]; then
            log_verification "ERROR" "Schema mismatch in table '$table'"
            verification_passed=false
        else
            log_verification "INFO" "Table '$table' schema verified"
        fi
    done <<< "$tables"
    
    if [ "$verification_passed" = true ]; then
        log_verification "INFO" "Schema verification passed"
        return 0
    else
        log_verification "ERROR" "Schema verification failed"
        return 1
    fi
}

dry_run_restore() {
    local backup_db=$1
    local temp_restore=$2
    
    log_verification "INFO" "Starting dry-run restore test"
    
    if ! cp "$backup_db" "$temp_restore" 2>/dev/null; then
        log_verification "ERROR" "Failed to copy backup for restore test"
        return 1
    fi
    
    if ! sqlite3 "$temp_restore" "PRAGMA integrity_check;" 2>/dev/null | grep -q "ok"; then
        log_verification "ERROR" "Restore test failed - database integrity check failed"
        rm -f "$temp_restore"
        return 1
    fi
    
    local table_count=$(sqlite3 "$temp_restore" "SELECT COUNT(*) FROM sqlite_master WHERE type='table';" 2>/dev/null || echo "0")
    if [ "$table_count" -eq 0 ]; then
        log_verification "ERROR" "Restore test failed - no tables found in restored database"
        rm -f "$temp_restore"
        return 1
    fi
    
    log_verification "INFO" "Dry-run restore test passed - $table_count tables accessible"
    rm -f "$temp_restore"
    return 0
}

run_backup_verification() {
    local original_db=$1
    local backup_db=$2
    local temp_restore=$3
    
    log_verification "INFO" "========== BACKUP VERIFICATION START =========="
    log_verification "INFO" "Original DB: $original_db"
    log_verification "INFO" "Backup DB: $backup_db"
    
    local all_passed=true
    
    if ! dry_run_restore "$backup_db" "$temp_restore"; then
        all_passed=false
    fi
    
    if ! verify_schemas "$original_db" "$backup_db"; then
        all_passed=false
    fi
    
    if ! verify_row_counts "$original_db" "$backup_db"; then
        all_passed=false
    fi
    
    if [ "$all_passed" = true ]; then
        log_verification "INFO" "========== BACKUP VERIFICATION PASSED =========="
        return 0
    else
        log_verification "ERROR" "========== BACKUP VERIFICATION FAILED =========="
        return 1
    fi
}

# Create backup
log_message "INFO" "Starting backup: $BACKUP_FILE"
if ! sqlite3 "$DB_FILE" ".backup '$BACKUP_FILE'" 2>/dev/null; then
    error_exit "Failed to create backup"
fi

# Verify backup file exists and has size > 0
if [ ! -f "$BACKUP_FILE" ]; then
    error_exit "Backup file not created: $BACKUP_FILE"
fi

BACKUP_SIZE=$(stat -f%z "$BACKUP_FILE" 2>/dev/null || stat -c%s "$BACKUP_FILE" 2>/dev/null)
if [ "$BACKUP_SIZE" -le 0 ]; then
    rm -f "$BACKUP_FILE"
    error_exit "Backup file is empty or corrupted (size: $BACKUP_SIZE bytes)"
fi

# Validate backup integrity
log_message "INFO" "Validating backup integrity"

# Check row counts match
ORIGINAL_COUNT=$(sqlite3 "$DB_FILE" "SELECT COUNT(*) FROM trades;" 2>/dev/null || echo "0")
BACKUP_COUNT=$(sqlite3 "$BACKUP_FILE" "SELECT COUNT(*) FROM trades;" 2>/dev/null || echo "-1")

if [ "$BACKUP_COUNT" = "-1" ]; then
    rm -f "$BACKUP_FILE"
    error_exit "Backup validation failed - cannot read backup database"
fi

if [ "$ORIGINAL_COUNT" != "$BACKUP_COUNT" ]; then
    rm -f "$BACKUP_FILE"
    error_exit "Backup validation failed - row count mismatch (original: $ORIGINAL_COUNT, backup: $BACKUP_COUNT)"
fi

# Check for table count consistency
ORIGINAL_TABLES=$(sqlite3 "$DB_FILE" "SELECT COUNT(*) FROM sqlite_master WHERE type='table';" 2>/dev/null || echo "0")
BACKUP_TABLES=$(sqlite3 "$BACKUP_FILE" "SELECT COUNT(*) FROM sqlite_master WHERE type='table';" 2>/dev/null || echo "0")

if [ "$ORIGINAL_TABLES" != "$BACKUP_TABLES" ]; then
    rm -f "$BACKUP_FILE"
    error_exit "Backup validation failed - table count mismatch (original: $ORIGINAL_TABLES, backup: $BACKUP_TABLES)"
fi

log_message "INFO" "Backup verified: $BACKUP_SIZE bytes, $BACKUP_COUNT trades, $BACKUP_TABLES tables"

# Run comprehensive backup verification
if ! run_backup_verification "$DB_FILE" "$BACKUP_FILE" "$TEMP_RESTORE_DB"; then
    rm -f "$BACKUP_FILE"
    error_exit "Comprehensive backup verification failed"
fi

CUTOFF_TIME=$(date -d "$RETENTION_DAYS days ago" +%s 2>/dev/null || date -v-${RETENTION_DAYS}d +%s 2>/dev/null)

cd "$BACKUP_DIR"
DELETED_COUNT=0
for backup_file in auto_*.db; do
    if [ -f "$backup_file" ]; then
        FILE_TIME=$(stat -f%m "$backup_file" 2>/dev/null || stat -c%Y "$backup_file" 2>/dev/null)
        if [ "$FILE_TIME" -lt "$CUTOFF_TIME" ]; then
            rm -f "$backup_file"
            DELETED_COUNT=$((DELETED_COUNT + 1))
            log_message "INFO" "Deleted old backup: $backup_file"
        fi
    fi
done

REMAINING=$(ls -1 auto_*.db 2>/dev/null | wc -l)
log_message "INFO" "Rotation complete: deleted $DELETED_COUNT old backups, $REMAINING backups remaining"

log_message "INFO" "Backup successful: $BACKUP_FILE (size: $BACKUP_SIZE bytes)"
log_message "INFO" "Backup verification logs: $VERIFICATION_LOG"
