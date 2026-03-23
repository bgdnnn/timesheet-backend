from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pathlib import Path
import shutil
from datetime import date, timedelta
from typing import List, Optional

from ..db import get_session
from ..auth import get_current_user
from ..models import PayslipFile
from ..schemas import PayslipFileOut
from ..config import settings
from ..utils.users import user_slug_from_identity
from ..utils.tax_year import tax_period_to_date

router = APIRouter(prefix="/payslip-files", tags=["payslip-files"])

@router.post("/upload", response_model=PayslipFileOut)
async def upload_payslip_file(
    file: UploadFile = File(...),
    process_date: Optional[date] = Form(None),
    tax_week: int = Form(...),
    tax_year: str = Form(...), # format ex: "25-26"
    user = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are allowed")

    # If no process_date provided, calculate a dummy one from the tax week
    if not process_date:
        try:
            # Convert "25-26" to 2025
            start_year_short = tax_year.split("-")[0]
            start_year = 2000 + int(start_year_short)
            process_date = tax_period_to_date(start_year, tax_week)
        except Exception:
            process_date = date.today()

    safe_user = user_slug_from_identity(user)
    media_root = Path(settings.MEDIA_ROOT)
    user_payslips_dir = media_root / safe_user / "payslips_pdf"
    user_payslips_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{tax_year}_{tax_week}.pdf"
    file_path = user_payslips_dir / filename

    try:
        content = await file.read()
        with file_path.open("wb") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(500, f"Failed to save file: {e}")

    new_file = PayslipFile(
        created_by=user.email,
        file_path=str(file_path),
        filename=filename,
        tax_year=tax_year,
        tax_week=tax_week,
        process_date=process_date
    )
    session.add(new_file)
    await session.commit()
    await session.refresh(new_file)

    return new_file

@router.get("", response_model=List[PayslipFileOut])
async def list_payslip_files(
    user = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    q = select(PayslipFile).where(PayslipFile.created_by == user.email).order_by(
        desc(PayslipFile.tax_year),
        desc(PayslipFile.tax_week)
    )
    result = await session.execute(q)
    return result.scalars().all()

@router.get("/{file_id}/view")
async def view_payslip_file(
    file_id: int,
    user = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    q = select(PayslipFile).where(PayslipFile.id == file_id, PayslipFile.created_by == user.email)
    result = await session.execute(q)
    pf = result.scalars().first()
    if not pf:
        raise HTTPException(404, "File not found")

    path = Path(pf.file_path)
    if not path.exists():
        raise HTTPException(404, "File not found on disk")

    return FileResponse(path, media_type="application/pdf", content_disposition_type="inline")

@router.get("/{file_id}/download")
async def download_payslip_file(
    file_id: int,
    user = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    q = select(PayslipFile).where(PayslipFile.id == file_id, PayslipFile.created_by == user.email)
    result = await session.execute(q)
    pf = result.scalars().first()
    if not pf:
        raise HTTPException(404, "File not found")

    path = Path(pf.file_path)
    if not path.exists():
        raise HTTPException(404, "File not found on disk")

    return FileResponse(path, media_type="application/pdf", filename=pf.filename, content_disposition_type="attachment")

@router.delete("/{file_id}")
async def delete_payslip_file(
    file_id: int,
    user = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    q = select(PayslipFile).where(PayslipFile.id == file_id, PayslipFile.created_by == user.email)
    result = await session.execute(q)
    pf = result.scalars().first()
    if not pf:
        raise HTTPException(404, "File not found")

    path = Path(pf.file_path)
    if path.exists():
        path.unlink()

    await session.delete(pf)
    await session.commit()

    return {"status": "ok"}
