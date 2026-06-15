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
BACKUP_FILE="$BACKUP_DIR/${DB_NAME}_$TIMESTAMP.tar.gz"
RETENTION_DAYS=30

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

# Perform backup
echo "Starting backup of database $DB_NAME and media files..."

# Create temporary directory
TEMP_DIR=$(mktemp -d)

# Dump database to db.sql in the temp dir
PGPASSWORD="$DB_PASS" pg_dump -h localhost -U "$DB_USER" "$DB_NAME" > "$TEMP_DIR/db.sql"
DB_DUMP_STATUS=$?

if [ $DB_DUMP_STATUS -eq 0 ]; then
    # Copy media folder if it exists
    if [ -d "/srv/timesheet-backend/media" ]; then
        cp -r "/srv/timesheet-backend/media" "$TEMP_DIR/media"
    fi

    # Create tar.gz archive of db.sql and media/
    tar -C "$TEMP_DIR" -czf "$BACKUP_FILE" db.sql media
    TAR_STATUS=$?
    
    # Cleanup temp dir
    rm -rf "$TEMP_DIR"

    if [ $TAR_STATUS -eq 0 ]; then
        echo "Backup successful! Created archive $BACKUP_FILE"

        # Upload to Google Drive if credentials key exists
        GDRIVE_KEY="/srv/timesheet-backend/gcs-credentials.json"
        GDRIVE_FOLDER_ID="your_google_drive_folder_id_here"
        
        if [ -f "$GDRIVE_KEY" ]; then
            /srv/timesheet-backend/.venv/bin/python3 /srv/timesheet-backend/scripts/upload_gdrive.py "$BACKUP_FILE" "$GDRIVE_FOLDER_ID" "$GDRIVE_KEY"
        else
            echo "Google Drive Credentials key not found at $GDRIVE_KEY. Skipping cloud upload."
        fi
        
        # Clean up old backups (Keep only 4 most recent)
        echo "Cleaning up old backups (keeping only 4 most recent)..."
        ls -t "$BACKUP_DIR"/*.tar.gz | tail -n +5 | xargs -r rm
        echo "Cleanup complete."
    else
        echo "Failed to create backup archive!"
        exit 1
    fi
else
    rm -rf "$TEMP_DIR"
    echo "Database backup failed!"
    exit 1
fi
