from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert, update, delete
from datetime import date as DateType
from ..db import get_session
from ..auth import get_current_user
from ..schemas import TimeEntryIn, TimeEntryOut
from ..models import TimeEntry
from .helpers import apply_sort

router = APIRouter(prefix="/time-entries", tags=["time_entries"])

@router.get("", response_model=list[TimeEntryOut])
async def list_entries(
    sort: str | None = "-created_at",
    created_by: str | None = None,
    from_date: DateType | None = Query(None, alias="from"),
    to_date: DateType | None = Query(None, alias="to"),
    project_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    current=Depends(get_current_user),
):
    stmt = select(TimeEntry).where(TimeEntry.user_id == current.id)
    if project_id:
        stmt = stmt.where(TimeEntry.project_id == project_id)
    if from_date:
        stmt = stmt.where(TimeEntry.date >= from_date)
    if to_date:
        stmt = stmt.where(TimeEntry.date <= to_date)
    stmt = apply_sort(stmt, TimeEntry, sort or "-created_at")
    rows = (await session.execute(stmt)).scalars().all()
    for r in rows:
        r.created_date = r.created_at
        r.updated_date = r.updated_at
    return rows

@router.post("", response_model=TimeEntryOut)
async def create_entry(payload: TimeEntryIn, session: AsyncSession = Depends(get_session), current=Depends(get_current_user)):
    duration = int(round((payload.hours_worked + payload.travel_time) * 60))
    res = await session.execute(
        insert(TimeEntry).values(
            user_id=current.id,
            project_id=payload.project_id,
            project_name=payload.project_name,
            date=payload.date,
            hours_worked=payload.hours_worked,
            travel_time=payload.travel_time,
            hotel_id=payload.hotel_id,
            hotel_name=payload.hotel_name,
            notes=payload.notes,
            duration_minutes=duration,
            created_by=current.email,
        ).returning(TimeEntry)
    )
    row = res.scalar_one()
    await session.commit()
    row.created_date = row.created_at
    row.updated_date = row.updated_at
    return row

@router.patch("/{tid}", response_model=TimeEntryOut)
async def update_entry(tid: int, payload: TimeEntryIn, session: AsyncSession = Depends(get_session), current=Depends(get_current_user)):
    duration = int(round((payload.hours_worked + payload.travel_time) * 60))
    await session.execute(
        update(TimeEntry).where(TimeEntry.id == tid, TimeEntry.user_id == current.id).values(
            project_id=payload.project_id,
            project_name=payload.project_name,
            date=payload.date,
            hours_worked=payload.hours_worked,
            travel_time=payload.travel_time,
            hotel_id=payload.hotel_id,
            hotel_name=payload.hotel_name,
            notes=payload.notes,
            duration_minutes=duration,
        )
    )
    await session.commit()
    return (await session.execute(select(TimeEntry).where(TimeEntry.id == tid))).scalar_one()

@router.delete("/{tid}")
async def delete_entry(tid: int, session: AsyncSession = Depends(get_session), current=Depends(get_current_user)):
    await session.execute(delete(TimeEntry).where(TimeEntry.id == tid, TimeEntry.user_id == current.id))
    await session.commit()
    return {"status": "ok"}
