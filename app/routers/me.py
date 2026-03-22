# app/routers/me.py
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from ..db import get_session
from ..models import User
from ..auth import get_current_user
import json
from pathlib import Path
from ..config import settings
from ..utils.users import user_slug_from_identity

router = APIRouter(prefix="", tags=["me"])

class MeOut(BaseModel):
    email: str
    full_name: str | None = None
    company: str | None = None
    wage: float | None = None
    role: str
    is_calculator_enabled: bool = True
    employment_type: str = "employed"
    guild_tax: float | None = None
    has_payslip: bool = False

class MeUpdate(BaseModel):
    company: str | None = None
    wage: float | None = None
    is_calculator_enabled: bool | None = None
    employment_type: str | None = None
    guild_tax: float | None = None

    @field_validator("wage")
    @classmethod
    def non_negative(cls, v):
        if v is None: return v
        if v < 0: raise ValueError("wage must be >= 0")
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
        wage=float(db_user.wage) if db_user.wage is not None else None,
        role=db_user.role,
        is_calculator_enabled=db_user.is_calculator_enabled,
        employment_type=db_user.employment_type,
        guild_tax=db_user.guild_tax,
        has_payslip=db_user.has_payslip,
    )

@router.put("/me", response_model=MeOut)
async def update_me(payload: MeUpdate, user=Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    q = select(User).where(User.email == user.email)
    db_user = (await session.execute(q)).scalars().first()
    if not db_user:
        raise HTTPException(404, "User not found")

    if payload.company is not None:
        db_user.company = payload.company.strip()
    
    if payload.wage is not None:
        db_user.wage = payload.wage

    if payload.is_calculator_enabled is not None:
        db_user.is_calculator_enabled = payload.is_calculator_enabled
    
    if payload.employment_type is not None:
        db_user.employment_type = payload.employment_type
    
    if payload.guild_tax is not None:
        db_user.guild_tax = payload.guild_tax

    await session.commit()
    # refresh
    db_user = (await session.execute(q)).scalars().first()

    return MeOut(
        email=db_user.email,
        full_name=db_user.full_name,
        company=db_user.company,
        wage=float(db_user.wage) if db_user.wage is not None else None,
        role=db_user.role,
        is_calculator_enabled=db_user.is_calculator_enabled,
        employment_type=db_user.employment_type,
        guild_tax=db_user.guild_tax,
        has_payslip=db_user.has_payslip,
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
