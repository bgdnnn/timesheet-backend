from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from datetime import date, datetime
from decimal import Decimal
from typing import List
from pathlib import Path
import json

from ..db import get_session
from ..auth import get_current_user
from ..models import WeeklyEarnings
from ..schemas import WeeklyEarningsOut
from pydantic import BaseModel
from ..services.weekly_calculator import recalculate_all_earnings
from ..services.payroll import get_profile
from ..utils.users import user_slug_from_identity
from ..config import settings
from ..utils.dates import week_monday
from ..utils.tax_year import tax_period_to_date
from ..lib.uk_tax import D

router = APIRouter(prefix="/earnings", tags=["earnings"])

class EarningsYTDOut(BaseModel):
    gross_pay: Decimal
    paye_tax: Decimal
    national_insurance: Decimal
    pension: Decimal
    net_pay: Decimal

@router.get("/ytd", response_model=EarningsYTDOut)
async def get_earnings_ytd(session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    profile = await get_profile(session, user)
    if not profile:
        return EarningsYTDOut(gross_pay=0, paye_tax=0, national_insurance=0, pension=0, net_pay=0)

    # Start with the YTD figures from the payslip (stored in the profile)
    ytd_gross = D(profile.ytd_gross or 0)
    ytd_tax = D(profile.ytd_tax or 0)
    ytd_ni = D(profile.ytd_ni or 0)
    ytd_pension = D(profile.ytd_pension or 0)

    # Find the payslip week start date to know where to start summing from
    safe_user = user_slug_from_identity(user)
    json_path = Path(settings.MEDIA_ROOT) / safe_user / "payslip.json"
    if not json_path.exists():
        return EarningsYTDOut(gross_pay=ytd_gross, paye_tax=ytd_tax, national_insurance=ytd_ni, pension=ytd_pension, net_pay=0)

    with open(json_path, "r") as f:
        payslip_data = json.load(f)

    payslip_week_start = None
    process_date_str = payslip_data.get("process_date")
    tax_period = payslip_data.get("tax_period")
    
    if process_date_str:
        try:
            process_date = datetime.strptime(process_date_str, "%d/%m/%Y").date()
            payslip_week_start = week_monday(process_date)
        except (ValueError, TypeError):
            pass

    if payslip_week_start is None and tax_period:
        today = date.today()
        tax_year = today.year
        if today.month < 4 or (today.month == 4 and today.day < 6):
            tax_year -= 1
        payslip_date_from_period = tax_period_to_date(tax_year, int(tax_period))
        payslip_week_start = week_monday(payslip_date_from_period)

    if payslip_week_start:
        # Sum up the earnings for all weeks AFTER the payslip week
        q = select(
            func.sum(WeeklyEarnings.gross_pay).label("gross_pay"),
            func.sum(WeeklyEarnings.paye_tax).label("paye_tax"),
            func.sum(WeeklyEarnings.national_insurance).label("national_insurance"),
            func.sum(WeeklyEarnings.pension).label("pension")
        ).where(
            WeeklyEarnings.created_by == user.email,
            WeeklyEarnings.week_start > payslip_week_start
        )
        forward_earnings = (await session.execute(q)).first()

        if forward_earnings and forward_earnings.gross_pay is not None:
            ytd_gross += D(forward_earnings.gross_pay)
            ytd_tax += D(forward_earnings.paye_tax)
            ytd_ni += D(forward_earnings.national_insurance)
            ytd_pension += D(forward_earnings.pension)

    return EarningsYTDOut(
        gross_pay=ytd_gross,
        paye_tax=ytd_tax,
        national_insurance=ytd_ni,
        pension=ytd_pension,
        net_pay=0 # Net pay is still not calculated for YTD
    )

@router.get("/for-week", response_model=WeeklyEarningsOut | None)
async def for_week(week_start: date, session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    q = select(WeeklyEarnings).where(
        WeeklyEarnings.created_by == user.email,
        WeeklyEarnings.week_start == week_start
    ).order_by(WeeklyEarnings.id.desc())
    result = (await session.execute(q)).scalars().first()
    return result

@router.post("/recalculate", status_code=200)
async def trigger_recalculation(user=Depends(get_current_user)):
    try:
        await recalculate_all_earnings(user)
        return {"status": "ok", "message": "Earnings recalculated successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred during recalculation: {e}")
