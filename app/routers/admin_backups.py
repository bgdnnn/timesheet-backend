import os
import gzip
import shutil
import subprocess
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..auth import get_admin_user
from ..models import User
from ..config import settings

router = APIRouter(prefix="/admin/backups", tags=["admin-backups"])

BACKUP_DIR = "/srv/backups/timesheet"
DB_USER = "timesheet"
DB_NAME = "timesheet"

def format_size(bytes_val: int | float | None) -> str:
    if not bytes_val or bytes_val <= 0:
        return "0 B"
    import math
    k = 1024
    sizes = ["B", "KB", "MB", "GB", "TB"]
    i = int(math.floor(math.log(bytes_val) / math.log(k)))
    i = min(max(i, 0), len(sizes) - 1)
    return f"{round(bytes_val / (k ** i), 2)} {sizes[i]}"

def get_safe_backup_path(filename: str) -> Path:
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename format")
    backup_path = Path(BACKUP_DIR) / filename
    if not backup_path.exists() or not backup_path.is_file():
        raise HTTPException(status_code=404, detail="Backup file not found")
    return backup_path

@router.get("")
async def list_backups(admin: User = Depends(get_admin_user)):
    """
    List all available database and archive backups.
    """
    path = Path(BACKUP_DIR)
    if not path.exists():
        return []
    
    files = []
    for f in list(path.glob("*.tar.gz")) + list(path.glob("*.sql.gz")):
        try:
            stat = f.stat()
            is_full = "gdrive" in f.name or f.name.endswith(".tar.gz")
            files.append({
                "filename": f.name,
                "size_bytes": stat.st_size,
                "size_formatted": format_size(stat.st_size),
                "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                "type": "full_archive" if is_full else "db_dump",
                "label": "Full Archive (DB + Media)" if is_full else "Database SQL Dump",
            })
        except Exception:
            pass
    
    # Sort by mtime descending
    files.sort(key=lambda x: x["created_at"], reverse=True)
    return files

@router.post("/trigger")
async def trigger_backup(
    backup_type: str = Query("db", description="'db' for fast SQL dump, 'full' for DB + media archive"),
    admin: User = Depends(get_admin_user)
):
    """
    Manually trigger a backup.
    """
    if backup_type == "full":
        script_path = "/srv/timesheet-backend/scripts/backup_gdrive.sh"
    else:
        script_path = "/srv/timesheet-backend/scripts/backup_db.sh"

    if not os.path.exists(script_path):
        raise HTTPException(status_code=500, detail=f"Backup script not found: {script_path}")

    try:
        result = subprocess.run([script_path], capture_output=True, text=True, check=True)
        return {
            "status": "success",
            "backup_type": backup_type,
            "message": "Backup completed successfully",
            "output": result.stdout
        }
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr or e.stdout or "Unknown error"
        raise HTTPException(status_code=500, detail=f"Backup failed: {error_msg}")

@router.get("/download/{filename}")
async def download_backup(filename: str, admin: User = Depends(get_admin_user)):
    """
    Download a backup file archive directly.
    """
    backup_path = get_safe_backup_path(filename)
    return FileResponse(
        path=str(backup_path),
        filename=filename,
        media_type="application/gzip"
    )

@router.get("/logs")
async def get_backup_logs(
    lines_count: int = Query(50, ge=1, le=500),
    admin: User = Depends(get_admin_user)
):
    """
    Retrieve the most recent backup execution logs.
    """
    log_path = Path(BACKUP_DIR) / "backup.log"
    if not log_path.exists():
        return {"logs": [], "message": "No backup log file found"}
    
    try:
        with open(log_path, "r", errors="ignore") as lf:
            lines = lf.readlines()
            return {"logs": [l.rstrip() for l in lines[-lines_count:]]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read backup logs: {str(e)}")

@router.post("/restore/{filename}")
async def restore_backup(filename: str, admin: User = Depends(get_admin_user)):
    """
    Restore the database (and media files if full archive) from a backup file.
    DANGER: This is destructive.
    """
    backup_path = get_safe_backup_path(filename)

    # Parse password from DATABASE_URL
    db_url = settings.DATABASE_URL
    try:
        # Example format: postgresql+asyncpg://timesheet:password@localhost:5432/timesheet
        db_pass = urllib.parse.unquote(db_url.split(":")[2].split("@")[0])
    except Exception:
        raise HTTPException(status_code=500, detail="Could not parse database credentials from configuration")

    temp_restore_dir = "/tmp/restore_temp_dir"
    try:
        if os.path.exists(temp_restore_dir):
            shutil.rmtree(temp_restore_dir)
        os.makedirs(temp_restore_dir)

        temp_sql = os.path.join(temp_restore_dir, "db.sql")

        is_tar = filename.endswith(".tar.gz")
        is_sql_gz = filename.endswith(".sql.gz")

        if is_tar:
            # 1. Extract tar.gz
            subprocess.run(["tar", "-xzf", str(backup_path), "-C", temp_restore_dir], check=True)
            if not os.path.exists(temp_sql):
                raise HTTPException(status_code=500, detail="db.sql not found inside backup archive")
        elif is_sql_gz:
            # Decompress .sql.gz directly
            with gzip.open(str(backup_path), "rb") as f_in:
                with open(temp_sql, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
        else:
            raise HTTPException(status_code=400, detail="Unsupported backup file format")

        # 2. Restore DB using psql
        env = os.environ.copy()
        env["PGPASSWORD"] = db_pass
        
        # Clear existing schema
        subprocess.run([
            "psql", "-h", "localhost", "-U", DB_USER, "-d", DB_NAME, 
            "-c", "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
        ], env=env, check=True)
        
        # Restore from SQL file
        with open(temp_sql, "rb") as f:
            subprocess.run([
                "psql", "-h", "localhost", "-U", DB_USER, "-d", DB_NAME
            ], stdin=f, env=env, check=True)

        # 3. Restore media files if present in archive
        media_restored = False
        backup_media_dir = os.path.join(temp_restore_dir, "media")
        if os.path.exists(backup_media_dir) and os.path.isdir(backup_media_dir):
            media_root = "/srv/timesheet-backend/media"
            if os.path.exists(media_root):
                shutil.rmtree(media_root)
            shutil.copytree(backup_media_dir, media_root)
            media_restored = True

        # 4. Cleanup temp dir
        shutil.rmtree(temp_restore_dir)
        
        detail_msg = f"Database {'and media files ' if media_restored else ''}successfully restored from {filename}"
        return {
            "status": "success",
            "message": detail_msg,
            "media_restored": media_restored
        }
    except subprocess.CalledProcessError as e:
        if os.path.exists(temp_restore_dir):
            shutil.rmtree(temp_restore_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Restore command failed: {e.stderr or e.stdout or e}")
    except Exception as e:
        if os.path.exists(temp_restore_dir):
            shutil.rmtree(temp_restore_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(e))
