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
from ..models import WeeklyEarnings, User, PayrollProfile
from ..schemas import WeeklyEarningsOut
from pydantic import BaseModel
from ..services.weekly_calculator import recalculate_all_earnings, calculate_single_week_earnings
from ..services.payroll import get_profile, D
from ..utils.users import user_slug_from_identity
from ..config import settings
from ..utils.dates import week_monday
from ..utils.tax_year import tax_period_to_date, get_tax_week, get_tax_year_start_date

router = APIRouter(prefix="/earnings", tags=["earnings"])

class EarningsYTDOut(BaseModel):
    gross_pay: Decimal
    paye_tax: Decimal
    national_insurance: Decimal
    pension: Decimal
    net_pay: Decimal
    guild_tax: Decimal = Decimal("0")

class CalculateWeekIn(BaseModel):
    week_start: date

class ManualWageIn(BaseModel):
    week_start: date
    hourly_wage: float

@router.get("/ytd", response_model=EarningsYTDOut)
async def get_earnings_ytd(session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    # Calculate tax year start
    today = date.today()
    tax_year_start = get_tax_year_start_date(today)

    if user.employment_type == "employed":
        # Pull directly from PayrollProfile which stores "Last manual YTD + subsequent weeks"
        profile = await get_profile(session, user)
        if not profile:
            return EarningsYTDOut(gross_pay=0, paye_tax=0, national_insurance=0, pension=0, net_pay=0)
        
        gross = D(profile.ytd_gross or 0)
        tax = D(profile.ytd_tax or 0)
        ni = D(profile.ytd_ni or 0)
        pension = D(profile.ytd_pension or 0)
        
        return EarningsYTDOut(
            gross_pay=gross,
            paye_tax=tax,
            national_insurance=ni,
            pension=pension,
            net_pay=gross - tax - ni - pension,
            guild_tax=0
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
                WeeklyEarnings.week_start >= tax_year_start
            )
        )
        
        result = (await session.execute(q)).one()
        
        return EarningsYTDOut(
            gross_pay=D(result.gross or 0),
            paye_tax=D(result.tax or 0),
            national_insurance=D(result.ni or 0),
            pension=D(result.pension or 0),
            net_pay=D(result.net or 0),
            guild_tax=D(result.guild or 0)
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
