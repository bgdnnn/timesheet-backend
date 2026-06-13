import os
import subprocess
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from pathlib import Path
from datetime import datetime

from ..db import get_session
from ..auth import get_admin_user
from ..models import User

router = APIRouter(prefix="/admin/backups", tags=["admin-backups"])

BACKUP_DIR = "/srv/backups/timesheet"

@router.get("")
async def list_backups(admin: User = Depends(get_admin_user)):
    """
    List the 4 most recent backups.
    """
    path = Path(BACKUP_DIR)
    if not path.exists():
        return []
    
    files = []
    for f in path.glob("*.sql.gz"):
        stat = f.stat()
        files.append({
            "filename": f.name,
            "size_bytes": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat()
        })
    
    # Sort by mtime descending and take top 4
    files.sort(key=lambda x: x["created_at"], reverse=True)
    return files[:4]

@router.post("/trigger")
async def trigger_backup(admin: User = Depends(get_admin_user)):
    """
    Manually trigger a backup.
    """
    script_path = "/srv/timesheet-backend/scripts/backup_db.sh"
    try:
        # Run the script synchronously for admin feedback, or background if too slow
        result = subprocess.run([script_path], capture_output=True, text=True, check=True)
        return {"status": "success", "output": result.stdout}
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"Backup failed: {e.stderr}")

@router.post("/restore/{filename}")
async def restore_backup(filename: str, admin: User = Depends(get_admin_user)):
    """
    Restore the database from a backup file.
    DANGER: This is destructive.
    """
    # Security: check if filename is safe (no .. or /)
    if "/" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    backup_path = Path(BACKUP_DIR) / filename
    if not backup_path.exists():
        raise HTTPException(status_code=404, detail="Backup file not found")

    # DB Config (hardcoded to match backup script for now, should use env)
    DB_NAME = "timesheet"
    DB_USER = "timesheet"
    # Note: Using DB_PASS from env in real scenarios is better.
    # We'll use a temporary env for the subprocess.
    db_pass = "s/jlfC6REZpGohIMncEQd1FelVLyVaZT9m93i31ibzA="

    try:
        # 1. Uncompress to temporary file
        temp_sql = "/tmp/restore_temp.sql"
        with open(temp_sql, "wb") as f:
            subprocess.run(["gunzip", "-c", str(backup_path)], stdout=f, check=True)

        # 2. Restore using psql
        # -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;" to clear existing data
        # Then run the sql file.
        env = os.environ.copy()
        env["PGPASSWORD"] = db_pass
        
        # Clear existing data
        subprocess.run([
            "psql", "-h", "localhost", "-U", DB_USER, "-d", DB_NAME, 
            "-c", "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
        ], env=env, check=True)
        
        # Restore from file
        with open(temp_sql, "rb") as f:
            subprocess.run([
                "psql", "-h", "localhost", "-U", DB_USER, "-d", DB_NAME
            ], stdin=f, env=env, check=True)

        # 3. Cleanup
        os.remove(temp_sql)
        
        return {"status": "success", "message": f"Database restored from {filename}"}
    except subprocess.CalledProcessError as e:
        # Note: If it fails midway, the DB might be in a broken state (schema dropped)
        # In a production app, we'd want more robust recovery.
        raise HTTPException(status_code=500, detail=f"Restore failed: {e.stderr or e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
