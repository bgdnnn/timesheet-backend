from fastapi import Depends, HTTPException, status, Request
import jwt
import secrets
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from .config import settings
from .db import get_session
from .models import User, RevokedToken

def make_token(data: dict, minutes: int | None = None, days: int | None = None):
    to_encode = data.copy()
    if minutes is not None:
        exp = datetime.utcnow() + timedelta(minutes=minutes)
    else:
        exp = datetime.utcnow() + timedelta(days=days or 1)
    # jti lets logout revoke this specific token server-side
    to_encode.update({"exp": exp, "jti": secrets.token_urlsafe(16)})
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALG)

def get_request_token(request: Request) -> str | None:
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1]
    return request.cookies.get("access_token")

def decode_token(token: str) -> dict:
    return jwt.decode(
        token, settings.JWT_SECRET, algorithms=[settings.JWT_ALG],
        options={"require": ["exp", "sub", "jti"]},
    )

async def get_current_user(request: Request, session: AsyncSession = Depends(get_session)):
    token = get_request_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        payload = decode_token(token)
        uid = int(payload.get("sub"))
    except (jwt.PyJWTError, TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token")

    if await session.get(RevokedToken, payload["jti"]):
        raise HTTPException(status_code=401, detail="Token revoked")

    user = (await session.execute(select(User).where(User.id == uid))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    request.state.jwt_payload = payload
    return user

async def get_admin_user(current_user: User = Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The user does not have admin privileges",
        )
    return current_user
