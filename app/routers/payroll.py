from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..db import get_session
from ..services.payroll import get_profile, upsert_profile_from_payslip
from ..models import Payslip
from ..schemas import PayrollProfileOut
from ..lib.uk_tax import calc_pay_period, D
from .auth_google import get_current_user

router = APIRouter(prefix="/payroll", tags=["payroll"])

class PayrollIn(BaseModel):
    gross: Decimal
    period: str = "weekly"
    region: str | None = None
    pension_employee_percent: Decimal | None = None
    use_profile: bool = True

    @field_validator("period")
    @classmethod
    def _ok(cls, v):
        if v not in {"weekly","monthly","annual"}:
            raise ValueError("period invalid")
        return v

@router.get("/profile", response_model=PayrollProfileOut | None)
async def profile(session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    return await get_profile(session, user)

@router.post("/recalibrate", response_model=PayrollProfileOut)
async def recalibrate(session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    q = select(Payslip).where(Payslip.created_by == user.email).order_by(Payslip.created_date.desc())
    ps = (await session.execute(q)).scalars().first()
    if not ps:
        raise HTTPException(404, "No payslip found")
    prof = await upsert_profile_from_payslip(session, user, ps)
    await session.commit()
    await session.refresh(prof)
    return prof

@router.post("/calc")
async def calc(inp: PayrollIn, session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    prof = await get_profile(session, user) if inp.use_profile else None
    region   = inp.region or (prof.region if prof else "rUK")
    pension  = inp.pension_employee_percent if inp.pension_employee_percent is not None else (prof.pension_employee_percent if prof else D("0"))
    tax_off  = prof.tax_offset if prof else D("0")
    ni_off   = prof.ni_offset if prof else D("0")
    out = calc_pay_period(inp.gross, inp.period, region, pension or D("0"), tax_off or D("0"), ni_off or D("0"))
    return out
