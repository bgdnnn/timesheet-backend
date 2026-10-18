import mimetypes
import re
from urllib.parse import quote
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, Response
from fastapi.responses import FileResponse
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..config import settings
from ..db import get_session
from ..models import ConstructionDetail
from ..schemas import ConstructionDetailOut, ConstructionDetailUpdate
from ..utils.users import user_slug_from_identity
from ..utils.security import read_decrypted_file, write_encrypted_file

router = APIRouter(prefix="/construction-details", tags=["construction-details"])


@router.post("/upload", response_model=ConstructionDetailOut)
async def upload_construction_detail(
    file: UploadFile = File(...),
    name: str = Form(...),
    manufacturer: str = Form(...),
    details: Optional[str] = Form(None),
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    trimmed_name = name.strip()
    trimmed_manufacturer = manufacturer.strip()
    if not trimmed_name:
        raise HTTPException(400, "Name cannot be empty")
    if not trimmed_manufacturer:
        raise HTTPException(400, "Manufacturer cannot be empty")

    safe_user = user_slug_from_identity(user)
    media_root = Path(settings.MEDIA_ROOT)
    user_details_dir = media_root / safe_user / "construction_details"
    user_details_dir.mkdir(parents=True, exist_ok=True)

    # Sanitize original filename
    orig_filename = file.filename or "detail"
    clean_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', orig_filename)
    safe_filename = f"{uuid.uuid4()}_{clean_name}"
    file_path = user_details_dir / safe_filename

    try:
        content = await file.read()
        write_encrypted_file(file_path, content, user.email)
    except Exception as e:
        raise HTTPException(500, f"Failed to save file: {e}")

    # Determine mime type
    mime_type = file.content_type
    if not mime_type or mime_type == "application/octet-stream":
        guessed_type, _ = mimetypes.guess_type(orig_filename)
        mime_type = guessed_type or "application/octet-stream"

    size_bytes = len(content)

    details_val = details.strip() if isinstance(details, str) and details.strip() else None

    new_detail = ConstructionDetail(
        created_by=user.email,
        name=trimmed_name,
        manufacturer=trimmed_manufacturer,
        details=details_val,
        file_path=str(file_path),
        filename=orig_filename,
        mime_type=mime_type,
        size_bytes=size_bytes,
    )
    session.add(new_detail)
    await session.commit()
    await session.refresh(new_detail)

    return new_detail


@router.get("", response_model=List[ConstructionDetailOut])
async def list_construction_details(
    manufacturer: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    sort_by: Optional[str] = Query("default"),
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    q = select(ConstructionDetail).where(ConstructionDetail.created_by == user.email)

    if isinstance(manufacturer, str) and manufacturer.strip() and manufacturer.lower() != "all":
        q = q.where(func.lower(ConstructionDetail.manufacturer) == manufacturer.strip().lower())

    if isinstance(search, str) and search.strip():
        term = f"%{search.strip().lower()}%"
        q = q.where(
            (func.lower(ConstructionDetail.name).like(term))
            | (func.lower(ConstructionDetail.manufacturer).like(term))
            | (func.lower(ConstructionDetail.details).like(term))
            | (func.lower(ConstructionDetail.filename).like(term))
        )

    sort_order = sort_by if isinstance(sort_by, str) else "default"
    if sort_order == "name_asc":
        q = q.order_by(ConstructionDetail.name.asc())
    elif sort_order == "name_desc":
        q = q.order_by(ConstructionDetail.name.desc())
    elif sort_order == "manufacturer_desc":
        q = q.order_by(ConstructionDetail.manufacturer.desc(), ConstructionDetail.name.asc())
    elif sort_order == "date_desc":
        q = q.order_by(ConstructionDetail.created_at.desc())
    elif sort_order == "date_asc":
        q = q.order_by(ConstructionDetail.created_at.asc())
    else:  # default: sort by manufacturer then details/name
        q = q.order_by(ConstructionDetail.manufacturer.asc(), ConstructionDetail.name.asc())

    result = await session.execute(q)
    return result.scalars().all()


@router.get("/manufacturers", response_model=List[str])
async def list_manufacturers(
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    q = (
        select(ConstructionDetail.manufacturer)
        .where(ConstructionDetail.created_by == user.email)
        .distinct()
        .order_by(ConstructionDetail.manufacturer.asc())
    )
    result = await session.execute(q)
    manufacturers = [m for (m,) in result.tuples() if m]
    return manufacturers


def make_content_disposition(disposition_type: str, filename: str) -> str:
    safe_ascii = re.sub(r'[\",;\\/\x00-\x1f\x7f-\xff]', '_', filename)
    encoded = quote(filename)
    return f"{disposition_type}; filename=\"{safe_ascii}\"; filename*=utf-8''{encoded}"

@router.get("/{detail_id}/view")
@router.get("/{detail_id}/file")
async def view_construction_detail_file(
    detail_id: int,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    q = select(ConstructionDetail).where(
        ConstructionDetail.id == detail_id,
        ConstructionDetail.created_by == user.email,
    )
    result = await session.execute(q)
    detail = result.scalars().first()
    if not detail:
        raise HTTPException(404, "Construction detail not found")

    path = Path(detail.file_path)
    if not path.exists():
        raise HTTPException(404, "File not found on disk")

    try:
        decrypted_bytes = read_decrypted_file(path, user.email)
        media_type = detail.mime_type
        if not media_type or media_type == "application/octet-stream":
            guessed, _ = mimetypes.guess_type(detail.filename)
            media_type = guessed or "application/octet-stream"
        if detail.filename.lower().endswith(".pdf"):
            media_type = "application/pdf"

        return Response(
            content=decrypted_bytes,
            media_type=media_type,
            headers={
                "Content-Disposition": make_content_disposition("inline", detail.filename),
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    except Exception as e:
        raise HTTPException(500, f"Failed to decrypt file: {e}")


@router.get("/{detail_id}/download")
async def download_construction_detail_file(
    detail_id: int,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    q = select(ConstructionDetail).where(
        ConstructionDetail.id == detail_id,
        ConstructionDetail.created_by == user.email,
    )
    result = await session.execute(q)
    detail = result.scalars().first()
    if not detail:
        raise HTTPException(404, "Construction detail not found")

    path = Path(detail.file_path)
    if not path.exists():
        raise HTTPException(404, "File not found on disk")

    try:
        decrypted_bytes = read_decrypted_file(path, user.email)
        media_type = detail.mime_type
        if not media_type or media_type == "application/octet-stream":
            guessed, _ = mimetypes.guess_type(detail.filename)
            media_type = guessed or "application/octet-stream"
        if detail.filename.lower().endswith(".pdf"):
            media_type = "application/pdf"

        return Response(
            content=decrypted_bytes,
            media_type=media_type,
            headers={
                "Content-Disposition": make_content_disposition("attachment", detail.filename),
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    except Exception as e:
        raise HTTPException(500, f"Failed to decrypt file: {e}")


@router.patch("/{detail_id}", response_model=ConstructionDetailOut)
async def update_construction_detail(
    detail_id: int,
    payload: ConstructionDetailUpdate,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    q = select(ConstructionDetail).where(
        ConstructionDetail.id == detail_id,
        ConstructionDetail.created_by == user.email,
    )
    result = await session.execute(q)
    detail = result.scalars().first()
    if not detail:
        raise HTTPException(404, "Construction detail not found")

    if payload.name is not None:
        trimmed_name = payload.name.strip()
        if not trimmed_name:
            raise HTTPException(400, "Name cannot be empty")
        detail.name = trimmed_name

    if payload.manufacturer is not None:
        trimmed_manufacturer = payload.manufacturer.strip()
        if not trimmed_manufacturer:
            raise HTTPException(400, "Manufacturer cannot be empty")
        detail.manufacturer = trimmed_manufacturer

    if payload.details is not None:
        detail.details = payload.details.strip() if payload.details else None

    await session.commit()
    await session.refresh(detail)
    return detail


@router.delete("/{detail_id}")
async def delete_construction_detail(
    detail_id: int,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    q = select(ConstructionDetail).where(
        ConstructionDetail.id == detail_id,
        ConstructionDetail.created_by == user.email,
    )
    result = await session.execute(q)
    detail = result.scalars().first()
    if not detail:
        raise HTTPException(404, "Construction detail not found")

    path = Path(detail.file_path)
    if path.exists():
        try:
            path.unlink()
        except Exception as e:
            print(f"Warning: could not delete file {path}: {e}")

    await session.delete(detail)
    await session.commit()

    return {"status": "ok", "deleted_id": detail_id}
