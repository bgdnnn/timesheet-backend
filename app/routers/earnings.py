from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, and_
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import List, Optional
from pathlib import Path
import json

from ..db import get_session
from ..auth import get_current_user
from ..models import WeeklyEarnings, User, PayrollProfile, PayslipFile
from ..schemas import WeeklyEarningsOut
from pydantic import BaseModel
from ..services.weekly_calculator import recalculate_all_earnings, calculate_single_week_earnings
from ..services.payroll import get_profile, D
from ..utils.users import user_slug_from_identity
from ..config import settings
from ..utils.dates import week_monday
from ..utils.tax_year import tax_period_to_date, get_tax_week, get_tax_year_start_date

router = APIRouter(prefix="/earnings", tags=["earnings"])

class PayslipBreakdownItem(BaseModel):
    id: int
    filename: str
    tax_year: str
    tax_week: int
    process_date: date
    gross_pay: Decimal
    paye_tax: Decimal
    national_insurance: Decimal
    pension: Decimal
    net_pay: Decimal
    deductions_total: Decimal

def get_tax_year_str(d: date) -> str:
    if d.month < 4 or (d.month == 4 and d.day < 6):
        start_y, end_y = d.year - 1, d.year
    else:
        start_y, end_y = d.year, d.year + 1
    return f"{str(start_y)[2:]}-{str(end_y)[2:]}"

def date_range_for_tax_year(tax_year_str: str):
    try:
        parts = tax_year_str.split("-")
        start_yy = int(parts[0])
        end_yy = int(parts[1])
        start_year = 2000 + start_yy
        end_year = 2000 + end_yy
        start_date = date(start_year, 4, 6)
        end_date = date(end_year, 4, 5)
        return start_date, end_date
    except Exception:
        today = date.today()
        start_date = get_tax_year_start_date(today)
        end_date = start_date + timedelta(days=365)
        return start_date, end_date

class EarningsYTDOut(BaseModel):
    gross_pay: Decimal
    paye_tax: Decimal
    national_insurance: Decimal
    pension: Decimal
    net_pay: Decimal
    guild_tax: Decimal = Decimal("0")
    breakdown: List[PayslipBreakdownItem] = []
    available_years: List[str] = []
    selected_year: str

class CalculateWeekIn(BaseModel):
    week_start: date

class ManualWageIn(BaseModel):
    week_start: date
    hourly_wage: float

