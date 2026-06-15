# Mailbox Auto-Upload Feature Documentation

This document outlines the architecture, database schema, background script behavior, and cron/login triggers for the **Mailbox Auto-Upload** feature implemented for weekly payslip and P60 PDF extraction.

---

## 1. Architecture Overview

```mermaid
graph TD
    User[Frontend UI: Automatic Upload Tab] -->|Saves settings| API[Backend: PUT /me]
    API -->|Encrypts passwords| DB[(PostgreSQL: users table)]
    API -->|Spawns synchronous test| Script[Downloader Script: download_payslips.py]
    Script -->|Tests connection & logs error| API
    
    Cron[System Cron: Saturday & Sunday 00:00] -->|Runs hourly checks| Script
    Login[Google OAuth Login] -->|If missing current payslip| Queue[FastAPI BackgroundTasks]
    Queue -->|Asynchronously runs| Script
    
    Script -->|Downloads & decrypts PDFs| Media[/srv/timesheet-backend/media]
    Script -->|Registers files| DB_Files[(PostgreSQL: payslip_files)]
```

---

## 2. Database Schema Modifications

The following columns were added to the `users` table:
* `is_auto_upload_enabled` (`BOOLEAN`, default `FALSE`)
* `auto_upload_provider` (`VARCHAR(32)`, either `"gmail"` or `"yahoo"`)
* `auto_upload_folder` (`VARCHAR(255)`, e.g., `"INBOX"`)
* `auto_upload_company` (`VARCHAR(255)`, filters email subjects, optional)
* `auto_upload_email` (`VARCHAR(255)`)
* `auto_upload_app_password` (`VARCHAR(512)`, encrypted)
* `pdf_password` (`VARCHAR(512)`, encrypted, optional)

### Migrations
Migrations run dynamically inside [app/db_utils.py](file:///srv/timesheet-backend/app/db_utils.py) on application startup using raw `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements.

---

## 3. Encryption Security

Credentials (`auto_upload_app_password` and `pdf_password`) are encrypted symmetrically using **Fernet (AES-128 in CBC mode)**.
* **Key Derivation**: The base 32-byte Fernet key is derived from the backend's `JWT_SECRET` by hashing it with SHA-256:
  `base64.urlsafe_b64encode(hashlib.sha256(JWT_SECRET.encode()).digest())`
* **Utility Module**: [app/utils/security.py](file:///srv/timesheet-backend/app/utils/security.py) handles `encrypt_value()` and `decrypt_value()`.

---

## 4. Backend Route Integration ([app/routers/me.py](file:///srv/timesheet-backend/app/routers/me.py))

* **`GET /me`**: Automatically decrypts saved credentials before sending them to the client (enabling fields to populate for editing).
* **`PUT /me`**: 
  1. Strips inputs and encrypts passwords using Fernet before saving.
  2. If `is_auto_upload_enabled = True`, triggers the downloader script synchronously in single-user verification mode:
     `download_payslips.py --email <user_email>`
  3. If the script exits with code `1`, intercepts the stderr output and raises an `HTTP 400 Bad Request` containing the specific connection/login/folder error. The database changes are preserved so the user can easily correct their fields.

---

## 5. Downloader Script ([download_payslips.py](file:///home/bgdn/download_payslips.py))

The script is located at `/home/bgdn/download_payslips.py` and uses `/srv/timesheet-backend/.venv/bin/python3`.

### Key Capabilities:
1. **Single User Mode (`--email <email>`)**: Verifies login/connection settings and imports files. Exits with code `1` and prints the exact error on failure.
2. **P60 Identification**: 
   * If the filename matches `"p60"` (case-insensitive), it sets `tax_week = 0`.
   * Stored on disk as `{tax_year}_0.pdf` and rendered in the frontend P60 tab.
3. **Resilient DB Registration**: If the target filename already exists on disk, it skips downloading/decrypting and registers the file directly in the `payslip_files` DB table.

---

## 6. Cron Schedule & Sunday Try-Again

The system cron (for user `bgdn`) runs the script at **00:00 every Saturday and Sunday**:
```cron
0 0 * * 0,6 /srv/timesheet-backend/.venv/bin/python3 /home/bgdn/download_payslips.py >> /home/bgdn/payslip_cron.log 2>&1
```

### Sunday Optimization:
When running in cron mode on Sunday (`weekday == 6`), the script executes a helper `is_payslip_missing(user_email)` to check if the database already has the payslip for the current tax week. If present, it skips mailbox scanning entirely to avoid redundant connections.

---

## 7. Login Trigger ([app/routers/auth_google.py](file:///srv/timesheet-backend/app/routers/auth_google.py))

When a user logs in via Google OAuth:
1. The backend checks if `is_auto_upload_enabled` is active.
2. It queries the `payslip_files` table to check if the payslip for the current tax week is missing.
3. If missing, it schedules a FastAPI background task to execute the single-user import script silently:
   `download_payslips.py --email <user_email>`
   This provides an automatic try-again check next time the user logs in.

---

## 8. Frontend Settings Tab ([src/pages/PayslipFiles.jsx](file:///srv/timesheet/src/pages/PayslipFiles.jsx))

* **Edit & Save**: Integrates a clean settings tab and dynamic readme setup guides for Gmail and Yahoo App Passwords.
* **Redirection on Success**: Switches to the main `payslips` tab and triggers `fetchFiles()` to display newly imported files upon a successful save.
* **Error Banner Handling**: Intercepts `HTTP 400` validation errors, extracts the detail description, and displays the warning in a toast alert, keeping the tab open for editing.
