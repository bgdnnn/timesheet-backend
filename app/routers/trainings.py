from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pathlib import Path
import shutil
from datetime import date
from typing import List

from ..db import get_session
from ..auth import get_current_user
from ..models import Training
from ..schemas import TrainingOut, TrainingUpdate
from ..config import settings
from ..utils.users import user_slug_from_identity

router = APIRouter(prefix="/trainings", tags=["trainings"])

@router.post("/upload", response_model=TrainingOut)
async def upload_training(
    file: UploadFile = File(...),
    name: str = Form(...),
    expiry_date: date = Form(...),
    user = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    ext = file.filename.lower().split('.')[-1]
    if ext not in ["pdf", "png", "jpg", "jpeg"]:
        raise HTTPException(400, "Only PDF, PNG, JPG files are allowed")

    safe_user = user_slug_from_identity(user)
    media_root = Path(settings.MEDIA_ROOT)
    user_trainings_dir = media_root / safe_user / "trainings"
    user_trainings_dir.mkdir(parents=True, exist_ok=True)

    # Use a safe filename to avoid collisions
    import uuid
    safe_filename = f"{uuid.uuid4()}_{file.filename}"
    file_path = user_trainings_dir / safe_filename

    try:
        content = await file.read()
        with file_path.open("wb") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(500, f"Failed to save file: {e}")

    new_training = Training(
        created_by=user.email,
        name=name,
        expiry_date=expiry_date,
        file_path=str(file_path),
        filename=file.filename,
        mime_type=file.content_type
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

    return FileResponse(path, media_type=t.mime_type, content_disposition_type="inline")

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

    return FileResponse(path, media_type=t.mime_type, filename=t.filename, content_disposition_type="attachment")

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
    if payload.expiry_date is not None:
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
