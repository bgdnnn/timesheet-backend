from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert, update, delete
from datetime import date as DateType
from ..db import get_session
from ..auth import get_current_user
from ..schemas import TimeEntryIn, TimeEntryOut
from ..models import TimeEntry, Project, Hotel
from .helpers import apply_sort, ensure_owned

router = APIRouter(prefix="/time-entries", tags=["time_entries"])

async def _check_refs(session: AsyncSession, payload: TimeEntryIn, current):
    await ensure_owned(session, Project, payload.project_id, Project.owner_user_id == current.id, "Project")
    await ensure_owned(session, Hotel, payload.hotel_id, Hotel.owner_user_id == current.id, "Hotel")

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
    await _check_refs(session, payload, current)
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
            created_by=current.email,
        ).returning(TimeEntry)
    )
    row = res.scalar_one()
    await session.commit()
    row.created_date = row.created_at
    row.updated_date = row.updated_at
    return row

@router.put("/{tid}", response_model=TimeEntryOut)
async def update_entry(tid: int, payload: TimeEntryIn, session: AsyncSession = Depends(get_session), current=Depends(get_current_user)):
    await _check_refs(session, payload, current)
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
        )
    )
    await session.commit()
    row = (await session.execute(select(TimeEntry).where(TimeEntry.id == tid, TimeEntry.user_id == current.id))).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Not found")
    return row

@router.delete("/{tid}")
async def delete_entry(tid: int, session: AsyncSession = Depends(get_session), current=Depends(get_current_user)):
    await session.execute(delete(TimeEntry).where(TimeEntry.id == tid, TimeEntry.user_id == current.id))
    await session.commit()
    return {"status": "ok"}
