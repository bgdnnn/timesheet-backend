from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from pathlib import Path
import shutil
import tempfile
from PIL import Image
import pytesseract
import json
from datetime import date, datetime
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..auth import get_current_user
from ..db import get_session
from ..utils.payslip_parser import parse_payslip
from ..services.payroll import upsert_profile_from_payslip
from ..utils.tax_year import tax_period_to_date
from ..utils.users import user_slug_from_identity
from ..utils.dates import week_monday

router = APIRouter(prefix="/payslips", tags=["payslips"])

def _ocr(path: Path) -> str:
    img = Image.open(path)
    return pytesseract.image_to_string(img, config="--psm 6")

@router.post("/upload")
async def upload_payslip(
    file: UploadFile = File(...),
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    safe_user = user_slug_from_identity(user)
    media_root = Path(settings.MEDIA_ROOT)
    user_media_dir = media_root / safe_user
    user_media_dir.mkdir(parents=True, exist_ok=True)

    # Save the uploaded file temporarily
    with tempfile.NamedTemporaryFile(delete=False) as temp:
        shutil.copyfileobj(file.file, temp)
        temp_path = temp.name
    
    text = _ocr(Path(temp_path))
    parsed_data = parse_payslip(text)

    # Save the parsed data to a JSON file
    json_path = user_media_dir / "payslip.json"
    with open(json_path, "w") as f:
        json.dump(parsed_data, f, indent=4, default=str)

    # Clean up the temporary file
    import os
    os.remove(temp_path)

    # Update payroll profile
    await upsert_profile_from_payslip(session, user, parsed_data)
    await session.commit()

    return {"status": "ok", "filename": file.filename, "json_path": str(json_path)}

@router.get("/for-week")
async def for_week(week_start: date, user=Depends(get_current_user)):
    safe_user = user_slug_from_identity(user)
    media_root = Path(settings.MEDIA_ROOT)
    user_media_dir = media_root / safe_user
    json_path = user_media_dir / "payslip.json"

    if not json_path.exists():
        return None

    with open(json_path, "r") as f:
        payslip_data = json.load(f)

    process_date_str = payslip_data.get("process_date")
    if not process_date_str:
        return None

    try:
        process_date = datetime.strptime(process_date_str, "%d/%m/%Y").date()
    except ValueError:
        return None

    payslip_week_start = week_monday(process_date)

    if week_start != payslip_week_start:
        return None

    return {
        "gross_pay": payslip_data.get("total_gross_pay"),
        "paye_tax": payslip_data.get("paye_tax"),
        "national_insurance": payslip_data.get("national_insurance"),
        "pension": payslip_data.get("pension"),
        "net_pay": payslip_data.get("calculated_net_pay"),
    }