@router.get("/ytd", response_model=EarningsYTDOut)
async def get_earnings_ytd(
    tax_year: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user)
):
    # Distinct available tax years for dropdown
    available_years = []
    if user.employment_type == "employed":
        q_years = select(PayslipFile.tax_year).where(
            PayslipFile.created_by == user.email,
            PayslipFile.tax_week > 0,
            PayslipFile.net_pay.isnot(None),
            PayslipFile.gross_pay.isnot(None)
        ).distinct().order_by(desc(PayslipFile.tax_year))
        res_years = await session.execute(q_years)
        available_years = [y for y in res_years.scalars().all() if y]
    else:
        q_weeks = select(WeeklyEarnings.week_start).where(
            WeeklyEarnings.created_by == user.email
        ).distinct().order_by(desc(WeeklyEarnings.week_start))
        res_weeks = await session.execute(q_weeks)
        weeks = res_weeks.scalars().all()
        seen_years = set()
        for w in weeks:
            yr_str = get_tax_year_str(w)
            if yr_str not in seen_years:
                seen_years.add(yr_str)
                available_years.append(yr_str)
        available_years.sort(reverse=True)

    # Determine selected tax year and start/end dates
    today = date.today()
    if not tax_year:
        tax_year = get_tax_year_str(today)
    
    if tax_year not in available_years:
        available_years.insert(0, tax_year)

    tax_year_start, tax_year_end = date_range_for_tax_year(tax_year)

    if user.employment_type == "employed":
        # Sum parsed fields directly from payslip_files table (excluding P60/tax_week=0)
        q_sum = select(
            func.sum(PayslipFile.gross_pay).label("gross"),
            func.sum(PayslipFile.paye_tax).label("tax"),
            func.sum(PayslipFile.national_insurance).label("ni"),
            func.sum(PayslipFile.pension).label("pension"),
            func.sum(PayslipFile.net_pay).label("net")
        ).where(
            PayslipFile.created_by == user.email,
            PayslipFile.process_date >= tax_year_start,
            PayslipFile.process_date <= tax_year_end,
            PayslipFile.tax_week > 0,
            PayslipFile.net_pay.isnot(None),
            PayslipFile.gross_pay.isnot(None)
        )
        res_sum = (await session.execute(q_sum)).one()

        # Fetch list of weekly payslips for the breakdown (sorted by tax_week desc)
        q_list = select(PayslipFile).where(
            PayslipFile.created_by == user.email,
            PayslipFile.process_date >= tax_year_start,
            PayslipFile.process_date <= tax_year_end,
            PayslipFile.tax_week > 0,
            PayslipFile.net_pay.isnot(None),
            PayslipFile.gross_pay.isnot(None)
        ).order_by(desc(PayslipFile.tax_week))
        pfs = (await session.execute(q_list)).scalars().all()

        breakdown = []
        for pf in pfs:
            breakdown.append({
                "id": pf.id,
                "filename": pf.filename,
                "tax_year": pf.tax_year,
                "tax_week": pf.tax_week,
                "process_date": pf.process_date,
                "gross_pay": pf.gross_pay or Decimal("0"),
                "paye_tax": pf.paye_tax or Decimal("0"),
                "national_insurance": pf.national_insurance or Decimal("0"),
                "pension": pf.pension or Decimal("0"),
                "net_pay": pf.net_pay or Decimal("0"),
                "deductions_total": pf.deductions_total or Decimal("0")
            })

        return EarningsYTDOut(
            gross_pay=res_sum.gross or Decimal("0"),
            paye_tax=res_sum.tax or Decimal("0"),
            national_insurance=res_sum.ni or Decimal("0"),
            pension=res_sum.pension or Decimal("0"),
            net_pay=res_sum.net or Decimal("0"),
            guild_tax=Decimal("0"),
            breakdown=breakdown,
            available_years=available_years,
            selected_year=tax_year
        )
    else:
        # Self-employed: Sum up WEEKLY EARNINGS rows for the current tax year.
        q = select(
            func.sum(WeeklyEarnings.gross_pay).label("gross"),
            func.sum(WeeklyEarnings.paye_tax).label("tax"),
            func.sum(WeeklyEarnings.national_insurance).label("ni"),
            func.sum(WeeklyEarnings.pension).label("pension"),
            func.sum(WeeklyEarnings.net_pay).label("net"),
            func.sum(WeeklyEarnings.guild_tax).label("guild")
        ).where(
            and_(
                WeeklyEarnings.created_by == user.email,
                WeeklyEarnings.week_start >= tax_year_start,
                WeeklyEarnings.week_start <= tax_year_end
            )
        )
        
        result = (await session.execute(q)).one()
        
        return EarningsYTDOut(
            gross_pay=D(result.gross or 0),
            paye_tax=D(result.tax or 0),
            national_insurance=D(result.ni or 0),
            pension=D(result.pension or 0),
            net_pay=D(result.net or 0),
            guild_tax=D(result.guild or 0),
            available_years=available_years,
            selected_year=tax_year
        )

@router.get("/for-week", response_model=WeeklyEarningsOut | None)
async def for_week(week_start: date, session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    q = select(WeeklyEarnings).where(
        WeeklyEarnings.created_by == user.email,
        WeeklyEarnings.week_start == week_start
    ).order_by(WeeklyEarnings.id.desc())
    result = (await session.execute(q)).scalars().first()

    if result:
        payment_date = week_start + timedelta(weeks=2)
        result.tax_week = get_tax_week(payment_date)

    return result


@router.post("/recalculate", status_code=200)
async def trigger_recalculation(user=Depends(get_current_user)):
    try:
        await recalculate_all_earnings(user)
        return {"status": "ok", "message": "Earnings recalculated successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred during recalculation: {e}")

@router.post("/calculate-week", status_code=200)
async def calculate_week_endpoint(
    calculate_week_in: CalculateWeekIn,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    try:
        await calculate_single_week_earnings(session, user, calculate_week_in.week_start)
        return {"status": "ok", "message": f"Earnings for week {calculate_week_in.week_start} calculated successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred during single week calculation: {e}")

@router.patch("/for-week", status_code=200)
async def update_week_wage(
    payload: ManualWageIn,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    try:
        await calculate_single_week_earnings(session, user, payload.week_start, manual_wage=payload.hourly_wage)
        return {"status": "ok", "message": f"Hourly wage for week {payload.week_start} updated to {payload.hourly_wage}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred while updating week wage: {e}")
