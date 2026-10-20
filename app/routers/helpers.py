from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.sql import Select

def apply_sort(stmt: Select, model, sort: str | None):
    if not sort:
        return stmt
    field = sort
    desc = False
    if sort.startswith("-"):
        desc = True
        field = sort[1:]
    # Only real table columns; anything else is ignored rather than passed to getattr
    if field in model.__table__.columns:
        col = getattr(model, field)
        stmt = stmt.order_by(col.desc() if desc else col.asc())
    return stmt

async def ensure_owned(session, model, obj_id: int | None, owner_clause, label: str):
    """Reject references (project_id, receipt_id, ...) to rows that belong to another user."""
    if obj_id is None:
        return
    found = (await session.execute(select(model.id).where(model.id == obj_id, owner_clause))).first()
    if not found:
        raise HTTPException(404, f"{label} not found")
