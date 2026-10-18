# app/routers/auth_google.py
from fastapi import APIRouter, Request, HTTPException, Depends, BackgroundTasks
from fastapi.responses import RedirectResponse, JSONResponse
from authlib.integrations.starlette_client import OAuth
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert, update, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from datetime import datetime
import jwt
from ..config import settings
from ..db import get_session
from ..models import User, SystemSetting, RevokedToken
from ..auth import make_token, get_request_token, decode_token
from pydantic import BaseModel
import secrets, time
from urllib.parse import urlsplit, urlunsplit

router = APIRouter(prefix="/auth", tags=["auth"])

oauth = OAuth()
oauth.register(
    name="google",
    client_id=settings.GOOGLE_CLIENT_ID,
    client_secret=settings.GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

ALLOWED_RETURN_HOSTS = {"timesheet.home-clouds.com", "www.timesheet.home-clouds.com"}

def safe_return_path(return_to: str | None) -> str:
    """Reduce returnTo to a local path so the post-login redirect can't leave the frontend."""
    if not return_to:
        return "/"
    parts = urlsplit(return_to)
    if parts.scheme or parts.netloc:
        if parts.scheme != "https" or parts.netloc not in ALLOWED_RETURN_HOSTS:
            return "/"
        return_to = urlunsplit(("", "", parts.path or "/", parts.query, parts.fragment))
    if not return_to.startswith("/") or return_to.startswith("//") or "\\" in return_to:
        return "/"
    return return_to

@router.get("/google/login")
async def google_login(request: Request, returnTo: str | None = None, action: str | None = "login"):
    # ensure the session is definitely mutated so cookie is set on this 302
    request.session["oauth_return_to"] = safe_return_path(returnTo)
    request.session["oauth_action"] = action or "login"
    request.session["oauth_touch"] = time.time()  # guaranteed write

    # (optional) manually set state for extra robustness
    state = secrets.token_urlsafe(32)
    request.session["oauth_google_state"] = state

    redirect_uri = settings.OAUTH_REDIRECT_URI
    return await oauth.google.authorize_redirect(request, redirect_uri, state=state, prompt="select_account")

async def run_auto_upload_in_background(email: str):
    import asyncio
    import sys
    python_bin = sys.executable or "/srv/timesheet-backend/.venv/bin/python3"
    script_path = "/srv/timesheet-backend/scripts/download_payslips.py"
    try:
        proc = await asyncio.create_subprocess_exec(
            python_bin,
            script_path,
            "--email",
            email,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()
    except Exception as e:
        print(f"Background auto-upload run failed for {email}: {e}")

@router.get("/google/callback")
async def google_callback(
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session)
):
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

    action = request.session.pop("oauth_action", "login")

    # Upsert user
    user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if not user:
        # Check system settings for signups
        setting = (await session.execute(select(SystemSetting).where(SystemSetting.key == "signup_enabled"))).scalar_one_or_none()
        signup_enabled = setting.value.lower() == "true" if setting else True
        if not signup_enabled:
            frontend_url = "https://timesheet.home-clouds.com/login?error=signups_closed"
            response = RedirectResponse(url=frontend_url, status_code=302)
            return response

        if action == "login":
            frontend_url = "https://timesheet.home-clouds.com/login?error=account_not_found"
            response = RedirectResponse(url=frontend_url, status_code=302)
            return response

        await session.execute(insert(User).values(email=email, full_name=full_name, role="user"))
    else:
        await session.execute(update(User).where(User.id == user.id).values(full_name=full_name))
    await session.commit()

    user = (await session.execute(select(User).where(User.email == email))).scalar_one()

    # Trigger background checks for missing payslip of current tax week if auto-upload is enabled
    if user.is_auto_upload_enabled and user.auto_upload_email and user.auto_upload_app_password:
        from datetime import date
        from ..models import PayslipFile
        
        today = date.today()
        tax_start = date(today.year, 4, 6)
        if today < tax_start:
            tax_start = date(today.year - 1, 4, 6)
        delta = today - tax_start
        current_week = (delta.days // 7) + 1
        
        if today.month < 4 or (today.month == 4 and today.day < 6):
            start_y, end_y = today.year - 1, today.year
        else:
            start_y, end_y = today.year, today.year + 1
        current_year_str = f"{str(start_y)[2:]}-{str(end_y)[2:]}"
        
        q_file = select(PayslipFile).where(
            PayslipFile.created_by == user.email,
            PayslipFile.tax_year == current_year_str,
            PayslipFile.tax_week == current_week
        )
        res_file = await session.execute(q_file)
        if res_file.scalars().first() is None:
            background_tasks.add_task(run_auto_upload_in_background, user.email)

    access = make_token({"sub": str(user.id)}, minutes=settings.ACCESS_TOKEN_MINUTES)
    return_to = safe_return_path(request.session.pop("oauth_return_to", "/"))

    # Set the token in a secure, HTTP-only cookie
    import time
    t_val = int(time.time())
    sep = "&" if "?" in (return_to or "/") else "?"
    frontend_url = f"https://timesheet.home-clouds.com{return_to or '/'}{sep}t={t_val}"
    response = RedirectResponse(url=frontend_url, status_code=302)
    response.set_cookie(
        "access_token",
        access,
        httponly=True,
        secure=True,
        samesite="lax",  # Changed to lax for same-site subdomains
        max_age=settings.ACCESS_TOKEN_MINUTES * 60,
        path="/",
        domain=settings.SESSION_COOKIE_DOMAIN, # Added domain
    )
    # Also set readable expiration timestamp cookie for instant client-side detection
    exp_ts = t_val + (settings.ACCESS_TOKEN_MINUTES * 60)
    response.set_cookie(
        "ts_session_exp",
        str(exp_ts),
        httponly=False,
        secure=True,
        samesite="lax",
        max_age=settings.ACCESS_TOKEN_MINUTES * 60,
        path="/",
        domain=settings.SESSION_COOKIE_DOMAIN,
    )
    return response

@router.post("/logout")
async def logout(request: Request, session: AsyncSession = Depends(get_session)):
    session_cookie_name = getattr(settings, "SESSION_COOKIE_NAME", "ts_session")
    cookie_domain = getattr(settings, "SESSION_COOKIE_DOMAIN", None)
    cookie_path = "/"

    # Revoke the token server-side so a copied token stops working too
    token = get_request_token(request)
    if token:
        try:
            payload = decode_token(token)
        except jwt.PyJWTError:
            payload = None
        if payload:
            now = datetime.utcnow()
            await session.execute(delete(RevokedToken).where(RevokedToken.expires_at < now))
            await session.execute(
                pg_insert(RevokedToken)
                .values(jti=payload["jti"], expires_at=datetime.utcfromtimestamp(payload["exp"]))
                .on_conflict_do_nothing()
            )
            await session.commit()

    request.session.clear()
    
    response = JSONResponse(content={"ok": True, "message": "Logged out successfully"})
    # Delete access_token with both lax and none to match setting environment
    response.delete_cookie("access_token", path=cookie_path, domain=cookie_domain, secure=True, httponly=True, samesite="lax")
    response.delete_cookie("access_token", path=cookie_path, domain=cookie_domain, secure=True, httponly=True, samesite="none")
    # Delete ts_session_exp cookie
    response.delete_cookie("ts_session_exp", path=cookie_path, domain=cookie_domain, secure=True, httponly=False, samesite="lax")
    response.delete_cookie("ts_session_exp", path=cookie_path, domain=cookie_domain, secure=True, httponly=False, samesite="none")
    # Delete session cookie with both lax and none
    response.delete_cookie(session_cookie_name, path=cookie_path, domain=cookie_domain, secure=True, httponly=True, samesite="lax")
    response.delete_cookie(session_cookie_name, path=cookie_path, domain=cookie_domain, secure=True, httponly=True, samesite="none")
    
    return response

class CurrentUser(BaseModel):
    email: str
    full_name: str | None = None
    picture: str | None = None

@router.get("/signup-enabled")
async def is_signup_enabled_endpoint(session: AsyncSession = Depends(get_session)):
    setting = (await session.execute(select(SystemSetting).where(SystemSetting.key == "signup_enabled"))).scalar_one_or_none()
    if not setting:
        return {"signup_enabled": True}
    return {"signup_enabled": setting.value.lower() == "true"}