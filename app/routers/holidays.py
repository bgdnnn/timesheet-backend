from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert, update, delete
from datetime import date as DateType
from ..db import get_session
from ..auth import get_current_user
from ..schemas import HolidayIn, HolidayOut
from ..models import Holiday
from .helpers import apply_sort

router = APIRouter(prefix="/holidays", tags=["holidays"])

@router.get("", response_model=list[HolidayOut])
async def list_holidays(
    sort: str | None = "date",
    date: DateType | None = None,
    from_date: DateType | None = Query(None, alias="from"),
    to_date: DateType | None = Query(None, alias="to"),
    session: AsyncSession = Depends(get_session),
    current=Depends(get_current_user),
):
    stmt = select(Holiday).where(Holiday.created_by == current.email)
    if date:
        stmt = stmt.where(Holiday.date == date)
    if from_date:
        stmt = stmt.where(Holiday.date >= from_date)
    if to_date:
        stmt = stmt.where(Holiday.date <= to_date)
    stmt = apply_sort(stmt, Holiday, sort or "date")
    rows = (await session.execute(stmt)).scalars().all()
    return rows

@router.post("", response_model=HolidayOut)
async def create_holiday(payload: HolidayIn, session: AsyncSession = Depends(get_session), current=Depends(get_current_user)):
    stmt = select(Holiday).where(Holiday.created_by == current.email, Holiday.date == payload.date)
    existing = (await session.execute(stmt)).scalars().first()
    if existing:
        existing.type = payload.type
        existing.notes = payload.notes
        await session.commit()
        await session.refresh(existing)
        return existing
    
    res = await session.execute(
        insert(Holiday).values(
            created_by=current.email,
            date=payload.date,
            type=payload.type,
            notes=payload.notes,
        ).returning(Holiday)
    )
    row = res.scalar_one()
    await session.commit()
    return row

@router.delete("/{hid}")
async def delete_holiday(hid: int, session: AsyncSession = Depends(get_session), current=Depends(get_current_user)):
    await session.execute(delete(Holiday).where(Holiday.id == hid, Holiday.created_by == current.email))
    await session.commit()
    return {"status": "ok"}

@router.delete("/date/{date_str}")
async def delete_holiday_by_date(date_str: DateType, session: AsyncSession = Depends(get_session), current=Depends(get_current_user)):
    await session.execute(delete(Holiday).where(Holiday.date == date_str, Holiday.created_by == current.email))
    await session.commit()
    return {"status": "ok"}
