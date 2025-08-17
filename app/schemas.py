from pydantic import BaseModel, EmailStr
from datetime import date, datetime
from typing import Optional

class UserOut(BaseModel):
    id: int
    email: EmailStr
    full_name: Optional[str] = None
    company: Optional[str] = None
    wage: Optional[float] = None
    role: str
    created_date: datetime | None = None
    updated_date: datetime | None = None
    class Config: from_attributes = True

class UserUpdate(BaseModel):
    company: Optional[str] = None
    wage: Optional[float] = None

class ProjectIn(BaseModel):
    name: str
    client: str
    contract: Optional[str] = ""
    default_hours_worked: float = 8.0
    default_travel_time: float = 0.0

class ProjectOut(ProjectIn):
    id: int
    archived: bool = False
    created_by: str
    created_date: datetime | None = None
    updated_date: datetime | None = None
    class Config: from_attributes = True

class HotelIn(BaseModel):
    name: str
    address: Optional[str] = ""

class HotelOut(HotelIn):
    id: int
    created_by: str
    created_date: datetime | None = None
    updated_date: datetime | None = None
    class Config: from_attributes = True

class TimeEntryIn(BaseModel):
    date: date
    project_id: int
    project_name: str
    hours_worked: float = 0.0
    travel_time: float = 0.0
    hotel_id: Optional[int] = None
    hotel_name: Optional[str] = None
    notes: Optional[str] = None

class TimeEntryOut(TimeEntryIn):
    id: int
    user_id: int
    duration_minutes: int
    created_by: str
    created_date: datetime | None = None
    updated_date: datetime | None = None
    class Config: from_attributes = True
