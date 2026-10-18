#!/usr/bin/env python3
"""
Send email notification when a backup job fails on home-clouds.com
Uses Resend API (configured via /srv/timesheet-backend/.env)
"""

import sys
import os
import argparse
import json
import urllib.request
import urllib.error
import socket
from datetime import datetime, timezone

def load_env_file(env_path):
    env_vars = {}
    if not os.path.exists(env_path):
        return env_vars
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                env_vars[k] = v
    except Exception as e:
        print(f"Warning: could not read {env_path}: {e}", file=sys.stderr)
    return env_vars

def get_config():
    # Priority: os.environ -> timesheet-backend .env -> financeflow-backend .env
    env = load_env_file("/srv/timesheet-backend/.env")
    if not env.get("RESEND_API_KEY"):
        fallback = load_env_file("/srv/financeflow-backend/.env")
        for k, v in fallback.items():
            if k not in env:
                env[k] = v

    api_key = os.environ.get("RESEND_API_KEY") or env.get("RESEND_API_KEY")
    from_email = os.environ.get("RESEND_FROM_EMAIL") or env.get("RESEND_FROM_EMAIL") or "Timesheet Backups <backups@contact.home-clouds.com>"
    to_email = os.environ.get("BACKUP_ALERT_EMAIL") or env.get("BACKUP_ALERT_EMAIL") or "tinauca.bogdan@gmail.com"

    return {
        "api_key": api_key,
        "from_email": from_email,
        "to_email": to_email,
    }

def get_log_tail(log_file, max_lines=35):
    if not log_file or not os.path.exists(log_file):
        return ""
    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            return "".join(lines[-max_lines:])
    except Exception as e:
        return f"[Failed to read log file: {e}]"

def send_failure_email(job_name, error_message, log_snippet=""):
    config = get_config()
    api_key = config["api_key"]
    if not api_key:
        print("ERROR: RESEND_API_KEY not found in environment or .env files.", file=sys.stderr)
        return False

    hostname = socket.gethostname() or "home-clouds.com"
    timestamp_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    subject = f"⚠️ Backup Failed: {job_name} on {hostname}"

    log_html = ""
    if log_snippet:
        # Escape HTML chars
        clean_snippet = log_snippet.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        log_html = f"""
        <div style="margin-top: 20px;">
          <h3 style="color: #475569; font-size: 14px; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px;">Recent Log Output:</h3>
          <pre style="background: #0f172a; color: #f8fafc; padding: 14px 16px; border-radius: 8px; font-size: 12px; font-family: monospace; overflow-x: auto; white-space: pre-wrap; word-break: break-all; border: 1px solid #1e293b;">{clean_snippet}</pre>
        </div>
        """

    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>{subject}</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f8fafc; margin: 0; padding: 24px 12px; color: #1e293b;">
  <div style="max-width: 580px; margin: 0 auto; background: #ffffff; border-radius: 16px; overflow: hidden; border: 1px solid #e2e8f0; box-shadow: 0 4px 12px rgba(0,0,0,0.05);">
    <div style="background: linear-gradient(135deg, #b91c1c 0%, #dc2626 100%); padding: 24px; color: #ffffff; text-align: left;">
      <h1 style="margin: 0; font-size: 20px; font-weight: 700; display: flex; align-items: center; gap: 8px;">
        ⚠️ Backup Execution Alert
      </h1>
      <p style="margin: 6px 0 0; font-size: 13px; color: #fecaca;">Automated notification from {hostname}</p>
    </div>

    <div style="padding: 24px;">
      <div style="background: #fef2f2; border-left: 4px solid #ef4444; padding: 14px 16px; border-radius: 6px; margin-bottom: 20px;">
        <div style="font-size: 14px; font-weight: 700; color: #991b1b; margin-bottom: 4px;">Job Failed: {job_name}</div>
        <div style="font-size: 13px; color: #b91c1c;">{error_message}</div>
      </div>

      <table style="width: 100%; border-collapse: collapse; font-size: 13px; margin-bottom: 16px;">
        <tr>
          <td style="padding: 6px 0; color: #64748b; width: 110px;">Server:</td>
          <td style="padding: 6px 0; font-weight: 600; color: #0f172a;">{hostname}</td>
        </tr>
        <tr>
          <td style="padding: 6px 0; color: #64748b;">Timestamp:</td>
          <td style="padding: 6px 0; font-weight: 600; color: #0f172a;">{timestamp_utc}</td>
        </tr>
      </table>

      {log_html}

      <div style="margin-top: 24px; padding-top: 16px; border-top: 1px solid #e2e8f0; font-size: 12px; color: #94a3b8; text-align: center;">
        Please inspect your server at <code>/srv/backups/timesheet/backup.log</code> to resolve this issue.
      </div>
    </div>
  </div>
</body>
</html>"""

    payload = {
        "from": config["from_email"],
        "to": [config["to_email"]],
        "subject": subject,
        "html": html_content
    }

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Timesheet-Backup-Alert/1.0"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
            print(f"Alert email sent successfully to {config['to_email']}. Resend ID: {resp_data.get('id')}")
            return True
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        print(f"Failed to send email (HTTP {e.code}): {body}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Failed to send email: {e}", file=sys.stderr)
        return False

def main():
    parser = argparse.ArgumentParser(description="Send backup failure alert email")
    parser.add_argument("--job", default="Timesheet Backup", help="Job name")
    parser.add_argument("--error", default="An error occurred during backup execution", help="Error description")
    parser.add_argument("--log-file", default="", help="Path to log file to extract tail snippet")
    parser.add_argument("--details", default="", help="Extra details or stderr to include in log snippet")
    parser.add_argument("--test", action="store_true", help="Send a test notification")
    args = parser.parse_args()

    snippet = ""
    if args.log_file:
        snippet = get_log_tail(args.log_file)
    if args.details:
        snippet = f"{args.details}\n\n{snippet}".strip()

    if args.test:
        print(f"Sending test alert to {get_config()['to_email']}...")
        success = send_failure_email("Test Backup Alert", "This is a verification test to ensure email alerts reach your inbox.", "Test log output line 1\nTest log output line 2\nSUCCESS")
        sys.exit(0 if success else 1)

    success = send_failure_email(args.job, args.error, snippet)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
