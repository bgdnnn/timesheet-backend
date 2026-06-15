# Google Drive Backup Setup Guide

This guide will help you complete the setup for sending automatic database backups to your Google Drive folder (utilizing your Google One 5TB quota).

---

## Prerequisites (Completed)
- [x] Installed Google Drive API client packages in Python venv.
- [x] Configured [backup_db.sh](file:///srv/timesheet-backend/scripts/backup_db.sh) to support Google Drive uploads.
- [x] Created [upload_gdrive.py](file:///srv/timesheet-backend/scripts/upload_gdrive.py) handler.

---

## Steps to Complete

### Step 1: Create a Service Account Key
1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project (or select an existing one).
3. Go to **IAM & Admin > Service Accounts**.
4. Create a Service Account (e.g., name it `timesheet-backup-uploader`).
5. Open the Service Account, go to the **Keys** tab, click **Add Key > Create new key**, choose **JSON**, and download it.
6. Copy this JSON file to your server at:
   `/srv/timesheet-backend/gcs-credentials.json`

### Step 2: Share Google Drive Folder
1. Go to your consumer [Google Drive](https://drive.google.com/).
2. Create a new folder (e.g., `Database Backups`).
3. Open your downloaded `gcs-credentials.json` file and copy the `"client_email"` address (e.g., `timesheet-backup-uploader@xxxx.iam.gserviceaccount.com`).
4. Share the newly created folder with that email address as an **Editor**.

### Step 3: Configure Folder ID in Script
1. Go into the backup folder you created in Google Drive and look at the browser URL:
   `https://drive.google.com/drive/folders/YOUR_FOLDER_ID`
   Copy the `YOUR_FOLDER_ID` part (it's the long string of letters and numbers at the end).
2. Open [backup_db.sh](file:///srv/timesheet-backend/scripts/backup_db.sh#L34-L35).
3. Replace the placeholder value for `GDRIVE_FOLDER_ID` with your actual Google Drive folder ID:
   ```bash
   GDRIVE_FOLDER_ID="your_google_drive_folder_id_here"
   ```

---

## Testing Your Setup
Once the credentials file is saved and the Folder ID is configured, you can test the backup immediately by running:
```bash
/bin/bash /srv/timesheet-backend/scripts/backup_db.sh
```
Check if the compressed SQL backup (.sql.gz) file successfully appears in your Google Drive folder.
