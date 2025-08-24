# app/routers/me.py
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from ..db import get_session
from ..models import User
from ..auth import get_current_user  # whatever you used elsewhere to decode JWT/cookie
import json
from pathlib import Path
from ..config import settings
from ..utils.users import user_slug_from_identity

router = APIRouter(prefix="", tags=["me"])

class MeOut(BaseModel):
    email: str
    full_name: str | None = None
    company: str | None = None
    hourly_rate: float | None = None
    role: str

class MeUpdate(BaseModel):
    company: str | None = None
    hourly_rate: float | None = None

    @field_validator("hourly_rate")
    @classmethod
    def non_negative(cls, v):
        if v is None: return v
        if v < 0: raise ValueError("hourly_rate must be >= 0")
        return v

@router.get("/me", response_model=MeOut)
async def read_me(user=Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    q = select(User).where(User.email == user.email)
    db_user = (await session.execute(q)).scalars().first()
    if not db_user:
        raise HTTPException(404, "User not found")
    return MeOut(
        email=db_user.email,
        full_name=db_user.full_name,
        company=db_user.company,
        hourly_rate=float(db_user.hourly_rate) if db_user.hourly_rate is not None else None,
        role=db_user.role,
    )

@router.put("/me", response_model=MeOut)
async def update_me(payload: MeUpdate, user=Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    q = select(User).where(User.email == user.email)
    db_user = (await session.execute(q)).scalars().first()
    if not db_user:
        raise HTTPException(404, "User not found")

    values = {}
    if payload.company is not None:
        values["company"] = payload.company.strip()
    
    if values:
        await session.execute(
            update(User).where(User.id == db_user.id).values(**values)
        )
    
    if payload.hourly_rate is not None:
        db_user.hourly_rate = payload.hourly_rate

    await session.commit()
    # refresh
    db_user = (await session.execute(q)).scalars().first()

    return MeOut(
        email=db_user.email,
        full_name=db_user.full_name,
        company=db_user.company,
        hourly_rate=float(db_user.hourly_rate) if db_user.hourly_rate is not None else None,
    )

@router.get("/me/payslip")
async def get_payslip_json(user=Depends(get_current_user)):
    safe_user = user_slug_from_identity(user)
    media_root = Path(settings.MEDIA_ROOT)
    user_media_dir = media_root / safe_user
    json_path = user_media_dir / "payslip.json"

    if not json_path.exists():
        raise HTTPException(status_code=404, detail="Payslip not found")

    with open(json_path, "r") as f:
        payslip_data = json.load(f)

    return payslip_data