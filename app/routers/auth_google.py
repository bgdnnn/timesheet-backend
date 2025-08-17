from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from authlib.integrations.starlette_client import OAuth
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert, update
from . import helpers
from ..config import settings
from ..db import get_session
from ..models import User
from ..auth import make_token

router = APIRouter(prefix="/auth/google", tags=["auth"])

oauth = OAuth()
oauth.register(
    name="google",
    client_id=settings.GOOGLE_CLIENT_ID,
    client_secret=settings.GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

@router.get("/login")
async def google_login(request: Request, returnTo: str | None = None):
    redirect_uri = settings.OAUTH_REDIRECT_URI
    request.session.setdefault("oauth_return_to", returnTo)
    return await oauth.google.authorize_redirect(request, redirect_uri)

@router.get("/callback")
async def google_callback(request: Request, session: AsyncSession = Depends(get_session)):
    token = await oauth.google.authorize_access_token(request)
    userinfo = token.get("userinfo")
    if not userinfo:
        # Fallback to fetch userinfo endpoint
        resp = await oauth.google.get("userinfo")
        userinfo = resp.json()

    email = userinfo.get("email")
    full_name = userinfo.get("name")

    # Upsert user
    user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if not user:
        await session.execute(
            insert(User).values(email=email, full_name=full_name, role="user")
        )
    else:
        await session.execute(
            update(User).where(User.id == user.id).values(full_name=full_name)
        )
    await session.commit()

    # Re-fetch to get id
    user = (await session.execute(select(User).where(User.email == email))).scalar_one()

    access = make_token({"sub": str(user.id)}, minutes=settings.ACCESS_TOKEN_MINUTES)
    return_to = request.session.pop("oauth_return_to", None)

    # Set cookie for convenience AND pass token in URL fragment so SPA can store it
    redirect_url = (return_to or "/").split("#")[0]
    redirect_url = f"{redirect_url}#access_token={access}"
    resp = RedirectResponse(url=redirect_url, status_code=302)
    resp.set_cookie("access_token", access, httponly=True, secure=True, samesite="lax", max_age=3600)
    return resp
