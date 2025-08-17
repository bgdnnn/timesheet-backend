from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert, update, delete
from ..db import get_session
from ..auth import get_current_user
from ..schemas import ProjectIn, ProjectOut
from ..models import Project
from .helpers import apply_sort

router = APIRouter(prefix="/projects", tags=["projects"])

@router.get("", response_model=list[ProjectOut])
async def list_projects(
    sort: str | None = None,
    created_by: str | None = None,  # ignored for security; ownership enforced
    session: AsyncSession = Depends(get_session),
    current=Depends(get_current_user),
):
    stmt = select(Project).where(Project.owner_user_id == current.id)
    stmt = apply_sort(stmt, Project, sort or "-created_at")
    rows = (await session.execute(stmt)).scalars().all()
    # Map date aliases
    for r in rows:
        r.created_date = r.created_at
        r.updated_date = r.updated_at
    return rows

@router.post("", response_model=ProjectOut)
async def create_project(
    payload: ProjectIn,
    session: AsyncSession = Depends(get_session),
    current=Depends(get_current_user),
):
    res = await session.execute(
        insert(Project).values(
            name=payload.name,
            client=payload.client,
            contract=payload.contract or "",
            default_hours_worked=payload.default_hours_worked,
            default_travel_time=payload.default_travel_time,
            owner_user_id=current.id,
            created_by=current.email,
        ).returning(Project)
    )
    proj = res.scalar_one()
    await session.commit()
    proj.created_date = proj.created_at
    proj.updated_date = proj.updated_at
    return proj

@router.patch("/{pid}", response_model=ProjectOut)
async def update_project(
    pid: int,
    payload: ProjectIn,
    session: AsyncSession = Depends(get_session),
    current=Depends(get_current_user),
):
    # Only allow owner
    res = await session.execute(select(Project).where(Project.id == pid, Project.owner_user_id == current.id))
    proj = res.scalar_one()
    await session.execute(
        update(Project).where(Project.id == pid).values(
            name=payload.name,
            client=payload.client,
            contract=payload.contract or "",
            default_hours_worked=payload.default_hours_worked,
            default_travel_time=payload.default_travel_time,
        )
    )
    await session.commit()
    return (await session.execute(select(Project).where(Project.id == pid))).scalar_one()

@router.delete("/{pid}")
async def delete_project(
    pid: int,
    session: AsyncSession = Depends(get_session),
    current=Depends(get_current_user),
):
    await session.execute(delete(Project).where(Project.id == pid, Project.owner_user_id == current.id))
    await session.commit()
    return {"status": "ok"}
