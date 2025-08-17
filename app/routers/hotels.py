from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert, update, delete
from ..db import get_session
from ..auth import get_current_user
from ..schemas import HotelIn, HotelOut
from ..models import Hotel
from .helpers import apply_sort

router = APIRouter(prefix="/hotels", tags=["hotels"])

@router.get("", response_model=list[HotelOut])
async def list_hotels(
    sort: str | None = "name",
    created_by: str | None = None,
    session: AsyncSession = Depends(get_session),
    current=Depends(get_current_user),
):
    stmt = select(Hotel).where(Hotel.owner_user_id == current.id)
    stmt = apply_sort(stmt, Hotel, sort or "name")
    rows = (await session.execute(stmt)).scalars().all()
    for r in rows:
        r.created_date = r.created_at
        r.updated_date = r.updated_at
    return rows

@router.post("", response_model=HotelOut)
async def create_hotel(payload: HotelIn, session: AsyncSession = Depends(get_session), current=Depends(get_current_user)):
    res = await session.execute(
        insert(Hotel).values(
            name=payload.name,
            address=payload.address or "",
            owner_user_id=current.id,
            created_by=current.email,
        ).returning(Hotel)
    )
    hotel = res.scalar_one()
    await session.commit()
    hotel.created_date = hotel.created_at
    hotel.updated_date = hotel.updated_at
    return hotel

@router.patch("/{hid}", response_model=HotelOut)
async def update_hotel(hid: int, payload: HotelIn, session: AsyncSession = Depends(get_session), current=Depends(get_current_user)):
    await session.execute(
        update(Hotel).where(Hotel.id == hid, Hotel.owner_user_id == current.id).values(
            name=payload.name,
            address=payload.address or "",
        )
    )
    await session.commit()
    return (await session.execute(select(Hotel).where(Hotel.id == hid))).scalar_one()

@router.delete("/{hid}")
async def delete_hotel(hid: int, session: AsyncSession = Depends(get_session), current=Depends(get_current_user)):
    await session.execute(delete(Hotel).where(Hotel.id == hid, Hotel.owner_user_id == current.id))
    await session.commit()
    return {"status": "ok"}
