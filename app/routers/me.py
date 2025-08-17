from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update
from ..db import get_session
from ..auth import get_current_user
from ..schemas import UserOut, UserUpdate
from ..models import User

router = APIRouter(tags=["me"])

@router.get("/me", response_model=UserOut)
async def me(current=Depends(get_current_user)):
    # Map created/updated
    current.created_date = getattr(current, "created_at", None)
    current.updated_date = getattr(current, "updated_at", None)
    return current

@router.patch("/me", response_model=UserOut)
async def update_me(payload: UserUpdate, current=Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    await session.execute(
        update(User).where(User.id == current.id).values(
            company=payload.company if payload.company is not None else current.company,
            wage=payload.wage if payload.wage is not None else current.wage,
        )
    )
    await session.commit()
    return await me(current)
