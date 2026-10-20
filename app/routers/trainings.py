from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Response
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pathlib import Path
import shutil
import mimetypes
import re
from datetime import date
from typing import List, Optional

from ..db import get_session
from ..auth import get_current_user
from ..models import Training
from ..schemas import TrainingOut, TrainingUpdate
from ..config import settings
from ..utils.users import user_slug_from_identity
from ..utils.security import read_decrypted_file, write_encrypted_file
from ..utils.files import file_response

router = APIRouter(prefix="/trainings", tags=["trainings"])

# Stored type comes from the (whitelisted) extension, not from the client's Content-Type header
TRAINING_TYPES = {"pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}

@router.post("/upload", response_model=TrainingOut)
async def upload_training(
    file: UploadFile = File(...),
    name: str = Form(..., min_length=1, max_length=255),
    expiry_date: Optional[str] = Form(None),
    user = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    orig_filename = Path(file.filename or "training").name
    ext = orig_filename.lower().split('.')[-1]
    if ext not in TRAINING_TYPES:
        raise HTTPException(400, "Only PDF, PNG, JPG files are allowed")

    safe_user = user_slug_from_identity(user)
    media_root = Path(settings.MEDIA_ROOT)
    user_trainings_dir = media_root / safe_user / "trainings"
    user_trainings_dir.mkdir(parents=True, exist_ok=True)

    # Use a safe filename to avoid collisions
    import uuid
    clean_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', orig_filename)
    safe_filename = f"{uuid.uuid4()}_{clean_name}"
    file_path = user_trainings_dir / safe_filename

    try:
        content = await file.read()
        write_encrypted_file(file_path, content, user.email)
    except Exception as e:
        raise HTTPException(500, f"Failed to save file: {e}")

    parsed_expiry_date = None
    if expiry_date and expiry_date not in ["N/A", "null", "undefined", ""]:
        from datetime import datetime
        try:
            parsed_expiry_date = datetime.strptime(expiry_date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(400, "Invalid expiry date format. Use YYYY-MM-DD.")

    new_training = Training(
        created_by=user.email,
        name=name,
        expiry_date=parsed_expiry_date,
        file_path=str(file_path),
        filename=orig_filename,
        mime_type=TRAINING_TYPES[ext]
    )
    session.add(new_training)
    await session.commit()
    await session.refresh(new_training)

    return new_training

@router.get("", response_model=List[TrainingOut])
async def list_trainings(
    user = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    q = select(Training).where(Training.created_by == user.email).order_by(Training.expiry_date)
    result = await session.execute(q)
    return result.scalars().all()


@router.get("/{training_id}/file")
@router.get("/{training_id}/view")
async def view_training_file(
    training_id: int,
    user = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    q = select(Training).where(Training.id == training_id, Training.created_by == user.email)
    result = await session.execute(q)
    t = result.scalars().first()
    if not t:
        raise HTTPException(404, "Training not found")

    path = Path(t.file_path)
    if not path.exists():
        raise HTTPException(404, "File not found on disk")

    try:
        decrypted_bytes = read_decrypted_file(path, user.email)
        media_type = t.mime_type
        if not media_type or media_type == "application/octet-stream":
            guessed, _ = mimetypes.guess_type(t.filename)
            media_type = guessed or "application/octet-stream"
        if t.filename.lower().endswith(".pdf"):
            media_type = "application/pdf"

        return file_response(decrypted_bytes, t.filename, media_type, "inline")
    except Exception as e:
        raise HTTPException(500, f"Failed to decrypt file: {e}")

@router.get("/{training_id}/download")
async def download_training_file(
    training_id: int,
    user = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    q = select(Training).where(Training.id == training_id, Training.created_by == user.email)
    result = await session.execute(q)
    t = result.scalars().first()
    if not t:
        raise HTTPException(404, "Training not found")

    path = Path(t.file_path)
    if not path.exists():
        raise HTTPException(404, "File not found on disk")

    try:
        decrypted_bytes = read_decrypted_file(path, user.email)
        media_type = t.mime_type
        if not media_type or media_type == "application/octet-stream":
            guessed, _ = mimetypes.guess_type(t.filename)
            media_type = guessed or "application/octet-stream"
        if t.filename.lower().endswith(".pdf"):
            media_type = "application/pdf"

        return file_response(decrypted_bytes, t.filename, media_type, "attachment")
    except Exception as e:
        raise HTTPException(500, f"Failed to decrypt file: {e}")

@router.patch("/{training_id}", response_model=TrainingOut)
async def update_training(
    training_id: int,
    payload: TrainingUpdate,
    user = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    q = select(Training).where(Training.id == training_id, Training.created_by == user.email)
    result = await session.execute(q)
    t = result.scalars().first()
    if not t:
        raise HTTPException(404, "Training not found")

    if payload.name is not None:
        t.name = payload.name
    
    # Check if expiry_date was explicitly provided, even if it is None (null)
    exclude_unset = payload.model_dump(exclude_unset=True) if hasattr(payload, "model_dump") else payload.dict(exclude_unset=True)
    if "expiry_date" in exclude_unset:
        t.expiry_date = payload.expiry_date

    await session.commit()
    await session.refresh(t)
    return t

@router.delete("/{training_id}")
async def delete_training(
    training_id: int,
    user = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    q = select(Training).where(Training.id == training_id, Training.created_by == user.email)
    result = await session.execute(q)
    t = result.scalars().first()
    if not t:
        raise HTTPException(404, "Training not found")

    path = Path(t.file_path)
    if path.exists():
        path.unlink()

    await session.delete(t)
    await session.commit()

    return {"status": "ok"}
