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

from ..utils.security import encrypt_value, decrypt_value

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
    is_auto_upload_enabled: bool = False
    auto_upload_provider: str | None = None
    auto_upload_folder: str | None = None
    auto_upload_company: str | None = None
    auto_upload_email: str | None = None
    auto_upload_app_password: str | None = None
    pdf_password: str | None = None

class MeUpdate(BaseModel):
    company: str | None = None
    wage: float | None = None
    is_calculator_enabled: bool | None = None
    employment_type: str | None = None
    guild_tax: float | None = None
    is_auto_upload_enabled: bool | None = None
    auto_upload_provider: str | None = None
    auto_upload_folder: str | None = None
    auto_upload_company: str | None = None
    auto_upload_email: str | None = None
    auto_upload_app_password: str | None = None
    pdf_password: str | None = None

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
        is_auto_upload_enabled=db_user.is_auto_upload_enabled,
        auto_upload_provider=db_user.auto_upload_provider,
        auto_upload_folder=db_user.auto_upload_folder,
        auto_upload_company=db_user.auto_upload_company,
        auto_upload_email=db_user.auto_upload_email,
        auto_upload_app_password=decrypt_value(db_user.auto_upload_app_password),
        pdf_password=decrypt_value(db_user.pdf_password),
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

    if payload.is_auto_upload_enabled is not None:
        db_user.is_auto_upload_enabled = payload.is_auto_upload_enabled
        
    if payload.auto_upload_provider is not None:
        db_user.auto_upload_provider = payload.auto_upload_provider.strip() if payload.auto_upload_provider else None
        
    if payload.auto_upload_folder is not None:
        db_user.auto_upload_folder = payload.auto_upload_folder.strip() if payload.auto_upload_folder else None
        
    if payload.auto_upload_company is not None:
        db_user.auto_upload_company = payload.auto_upload_company.strip() if payload.auto_upload_company else None
        
    if payload.auto_upload_email is not None:
        db_user.auto_upload_email = payload.auto_upload_email.strip() if payload.auto_upload_email else None
        
    if payload.auto_upload_app_password is not None:
        db_user.auto_upload_app_password = encrypt_value(payload.auto_upload_app_password.strip()) if payload.auto_upload_app_password else None
        
    if payload.pdf_password is not None:
        db_user.pdf_password = encrypt_value(payload.pdf_password.strip()) if payload.pdf_password else None

    await session.commit()
    # refresh
    db_user = (await session.execute(q)).scalars().first()

    # Verify and trigger download immediately if auto-upload is enabled
    if db_user.is_auto_upload_enabled and db_user.auto_upload_email and db_user.auto_upload_app_password:
        import asyncio
        import sys
        
        # Run downloader script as subprocess
        python_bin = sys.executable or "/srv/timesheet-backend/.venv/bin/python3"
        script_path = "/home/bgdn/download_payslips.py"
        
        try:
            proc = await asyncio.create_subprocess_exec(
                python_bin,
                script_path,
                "--email",
                db_user.email,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                err_msg = stderr.decode().strip() or stdout.decode().strip() or "Connection/Login verification failed"
                if err_msg.startswith("Error: "):
                    err_msg = err_msg[7:]
                raise HTTPException(status_code=400, detail=f"Auto-upload setup failed: {err_msg}")
        except HTTPException:
            raise
        except Exception as proc_err:
            raise HTTPException(status_code=500, detail=f"Failed to run auto-upload verification: {proc_err}")

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
        is_auto_upload_enabled=db_user.is_auto_upload_enabled,
        auto_upload_provider=db_user.auto_upload_provider,
        auto_upload_folder=db_user.auto_upload_folder,
        auto_upload_company=db_user.auto_upload_company,
        auto_upload_email=db_user.auto_upload_email,
        auto_upload_app_password=decrypt_value(db_user.auto_upload_app_password),
        pdf_password=decrypt_value(db_user.pdf_password),
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
