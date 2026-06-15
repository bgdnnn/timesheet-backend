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
from ..config import settings

router = APIRouter(prefix="/admin/backups", tags=["admin-backups"])

BACKUP_DIR = "/srv/backups/timesheet"
DB_USER = "timesheet"
DB_NAME = "timesheet"

@router.get("")
async def list_backups(admin: User = Depends(get_admin_user)):
    """
    List the 4 most recent backups.
    """
    path = Path(BACKUP_DIR)
    if not path.exists():
        return []
    
    files = []
    for f in path.glob("*.tar.gz"):
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
    Restore the database and media files from a backup file.
    DANGER: This is destructive.
    """
    # Security: check if filename is safe (no .. or /)
    if "/" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    backup_path = Path(BACKUP_DIR) / filename
    if not backup_path.exists():
        raise HTTPException(status_code=404, detail="Backup file not found")

    # Parse password from DATABASE_URL
    db_url = settings.DATABASE_URL
    import urllib.parse
    try:
        # Example format: postgresql+asyncpg://timesheet:password@localhost:5432/timesheet
        db_pass = urllib.parse.unquote(db_url.split(":")[2].split("@")[0])
    except Exception:
        raise HTTPException(status_code=500, detail="Could not parse database credentials")

    try:
        import shutil
        # 1. Create temporary directory for extraction
        temp_restore_dir = "/tmp/restore_temp_dir"
        if os.path.exists(temp_restore_dir):
            shutil.rmtree(temp_restore_dir)
        os.makedirs(temp_restore_dir)

        # Extract tar.gz
        subprocess.run(["tar", "-xzf", str(backup_path), "-C", temp_restore_dir], check=True)

        temp_sql = os.path.join(temp_restore_dir, "db.sql")
        if not os.path.exists(temp_sql):
            raise HTTPException(status_code=500, detail="db.sql not found in backup archive")

        # 2. Restore DB using psql
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

        # 3. Restore media files
        backup_media_dir = os.path.join(temp_restore_dir, "media")
        if os.path.exists(backup_media_dir):
            media_root = "/srv/timesheet-backend/media"
            if os.path.exists(media_root):
                shutil.rmtree(media_root)
            shutil.copytree(backup_media_dir, media_root)

        # 4. Cleanup
        shutil.rmtree(temp_restore_dir)
        
        return {"status": "success", "message": f"Database and media restored from {filename}"}
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"Restore failed: {e.stderr or e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
