# Timesheet Backend

FastAPI + PostgreSQL + Google OAuth backend for the Timesheet app.

## Dev
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # then fill values
uvicorn app.main:app --host 127.0.0.1 --port 4000

## Deploy
Run as a systemd service and reverse-proxy at https://api.timesheet.home-clouds.com
