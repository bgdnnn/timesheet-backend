#!/bin/bash

# Configuration
BACKUP_DIR="/srv/backups/timesheet"
DB_NAME="timesheet"
DB_USER="timesheet"
DB_PASS="s/jlfC6REZpGohIMncEQd1FelVLyVaZT9m93i31ibzA="
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/${DB_NAME}_$TIMESTAMP.sql"
RETENTION_DAYS=30

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

# Perform backup
echo "Starting backup of $DB_NAME to $BACKUP_FILE..."
PGPASSWORD="$DB_PASS" pg_dump -h localhost -U "$DB_USER" "$DB_NAME" > "$BACKUP_FILE"

if [ $? -eq 0 ]; then
    echo "Backup successful! Compressing..."
    gzip "$BACKUP_FILE"
    echo "Compression complete: ${BACKUP_FILE}.gz"
    
    # Clean up old backups (Keep only 4 most recent)
    echo "Cleaning up old backups (keeping only 4 most recent)..."
    ls -t "$BACKUP_DIR"/*.sql.gz | tail -n +5 | xargs -r rm
    echo "Cleanup complete."
else
    echo "Backup failed!"
    exit 1
fi
