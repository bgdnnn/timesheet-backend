# Google Drive Backup Setup Guide (OAuth 2.0 User Authentication)

This guide will help you complete the setup for sending automatic database and media backups to your personal Google Drive (utilizing your Google One 5TB quota).

---

## Prerequisites (Completed)
- [x] Installed Google Drive API client packages in Python venv.
- [x] Installed `google-auth-oauthlib` package.
- [x] Created [backup_gdrive.sh](file:///srv/timesheet-backend/scripts/backup_gdrive.sh) to support Google Drive uploads.
- [x] Created [upload_gdrive.py](file:///srv/timesheet-backend/scripts/upload_gdrive.py) handler.
- [x] Created [gdrive_auth.py](file:///srv/timesheet-backend/scripts/gdrive_auth.py) helper for headless authorization.

---

## Steps to Complete

### Step 1: Enable Google Drive API in Google Cloud Console
1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Select your project (e.g., `Timesheet Backups`) from the top-left dropdown.
3. In the search bar at the top, type `Google Drive API` and press Enter.
4. Click on **Google Drive API** from the results, and click the blue **Enable** button.

---

### Step 2: Configure the OAuth Consent Screen (Crucial)
Before creating your client credentials, you must configure the consent screen and add yourself as a test user:
1. Go to **APIs & Services > OAuth consent screen** in the left sidebar.
2. Select **External** as the User Type and click **Create**.
3. Fill in the required fields:
   - **App name:** `Timesheet Backup`
   - **User support email:** Select your email address.
   - **Developer contact information:** Enter your email address.
4. Click **Save and Continue**.
5. On the **Scopes** page, click **Save and Continue** (no extra scopes are required here).
6. On the **Test users** page (extremely important):
   - Click **+ Add Users**.
   - Enter your personal Google email address (the one with the 5TB storage).
   - Click **Save**.
7. Click **Save and Continue**, then review the summary and click **Back to Dashboard**.

---

### Step 3: Create OAuth Client ID Credentials
1. Navigate to **APIs & Services > Credentials** in the left sidebar.
2. Click **+ Create Credentials** at the top and select **OAuth client ID**.
3. Under **Application type**, select **Desktop app**.
4. Set the name to `Timesheet Backup CLI Client`.
5. Click **Create**.
6. Find your new credentials in the table under **OAuth 2.0 Client IDs**, and click the **Download JSON** button (downward arrow) on the right side of the row.
7. Save this JSON file on your server at:
   `/srv/timesheet-backend/gdrive-client-secrets.json`

---

### Step 4: Run the Headless Authorization Script
1. Run the authorization script on the server:
   ```bash
   /srv/timesheet-backend/.venv/bin/python3 /srv/timesheet-backend/scripts/gdrive_auth.py
   ```
2. Copy the long authorization URL printed in the terminal and open it in your browser.
3. Log in with your 5TB Google Account.
4. You will see a warning screen saying *“Google hasn’t verified this app”*. Click **Advanced** and then click **Go to Timesheet Backup (unsafe)** to proceed.
5. Click **Continue** to grant the requested Google Drive permissions.
6. Your browser will attempt to redirect to `http://localhost/?state=...&code=...` and display a *"Site cannot be reached"* page. **This is normal and expected.**
7. Copy the **entire URL** from your browser's address bar.
8. Paste it back into your server terminal where the script is waiting, and press **Enter**.
9. The script will exchange the authorization code for a token and save it to:
   `/srv/timesheet-backend/gdrive-token.json`

---

## Testing Your Setup
Once the `gdrive-token.json` file is saved and the Folder ID is configured in the script, you can test the backup immediately by running:
```bash
/bin/bash /srv/timesheet-backend/scripts/backup_gdrive.sh
```
Check if the compressed archive (.tar.gz) file containing your database and media files successfully appears in your Google Drive folder.
