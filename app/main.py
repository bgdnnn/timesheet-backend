# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from .config import settings
from .routers import auth_google
from .routers import receipts
from .routers import payslips
from .routers import me, earnings, payslip_parser_endpoint, expenses, admin

# If you also have these routers, leave them; otherwise comment them out.
from .routers import projects, hotels, time_entries
from .db_utils import create_tables

def cors_origins_list():
    raw = (settings.CORS_ORIGINS or "").strip()
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]

app = FastAPI(title="Timesheet API")

@app.on_event("startup")
async def on_startup():
    await create_tables()

# Order matters: CORS first (outermost), then Session.
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.JWT_SECRET,
    session_cookie=getattr(settings, "SESSION_COOKIE_NAME", "ts_session"),
    same_site=getattr(settings, "SESSION_SAMESITE", "lax"),
    https_only=getattr(settings, "SESSION_HTTPS_ONLY", True),
    domain=getattr(settings, "SESSION_COOKIE_DOMAIN", None),
)

# Routers
app.include_router(auth_google.router)
app.include_router(me.router)
app.include_router(earnings.router)
app.include_router(payslip_parser_endpoint.router)
app.include_router(payslips.router)
app.include_router(receipts.router)
app.include_router(expenses.router)

# Optional, if present
app.include_router(projects.router)
app.include_router(hotels.router)
app.include_router(time_entries.router)
app.include_router(admin.router)

@app.get("/healthz")
async def healthz():
    return {"ok": True}
