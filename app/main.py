from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from .config import cors_origins_list, settings
from .db import engine
from .models import Base

from .routers.auth_google import router as google_auth_router
from .routers.me import router as me_router
from .routers.projects import router as projects_router
from .routers.hotels import router as hotels_router
from .routers.time_entries import router as time_entries_router

app = FastAPI(title="Timesheet API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Session for OAuth state
app.add_middleware(SessionMiddleware, secret_key=settings.JWT_SECRET)

@app.on_event("startup")
async def on_startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# Routers
app.include_router(google_auth_router)
app.include_router(me_router)
app.include_router(projects_router)
app.include_router(hotels_router)
app.include_router(time_entries_router)
