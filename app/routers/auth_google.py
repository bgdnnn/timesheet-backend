# app/routers/auth_google.py
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from authlib.integrations.starlette_client import OAuth
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert, update
from ..config import settings
from ..db import get_session
from ..models import User
from ..auth import make_token
from pydantic import BaseModel
import secrets, time

router = APIRouter(prefix="/auth", tags=["auth"])

oauth = OAuth()
oauth.register(
    name="google",
    client_id=settings.GOOGLE_CLIENT_ID,
    client_secret=settings.GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

@router.get("/google/login")
async def google_login(request: Request, returnTo: str | None = None):
    # ensure the session is definitely mutated so cookie is set on this 302
    request.session["oauth_return_to"] = returnTo or "/"
    request.session["oauth_touch"] = time.time()  # guaranteed write

    # (optional) manually set state for extra robustness
    state = secrets.token_urlsafe(32)
    request.session["oauth_google_state"] = state

    redirect_uri = settings.OAUTH_REDIRECT_URI
    return await oauth.google.authorize_redirect(request, redirect_uri, state=state)

@router.get("/google/callback")
async def google_callback(request: Request, session: AsyncSession = Depends(get_session)):
    # Quick manual state check (helps diagnose if session not returning)
    state_param = request.query_params.get("state")
    saved_state = request.session.get("oauth_google_state")
    if not state_param or not saved_state or state_param != saved_state:
        # This is the same condition Authlib checks, but we raise a clearer message if it happens
        raise HTTPException(status_code=400, detail="OAuth state mismatch. Please clear site data and try again.")

    token = await oauth.google.authorize_access_token(request)
    userinfo = token.get("userinfo")
    if not userinfo:
        resp = await oauth.google.get("userinfo")
        userinfo = resp.json()

    email = userinfo.get("email")
    full_name = userinfo.get("name")

    # Upsert user
    user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if not user:
        await session.execute(insert(User).values(email=email, full_name=full_name, role="user"))
    else:
        await session.execute(update(User).where(User.id == user.id).values(full_name=full_name))
    await session.commit()

    user = (await session.execute(select(User).where(User.email == email))).scalar_one()

    access = make_token({"sub": str(user.id)}, minutes=settings.ACCESS_TOKEN_MINUTES)
    return_to = request.session.pop("oauth_return_to", "/")

    # send token back to SPA via URL fragment
    redirect_url = (return_to or "/").split("#")[0]
    redirect_url = f"{redirect_url}#access_token={access}"
    resp = RedirectResponse(url=redirect_url, status_code=302)
    resp.set_cookie("access_token", access, httponly=True, secure=True, samesite="lax", max_age=3600, path="/")
    return resp

@router.post("/logout")
async def logout(request: Request):
    session_cookie_name = getattr(settings, "SESSION_COOKIE_NAME", "ts_session")
    cookie_domain = getattr(settings, "SESSION_COOKIE_DOMAIN", None)
    cookie_path = "/"

    request.session.clear()
    # Instead of returning JSON, we return a redirect to the login page.
    # The frontend URL needs to be known or configured.
    # Assuming it's configured in settings.CORS_ORIGINS
    origins = (settings.CORS_ORIGINS or "").split(",")
    frontend_url = origins[0] if origins else "/"
    response = RedirectResponse(url=f"{frontend_url}/login", status_code=303) # 303 See Other is appropriate for POST->GET redirect
    
    response.delete_cookie("access_token", path=cookie_path, domain=cookie_domain)
    response.delete_cookie(session_cookie_name, path=cookie_path, domain=cookie_domain)
    
    return response

class CurrentUser(BaseModel):
    email: str
    full_name: str | None = None
    picture: str | None = None