# app/services/payroll.py
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..models import PayrollProfile, User
from ..lib.uk_tax import D


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

    prof.tax_code = payslip_data.get("tax_code") or prof.tax_code

    await session.flush()
    await session.refresh(prof)
    return prof