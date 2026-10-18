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
BACKUP_FILE="$BACKUP_DIR/${DB_NAME}_${TIMESTAMP}_gdrive.tar.gz"
# Local retention: the 4 most recent *_gdrive archives are kept (see cleanup below)

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

PYTHON_BIN="/srv/timesheet-backend/.venv/bin/python3"
ALERT_SCRIPT="/srv/timesheet-backend/scripts/send_backup_alert.py"
LOG_FILE="$BACKUP_DIR/backup.log"

send_alert() {
    local err_msg="$1"
    echo "Sending failure alert email..."
    if [ -f "$ALERT_SCRIPT" ]; then
        "$PYTHON_BIN" "$ALERT_SCRIPT" --job "Timesheet Google Drive Backup" --error "$err_msg" --log-file "$LOG_FILE"
    fi
}

# Perform backup
echo "Starting backup of database $DB_NAME and media files for Google Drive..."

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

        # Detect which credentials key file to use (prioritize user token over service account)
        USER_TOKEN="/srv/timesheet-backend/gdrive-token.json"
        GCS_KEY="/srv/timesheet-backend/gcs-credentials.json"
        GDRIVE_FOLDER_ID="1YhnB2w6gFYVB2oNG7uidtniDbX9A9FUD"
        
        if [ -f "$USER_TOKEN" ]; then
            GDRIVE_KEY="$USER_TOKEN"
        elif [ -f "$GCS_KEY" ]; then
            GDRIVE_KEY="$GCS_KEY"
        else
            GDRIVE_KEY=""
        fi
        
        # The off-site copy is encrypted; decrypt with: gpg -d file.tar.gz.gpg > file.tar.gz (BACKUP_PASSPHRASE)
        BACKUP_PASSPHRASE=$(grep "^BACKUP_PASSPHRASE=" "$ENV_FILE" | cut -d '=' -f2-)
        ENCRYPTED_FILE="$BACKUP_FILE.gpg"

        if [ -z "$BACKUP_PASSPHRASE" ]; then
            echo "ERROR: BACKUP_PASSPHRASE missing from .env. Refusing to upload an unencrypted backup."
            UPLOAD_STATUS=1
            send_alert "BACKUP_PASSPHRASE missing from .env; Google Drive upload skipped."
        elif ! gpg --batch --yes --pinentry-mode loopback --symmetric --cipher-algo AES256 \
                --passphrase-fd 3 -o "$ENCRYPTED_FILE" "$BACKUP_FILE" 3<<<"$BACKUP_PASSPHRASE"; then
            echo "ERROR: Failed to encrypt backup archive"
            UPLOAD_STATUS=1
            send_alert "GPG encryption of the backup archive failed; Google Drive upload skipped."
        elif [ -n "$GDRIVE_KEY" ]; then
            /srv/timesheet-backend/.venv/bin/python3 /srv/timesheet-backend/scripts/upload_gdrive.py "$ENCRYPTED_FILE" "$GDRIVE_FOLDER_ID" "$GDRIVE_KEY"
            UPLOAD_STATUS=$?
            if [ $UPLOAD_STATUS -ne 0 ]; then
                echo "ERROR: Google Drive upload failed with code $UPLOAD_STATUS"
                send_alert "Google Drive upload failed with exit code $UPLOAD_STATUS. See recent log excerpt below."
            fi
        else
            echo "Google Drive Credentials key not found (neither gdrive-token.json nor gcs-credentials.json exists). Skipping cloud upload."
            echo "Please see /srv/timesheet-backend/GDRIVE_BACKUP_GUIDE.md for setup instructions."
            UPLOAD_STATUS=1
            send_alert "Google Drive credentials key not found on server. Cloud upload skipped."
        fi
        rm -f "$ENCRYPTED_FILE"
        
        # Clean up old local Google Drive backup archives (Keep only 4 most recent)
        echo "Cleaning up old local gdrive archives (keeping only 4 most recent)..."
        ls -t "$BACKUP_DIR"/*_gdrive.tar.gz | tail -n +5 | xargs -r rm
        echo "Cleanup complete."
        
        exit $UPLOAD_STATUS
    else
        echo "Failed to create backup archive!"
        send_alert "Failed to create compressed tar.gz archive for Google Drive backup."
        exit 1
    fi
else
    rm -rf "$TEMP_DIR"
    echo "Database backup failed!"
    send_alert "PostgreSQL pg_dump failed while preparing database for Google Drive backup."
    exit 1
fi
