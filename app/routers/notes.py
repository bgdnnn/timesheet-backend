from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert, update, delete
from datetime import date as DateType
from ..db import get_session
from ..auth import get_current_user
from ..schemas import NoteIn, NoteOut
from ..models import Note
from .helpers import apply_sort

router = APIRouter(prefix="/notes", tags=["notes"])

@router.get("", response_model=list[NoteOut])
async def list_notes(
    sort: str | None = "-created_at",
    date: DateType | None = None,
    from_date: DateType | None = Query(None, alias="from"),
    to_date: DateType | None = Query(None, alias="to"),
    session: AsyncSession = Depends(get_session),
    current=Depends(get_current_user),
):
    stmt = select(Note).where(Note.created_by == current.email)
    if date:
        stmt = stmt.where(Note.date == date)
    if from_date:
        stmt = stmt.where(Note.date >= from_date)
    if to_date:
        stmt = stmt.where(Note.date <= to_date)
    stmt = apply_sort(stmt, Note, sort or "-created_at")
    rows = (await session.execute(stmt)).scalars().all()
    return rows

@router.post("", response_model=NoteOut)
async def create_note(payload: NoteIn, session: AsyncSession = Depends(get_session), current=Depends(get_current_user)):
    res = await session.execute(
        insert(Note).values(
            created_by=current.email,
            date=payload.date,
            content=payload.content,
        ).returning(Note)
    )
    row = res.scalar_one()
    await session.commit()
    return row

@router.put("/{nid}", response_model=NoteOut)
async def update_note(nid: int, payload: NoteIn, session: AsyncSession = Depends(get_session), current=Depends(get_current_user)):
    await session.execute(
        update(Note).where(Note.id == nid, Note.created_by == current.email).values(
            date=payload.date,
            content=payload.content,
        )
    )
    await session.commit()
    return (await session.execute(select(Note).where(Note.id == nid))).scalar_one()

@router.delete("/{nid}")
async def delete_note(nid: int, session: AsyncSession = Depends(get_session), current=Depends(get_current_user)):
    await session.execute(delete(Note).where(Note.id == nid, Note.created_by == current.email))
    await session.commit()
    return {"status": "ok"}
