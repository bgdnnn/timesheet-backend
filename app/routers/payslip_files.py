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
from ..utils.payslip_ocr import extract_payslip_text, parse_payslip_text
from ..utils.security import decrypt_value

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

    # OCR parsing
    pdf_pw = decrypt_value(user.pdf_password) if hasattr(user, "pdf_password") else None
    gross_pay = None
    paye_tax = None
    national_insurance = None
    pension = None
    net_pay = None
    tax_code = None
    tax_period_val = None
    ytd_gross = None
    ytd_tax = None
    ytd_ni = None
    deductions_total = None

    try:
        raw_text = extract_payslip_text(str(file_path), pdf_pw)
        parsed = parse_payslip_text(raw_text)
        gross_pay = parsed.get("total_gross_pay")
        paye_tax = parsed.get("paye_tax")
        national_insurance = parsed.get("national_insurance")
        pension = parsed.get("pension")
        net_pay = parsed.get("calculated_net_pay")
        tax_code = parsed.get("tax_code")
        tax_period_val = parsed.get("tax_period")
        ytd_gross = parsed.get("ytd_gross")
        ytd_tax = parsed.get("ytd_tax")
        ytd_ni = parsed.get("ytd_ni")
        deductions_total = parsed.get("deductions_total")
    except Exception as ocr_err:
        print(f"OCR parsing failed for manual upload: {ocr_err}")

    new_file = PayslipFile(
        created_by=user.email,
        file_path=str(file_path),
        filename=filename,
        tax_year=tax_year,
        tax_week=tax_week,
        process_date=process_date,
        gross_pay=gross_pay,
        paye_tax=paye_tax,
        national_insurance=national_insurance,
        pension=pension,
        net_pay=net_pay,
        tax_code=tax_code,
        tax_period=tax_period_val,
        ytd_gross=ytd_gross,
        ytd_tax=ytd_tax,
        ytd_ni=ytd_ni,
        deductions_total=deductions_total
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

@router.get("/last/ocr")
async def run_ocr_on_last_payslip(
    user = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    q = select(PayslipFile).where(PayslipFile.created_by == user.email).order_by(
        desc(PayslipFile.tax_year),
        desc(PayslipFile.tax_week)
    ).limit(1)
    result = await session.execute(q)
    pf = result.scalars().first()
    if not pf:
        raise HTTPException(404, "No payslips found in your folder")

    path = Path(pf.file_path)
    if not path.exists():
        raise HTTPException(404, f"File {pf.filename} not found on disk")

    pdf_pw = decrypt_value(user.pdf_password) if hasattr(user, "pdf_password") else None

    try:
        raw_text = extract_payslip_text(str(path), pdf_pw)
        parsed_data = parse_payslip_text(raw_text)
        return {
            "raw_text": raw_text,
            "parsed_data": parsed_data,
            "filename": pf.filename,
            "id": pf.id,
            "tax_year": pf.tax_year,
            "tax_week": pf.tax_week
        }
    except Exception as e:
        raise HTTPException(500, f"OCR Extraction failed: {e}")

@router.get("/{file_id}/ocr")
async def run_ocr_on_payslip(
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

    pdf_pw = decrypt_value(user.pdf_password) if hasattr(user, "pdf_password") else None

    try:
        raw_text = extract_payslip_text(str(path), pdf_pw)
        parsed_data = parse_payslip_text(raw_text)
        return {
            "raw_text": raw_text,
            "parsed_data": parsed_data,
            "filename": pf.filename,
            "id": pf.id,
            "tax_year": pf.tax_year,
            "tax_week": pf.tax_week
        }
    except Exception as e:
        raise HTTPException(500, f"OCR Extraction failed: {e}")
