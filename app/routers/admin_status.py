import os
import sys
import time
import shutil
import platform
import math
import datetime
from pathlib import Path
from typing import Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from ..db import get_session
from ..auth import get_admin_user
from ..models import User

router = APIRouter(prefix="/admin/status", tags=["admin-status"])

START_TIME = time.time()
BACKUP_DIR = "/srv/backups/timesheet"
MEDIA_DIR = "/srv/timesheet-backend/media"
PAYSLIP_CRON_LOG = "/home/bgdn/payslip_cron.log"
PAYSLIP_HISTORY_FILE = "/srv/timesheet-backend/.payslip_history.json"
GDRIVE_TOKEN_FILE = "/srv/timesheet-backend/gdrive-token.json"
GCS_KEY_FILE = "/srv/timesheet-backend/gcs-credentials.json"

def format_size(bytes_val: int | float | None) -> str:
    if not bytes_val or bytes_val <= 0:
        return "0 B"
    k = 1024
    sizes = ["B", "KB", "MB", "GB", "TB"]
    i = int(math.floor(math.log(bytes_val) / math.log(k)))
    i = min(max(i, 0), len(sizes) - 1)
    return f"{round(bytes_val / (k ** i), 2)} {sizes[i]}"

def format_duration(seconds: float | int) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    mins = int(seconds // 60)
    if mins < 60:
        return f"{mins}m {int(seconds % 60)}s"
    hours = int(mins // 60)
    rem_mins = int(mins % 60)
    if hours < 24:
        return f"{hours}h {rem_mins}m"
    days = int(hours // 24)
    rem_hours = int(hours % 24)
    return f"{days}d {rem_hours}h {rem_mins}m"

def get_next_cron_time(target_weekday: int, target_hour: int, target_minute: int) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    days_ahead = target_weekday - now.weekday()
    if days_ahead < 0 or (days_ahead == 0 and (now.hour > target_hour or (now.hour == target_hour and now.minute >= target_minute))):
        days_ahead += 7
    target_dt = (now + datetime.timedelta(days=days_ahead)).replace(
        hour=target_hour, minute=target_minute, second=0, microsecond=0
    )
    return target_dt.isoformat()

def get_system_metrics() -> Dict[str, Any]:
    mem: Dict[str, int] = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    k, v = parts[0].strip(), parts[1].strip().split()[0]
                    mem[k] = int(v) * 1024
    except Exception:
        pass

    total_ram = mem.get("MemTotal", 0)
    avail_ram = mem.get("MemAvailable", 0)
    used_ram = total_ram - avail_ram if total_ram else 0
    ram_pct = round((used_ram / total_ram) * 100, 1) if total_ram else 0

    root_disk = shutil.disk_usage("/")
    srv_disk = shutil.disk_usage("/srv") if os.path.exists("/srv") else None

    sys_uptime_sec = 0.0
    try:
        with open("/proc/uptime") as f:
            sys_uptime_sec = float(f.readline().split()[0])
    except Exception:
        pass

    load_avg = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
    cpu_count = os.cpu_count() or 1

    return {
        "os": f"{platform.system()} {platform.release()}",
        "hostname": platform.node(),
        "python_version": platform.python_version(),
        "uptime_seconds": int(sys_uptime_sec),
        "uptime_formatted": format_duration(sys_uptime_sec),
        "load_average": [round(x, 2) for x in load_avg],
        "cpu_cores": cpu_count,
        "ram": {
            "total_bytes": total_ram,
            "used_bytes": used_ram,
            "available_bytes": avail_ram,
            "used_percent": ram_pct,
            "formatted_total": format_size(total_ram),
            "formatted_used": format_size(used_ram),
            "formatted_available": format_size(avail_ram),
        },
        "disk_root": {
            "total_bytes": root_disk.total,
            "used_bytes": root_disk.used,
            "free_bytes": root_disk.free,
            "used_percent": round((root_disk.used / root_disk.total) * 100, 1),
            "formatted_total": format_size(root_disk.total),
            "formatted_used": format_size(root_disk.used),
            "formatted_free": format_size(root_disk.free),
        },
        "disk_srv": {
            "total_bytes": srv_disk.total,
            "used_bytes": srv_disk.used,
            "free_bytes": srv_disk.free,
            "used_percent": round((srv_disk.used / srv_disk.total) * 100, 1),
            "formatted_total": format_size(srv_disk.total),
            "formatted_used": format_size(srv_disk.used),
            "formatted_free": format_size(srv_disk.free),
        } if srv_disk else None,
    }

def get_folder_stats(dir_path: str) -> Dict[str, Any]:
    path = Path(dir_path)
    if not path.exists():
        return {"total_bytes": 0, "files_count": 0, "formatted_size": "0 B", "path": dir_path}
    
    total_bytes = 0
    files_count = 0
    try:
        for entry in path.rglob("*"):
            if entry.is_file():
                files_count += 1
                try:
                    total_bytes += entry.stat().st_size
                except Exception:
                    pass
    except Exception:
        pass

    return {
        "total_bytes": total_bytes,
        "files_count": files_count,
        "formatted_size": format_size(total_bytes),
        "path": dir_path,
    }

def get_backups_overview() -> Dict[str, Any]:
    path = Path(BACKUP_DIR)
    files = []
    if path.exists():
        for f in list(path.glob("*.tar.gz")) + list(path.glob("*.sql.gz")):
            try:
                stat = f.stat()
                is_full = "gdrive" in f.name or f.name.endswith(".tar.gz")
                files.append({
                    "filename": f.name,
                    "size_bytes": stat.st_size,
                    "size_formatted": format_size(stat.st_size),
                    "created_at": datetime.datetime.fromtimestamp(stat.st_mtime, tz=datetime.timezone.utc).isoformat(),
                    "type": "full_archive" if is_full else "db_dump",
                    "label": "Full Archive (DB + Media)" if is_full else "Database SQL Dump",
                })
            except Exception:
                pass

    files.sort(key=lambda x: x["created_at"], reverse=True)
    
    last_backup = files[0] if files else None
    last_db_backup = next((f for f in files if f["type"] == "db_dump"), None)
    last_full_backup = next((f for f in files if f["type"] == "full_archive"), None)
    total_backups_bytes = sum(f["size_bytes"] for f in files)

    # Check GDrive token & credentials
    has_user_token = os.path.exists(GDRIVE_TOKEN_FILE)
    has_gcs_key = os.path.exists(GCS_KEY_FILE)
    
    # Read backup log
    log_path = path / "backup.log"
    recent_logs: List[str] = []
    gdrive_status = "idle"
    gdrive_message = "Google Drive sync configured"
    
    if log_path.exists():
        try:
            with open(log_path, "r", errors="ignore") as lf:
                lines = lf.readlines()
                recent_logs = [line.rstrip() for line in lines[-35:]]
                
                # Find the status of the most recent Google Drive upload attempt
                for line in reversed(lines):
                    if "Google Drive Upload successful" in line or "File uploaded successfully" in line or "Upload complete" in line:
                        gdrive_status = "synced"
                        gdrive_message = "Synced successfully with Google Drive"
                        break
                    elif "invalid_grant" in line:
                        gdrive_status = "needs_reauth"
                        gdrive_message = "Google OAuth token expired / requires re-authentication"
                        break
                    elif "Google Drive Upload failed" in line:
                        gdrive_status = "error"
                        gdrive_message = "Last Google Drive cloud upload failed"
                        break
        except Exception:
            pass

    schedules = [
        {
            "id": "db_dump",
            "name": "Database SQL Dump",
            "cron": "30 23 * * 6",
            "description": "Weekly on Saturdays at 23:30 UTC",
            "next_run": get_next_cron_time(5, 23, 30),
            "script": "/srv/timesheet-backend/scripts/backup_db.sh",
        },
        {
            "id": "gdrive_sync",
            "name": "Google Drive Sync (DB + Media)",
            "cron": "45 23 * * 6",
            "description": "Weekly on Saturdays at 23:45 UTC",
            "next_run": get_next_cron_time(5, 23, 45),
            "script": "/srv/timesheet-backend/scripts/backup_gdrive.sh",
        },
        {
            "id": "payslip_fetcher",
            "name": "Payslip Auto-Downloader",
            "cron": "0 13,17 * * 4, 0 0 * * 5,6",
            "description": "Thursdays (13:00, 17:00), Fridays & Saturdays (00:00 UTC)",
            "script": "/srv/timesheet-backend/scripts/download_payslips.py",
        },
    ]

    return {
        "last_backup": last_backup,
        "last_db_backup": last_db_backup,
        "last_full_backup": last_full_backup,
        "total_backups_count": len(files),
        "total_backups_bytes": total_backups_bytes,
        "total_backups_formatted": format_size(total_backups_bytes),
        "files": files,
        "gdrive": {
            "has_user_token": has_user_token,
            "has_service_account": has_gcs_key,
            "status": gdrive_status,
            "message": gdrive_message,
        },
        "schedules": schedules,
        "recent_logs": recent_logs,
    }

def get_payslip_automation_info() -> Dict[str, Any]:
    last_run_time = None
    log_summary = "No recent run recorded"
    
    if os.path.exists(PAYSLIP_CRON_LOG):
        try:
            stat = os.stat(PAYSLIP_CRON_LOG)
            last_run_time = datetime.datetime.fromtimestamp(stat.st_mtime, tz=datetime.timezone.utc).isoformat()
            with open(PAYSLIP_CRON_LOG, "r", errors="ignore") as f:
                lines = f.readlines()
                if lines:
                    non_empty = [l.strip() for l in lines if l.strip()]
                    log_summary = non_empty[-1] if non_empty else "Completed"
        except Exception:
            pass

    return {
        "status": "active",
        "schedule": "Thursdays at 13:00, 17:00; Fridays & Saturdays at 00:00",
        "last_run": last_run_time,
        "last_summary": log_summary,
    }

@router.get("")
async def get_system_status(
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(get_admin_user)
) -> Dict[str, Any]:
    """
    Returns comprehensive system, database, storage, and backup telemetry.
    Requires admin privileges.
    """
    # 1. Backend process info
    backend_uptime = time.time() - START_TIME
    backend_info = {
        "status": "online",
        "uptime_seconds": int(backend_uptime),
        "uptime_formatted": format_duration(backend_uptime),
        "server_time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "python_version": platform.python_version(),
        "pid": os.getpid(),
        "environment": "production",
    }

    # 2. Database telemetry & table counts
    t0 = time.perf_counter()
    v = (await session.execute(text("SELECT version();"))).scalar()
    t1 = time.perf_counter()
    latency_ms = round((t1 - t0) * 1000, 2)

    db_size = (await session.execute(text("SELECT pg_database_size(current_database());"))).scalar()
    conn_count = (await session.execute(text("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database();"))).scalar()

    users_count = (await session.execute(text("SELECT count(*) FROM users;"))).scalar()
    admin_count = (await session.execute(text("SELECT count(*) FROM users WHERE role = 'admin';"))).scalar()
    entries_count = (await session.execute(text("SELECT count(*) FROM time_entries;"))).scalar()
    total_hours = (await session.execute(text("SELECT coalesce(sum(hours_worked), 0) FROM time_entries;"))).scalar()
    projects_count = (await session.execute(text("SELECT count(*) FROM projects;"))).scalar()
    active_projects = (await session.execute(text("SELECT count(*) FROM projects WHERE archived = false AND is_deleted = false;"))).scalar()
    payslips_count = (await session.execute(text("SELECT count(*) FROM payslip_files;"))).scalar()
    receipts_count = (await session.execute(text("SELECT count(*) FROM receipts;"))).scalar()
    expenses_count = (await session.execute(text("SELECT count(*) FROM expenses;"))).scalar()
    expenses_total = (await session.execute(text("SELECT coalesce(sum(total_amount), 0) FROM expenses;"))).scalar()
    trainings_count = (await session.execute(text("SELECT count(*) FROM trainings;"))).scalar()
    holidays_count = (await session.execute(text("SELECT count(*) FROM holidays;"))).scalar()
    hotels_count = (await session.execute(text("SELECT count(*) FROM hotels;"))).scalar()
    notes_count = (await session.execute(text("SELECT count(*) FROM notes;"))).scalar()

    database_info = {
        "status": "healthy",
        "version": v.split(",")[0] if v else "PostgreSQL",
        "latency_ms": latency_ms,
        "size_bytes": db_size,
        "size_formatted": format_size(db_size),
        "active_connections": conn_count,
        "database_name": "timesheet",
        "counts": {
            "users": users_count or 0,
            "admins": admin_count or 0,
            "time_entries": entries_count or 0,
            "total_hours": round(float(total_hours), 1) if total_hours else 0.0,
            "projects": projects_count or 0,
            "active_projects": active_projects or 0,
            "payslips": payslips_count or 0,
            "receipts": receipts_count or 0,
            "expenses": expenses_count or 0,
            "expenses_total": round(float(expenses_total), 2) if expenses_total else 0.0,
            "trainings": trainings_count or 0,
            "holidays": holidays_count or 0,
            "hotels": hotels_count or 0,
            "notes": notes_count or 0,
        }
    }

    # 3. Storage & Folders
    system_metrics = get_system_metrics()
    media_stats = get_folder_stats(MEDIA_DIR)
    backups_stats = get_folder_stats(BACKUP_DIR)
    
    storage_info = {
        "disk_root": system_metrics["disk_root"],
        "disk_srv": system_metrics["disk_srv"],
        "media": media_stats,
        "backups": backups_stats,
    }

    # 4. Backups overview & automation
    backups_overview = get_backups_overview()
    payslip_automation = get_payslip_automation_info()

    return {
        "backend": backend_info,
        "database": database_info,
        "system": system_metrics,
        "storage": storage_info,
        "backups": backups_overview,
        "payslip_automation": payslip_automation,
    }
