from sqlalchemy.sql import Select
from sqlalchemy.orm import InstrumentedAttribute

def apply_sort(stmt: Select, model, sort: str | None):
    if not sort:
        return stmt
    field = sort
    desc = False
    if sort.startswith("-"):
        desc = True
        field = sort[1:]
    col: InstrumentedAttribute = getattr(model, field, None)
    if not col is None:
        stmt = stmt.order_by(col.desc() if desc else col.asc())
    return stmt
