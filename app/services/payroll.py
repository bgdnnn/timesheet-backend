# app/services/payroll.py
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..models import PayrollProfile, User
from ..lib.uk_tax import calc_pay_period, D
from ..utils.payslip_parser import parse_payslip
from ..utils.users import user_slug_from_identity


def as_dec(x):
    if x is None:
        return None
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


async def get_profile(session: AsyncSession, user):
    q = select(PayrollProfile).where(PayrollProfile.created_by == user.email)
    return (await session.execute(q)).scalars().first()


async def upsert_profile_from_payslip(session: AsyncSession, user: User, payslip_data: dict) -> PayrollProfile:
    prof = await get_profile(session, user)
    if prof is None:
        prof = PayrollProfile(created_by=user.email)
        session.add(prof)

    prof.username = user_slug_from_identity(user)
    prof.tax_code = payslip_data.get("tax_code") or prof.tax_code
    prof.ni_number = payslip_data.get("ni_number") or prof.ni_number
    
    pension_employee = D(payslip_data.get("pension") or 0)
    gross_total = D(payslip_data.get("total_gross_pay") or 0)
    if pension_employee > 0 and gross_total > 0:
        prof.pension_employee_percent = (pension_employee / gross_total).quantize(D("0.0001"))
    elif not prof.pension_employee_percent:
        prof.pension_employee_percent = D("0.04")


    # Baseline figures from "this period"
    prof.baseline_gross = D(payslip_data.get("total_gross_pay") or 0)
    prof.baseline_paye = D(payslip_data.get("paye_tax") or 0)
    prof.baseline_ni = D(payslip_data.get("national_insurance") or 0)
    prof.baseline_pension = D(payslip_data.get("pension") or 0)
    prof.baseline_net = D(payslip_data.get("calculated_net_pay") or 0)

    # YTD figures
    prof.ytd_gross = D(payslip_data.get("ytd_gross") or 0)
    prof.ytd_tax = D(payslip_data.get("ytd_tax") or 0)
    prof.ytd_ni = D(payslip_data.get("ytd_ni") or 0)
    prof.ytd_pension = D(payslip_data.get("ytd_pension") or 0)

    await session.flush()
    await session.refresh(prof)
    return prof