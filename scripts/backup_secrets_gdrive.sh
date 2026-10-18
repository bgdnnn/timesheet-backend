#!/bin/bash
# Encrypts the timesheet secrets with a passphrase YOU choose (prompted, never stored)
# and uploads the encrypted bundle to the Google Drive backup folder.
# Run it in a real terminal (SSH): bash /srv/timesheet-backend/scripts/backup_secrets_gdrive.sh
# Re-run it whenever .env or the Google credentials change.
#
# Restore: download the .tar.gpg from Drive, then:
#   gpg -d timesheet-secrets_YYYYMMDD.tar.gpg | tar -x
set -euo pipefail

APP_DIR="/srv/timesheet-backend"
GDRIVE_FOLDER_ID="1YhnB2w6gFYVB2oNG7uidtniDbX9A9FUD"
OUT="$(mktemp -d)/timesheet-secrets_$(date +%Y%m%d).tar.gpg"
trap 'rm -rf "$(dirname "$OUT")"' EXIT

echo "Encrypting secrets. GPG will ask for a passphrase twice."
echo "Use a strong one you will REMEMBER. It is not stored anywhere; without it this backup is useless."
tar -C "$APP_DIR" -c .env gdrive-token.json gdrive-client-secrets.json gcs-credentials.json \
  | gpg --symmetric --cipher-algo AES256 --no-symkey-cache -o "$OUT"

echo "Checking the passphrase decrypts it (enter it once more)..."
gpg --no-symkey-cache -d "$OUT" | tar -t >/dev/null && echo "Decryption check OK."

"$APP_DIR/.venv/bin/python3" "$APP_DIR/scripts/upload_gdrive.py" "$OUT" "$GDRIVE_FOLDER_ID" "$APP_DIR/gdrive-token.json"
echo "Done. Encrypted secrets are in your Google Drive backup folder as $(basename "$OUT")."
