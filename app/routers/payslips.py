from fastapi import APIRouter, Depends, HTTPException
from pathlib import Path
import json
from datetime import date, datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..config import settings
from ..auth import get_current_user
from ..db import get_session
from ..services.payroll import upsert_profile_from_payslip
from ..utils.tax_year import tax_period_to_date
from ..utils.users import user_slug_from_identity
from ..utils.dates import week_monday
from ..schemas import ManualPayslipIn
from ..models import PayslipFile
from ..services.weekly_calculator import recalculate_all_earnings
from ..services.payroll import upsert_profile_from_payslip

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

    # Parse dates and compute tax info
    process_date = None
    if payslip_data_in.process_date:
        try:
            process_date = datetime.strptime(payslip_data_in.process_date, "%d/%m/%Y").date()
        except ValueError:
            pass
    if not process_date:
        process_date = date.today()

    tax_week = payslip_data_in.tax_period
    today = date.today()
    if today.month < 4 or (today.month == 4 and today.day < 6):
        start_y, end_y = today.year - 1, today.year
    else:
        start_y, end_y = today.year, today.year + 1
    tax_year = f"{str(start_y)[2:]}-{str(end_y)[2:]}"

    filename = f"manual_{tax_year}_{tax_week}"

    # Upsert into payslip_files
    q = select(PayslipFile).where(
        PayslipFile.created_by == user.email,
        PayslipFile.tax_year == tax_year,
        PayslipFile.tax_week == tax_week
    )
    res = await session.execute(q)
    pf = res.scalars().first()

    if not pf:
        pf = PayslipFile(
            created_by=user.email,
            file_path="manual",
            filename=filename,
            tax_year=tax_year,
            tax_week=tax_week,
            process_date=process_date
        )
        session.add(pf)

    pf.gross_pay = payslip_data_in.total_gross_pay
    pf.paye_tax = payslip_data_in.paye_tax
    pf.national_insurance = payslip_data_in.national_insurance
    pf.pension = payslip_data_in.pension
    pf.net_pay = payslip_data_in.calculated_net_pay
    pf.tax_code = payslip_data_in.tax_code
    pf.tax_period = payslip_data_in.tax_period
    pf.ytd_gross = payslip_data_in.ytd_gross
    pf.ytd_tax = payslip_data_in.ytd_tax
    pf.ytd_ni = payslip_data_in.ytd_ni
    pf.deductions_total = payslip_data_in.deductions_total

    await session.commit()

    # Trigger full recalculation
    await recalculate_all_earnings(user)

    return {"status": "ok", "message": "Payslip data saved and earnings recalculated.", "data": manual_data}

@router.get("/for-week")
async def for_week(
    week_start: date,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    # Retrieve matching payslip based on process_date - 2 weeks == week_start
    q = select(PayslipFile).where(
        PayslipFile.created_by == user.email,
        PayslipFile.net_pay.isnot(None),
        PayslipFile.gross_pay.isnot(None)
    )
    res = await session.execute(q)
    pfs = res.scalars().all()

    for pf in pfs:
        try:
            payslip_week_start = week_monday(pf.process_date - timedelta(weeks=2))
            if payslip_week_start == week_start:
                return {
                    "id": pf.id,
                    "filename": pf.filename,
                    "tax_year": pf.tax_year,
                    "tax_week": pf.tax_week,
                    "process_date": pf.process_date.strftime("%d/%m/%Y"),
                    "total_gross_pay": float(pf.gross_pay or 0),
                    "gross_pay": float(pf.gross_pay or 0),
                    "paye_tax": float(pf.paye_tax or 0),
                    "national_insurance": float(pf.national_insurance or 0),
                    "pension": float(pf.pension or 0),
                    "net_pay": float(pf.net_pay or 0),
                    "calculated_net_pay": float(pf.net_pay or 0),
                    "deductions_total": float(pf.deductions_total or 0),
                    "tax_code": pf.tax_code,
                    "tax_period": pf.tax_period,
                    "ytd_gross": float(pf.ytd_gross or 0),
                    "ytd_tax": float(pf.ytd_tax or 0),
                    "ytd_ni": float(pf.ytd_ni or 0),
                    "source": "manual" if pf.file_path == "manual" else "ocr"
                }
        except Exception:
            pass

    return None
