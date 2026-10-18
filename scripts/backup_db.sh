#!/bin/bash

# Configuration
BACKUP_DIR="/srv/backups/timesheet"
DB_NAME="timesheet"
DB_USER="timesheet"

# Extract password from .env file
ENV_FILE="/srv/timesheet-backend/.env"
DB_URL=$(grep "^DATABASE_URL=" "$ENV_FILE" | cut -d '=' -f2-)
RAW_PASS=$(echo "$DB_URL" | sed -E 's/.*:\/\/.*:(.*)@.*/\1/')
DB_PASS=$(python3 -c "import urllib.parse, sys; print(urllib.parse.unquote(sys.argv[1]))" "$RAW_PASS")

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/${DB_NAME}_$TIMESTAMP.sql"
RETENTION_DAYS=30

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

PYTHON_BIN="/srv/timesheet-backend/.venv/bin/python3"
ALERT_SCRIPT="/srv/timesheet-backend/scripts/send_backup_alert.py"
LOG_FILE="$BACKUP_DIR/backup.log"

send_alert() {
    local err_msg="$1"
    echo "Sending failure alert email..."
    if [ -f "$ALERT_SCRIPT" ]; then
        "$PYTHON_BIN" "$ALERT_SCRIPT" --job "Timesheet Database Backup (Local)" --error "$err_msg" --log-file "$LOG_FILE"
    fi
}

# Perform backup
echo "Starting backup of $DB_NAME to $BACKUP_FILE..."
if PGPASSWORD="$DB_PASS" pg_dump -h localhost -U "$DB_USER" "$DB_NAME" > "$BACKUP_FILE"; then
    echo "Backup successful! Compressing..."
    if gzip -f "$BACKUP_FILE"; then
        echo "Compression complete: ${BACKUP_FILE}.gz"
        
        # Clean up old backups (Keep only 4 most recent)
        echo "Cleaning up old backups (keeping only 4 most recent)..."
        ls -t "$BACKUP_DIR"/*.sql.gz | tail -n +5 | xargs -r rm
        echo "Cleanup complete."
    else
        echo "Compression failed!"
        send_alert "Database dump succeeded, but gzip compression failed for $BACKUP_FILE."
        exit 1
    fi
else
    echo "Backup failed!"
    rm -f "$BACKUP_FILE"
    send_alert "PostgreSQL pg_dump failed while dumping database '$DB_NAME'."
    exit 1
fi
