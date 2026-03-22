from fastapi import APIRouter, Depends, HTTPException
from pathlib import Path
import json
from datetime import date, datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..auth import get_current_user
from ..db import get_session
from ..services.payroll import upsert_profile_from_payslip
from ..utils.tax_year import tax_period_to_date
from ..utils.users import user_slug_from_identity
from ..utils.dates import week_monday
from ..schemas import ManualPayslipIn
from ..services.weekly_calculator import recalculate_all_earnings

router = APIRouter(prefix="/payslips", tags=["payslips"])

@router.post("/manual-entry")
async def manual_payslip_entry(
    payslip_data_in: ManualPayslipIn,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    safe_user = user_slug_from_identity(user)
    media_root = Path(settings.MEDIA_ROOT)
    user_media_dir = media_root / safe_user
    user_media_dir.mkdir(parents=True, exist_ok=True)

    json_path = user_media_dir / "payslip.json"
    manual_data = payslip_data_in.model_dump()
    manual_data["source"] = "manual"
    with open(json_path, "w") as f:
        json.dump(manual_data, f, indent=4, default=str)

    # Update payroll profile
    await upsert_profile_from_payslip(session, user, manual_data)
    
    # Update user flag
    user.has_payslip = True
    session.add(user)
    
    await session.commit()

    # Trigger full recalculation
    await recalculate_all_earnings(user)

    return {"status": "ok", "message": "Payslip data saved and earnings recalculated.", "data": manual_data}

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
    tax_period = payslip_data.get("tax_period")
    
    print(f"DEBUG: for_week check. week_start={week_start}, process_date_str={process_date_str}, tax_period={tax_period}")

    payslip_week_start = None
    if process_date_str:
        try:
            process_date = datetime.strptime(process_date_str, "%d/%m/%Y").date()
            payslip_week_start = week_monday(process_date - timedelta(weeks=2))
            print(f"DEBUG: derived payslip_week_start from process_date = {payslip_week_start}")
        except (ValueError, TypeError) as e:
            print(f"DEBUG: error parsing process_date: {e}")

    if payslip_week_start is None and tax_period:
        try:
            today = date.today()
            tax_year = today.year
            if today.month < 4 or (today.month == 4 and today.day < 6):
                tax_year -= 1
            
            payslip_date_from_period = tax_period_to_date(tax_year, int(tax_period))
            payslip_week_start = week_monday(payslip_date_from_period - timedelta(weeks=2))
            print(f"DEBUG: derived payslip_week_start from tax_period = {payslip_week_start}")
        except (ValueError, TypeError) as e:
            print(f"DEBUG: error parsing tax_period: {e}")

    if not payslip_week_start:
        print("DEBUG: could not determine payslip_week_start")
        return None

    if week_start != payslip_week_start:
        print(f"DEBUG: week_start mismatch. requested={week_start}, payslip={payslip_week_start}")
        return None

    return {
        **payslip_data,
        "gross_pay": payslip_data.get("total_gross_pay"),
        "net_pay": payslip_data.get("calculated_net_pay") or payslip_data.get("net_pay"),
    }
