from fastapi import Depends, HTTPException, status, Request
from jose import jwt, JWTError
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from .config import settings
from .db import get_session
from .models import User

def make_token(data: dict, minutes: int | None = None, days: int | None = None):
    to_encode = data.copy()
    if minutes is not None:
        exp = datetime.utcnow() + timedelta(minutes=minutes)
    else:
        exp = datetime.utcnow() + timedelta(days=days or 1)
    to_encode.update({"exp": exp})
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALG)

async def get_current_user(request: Request, session: AsyncSession = Depends(get_session)):
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    token = None
    if auth and auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1]
    # Also accept token via cookie (optional)
    if not token:
        token = request.cookies.get("access_token")

    if not token:
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALG])
        uid = int(payload.get("sub"))
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = (await session.execute(select(User).where(User.id == uid))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user
