from pydantic import BaseModel, EmailStr
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel
from decimal import Decimal
from datetime import date, datetime

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
    full_name: Optional[str] = None
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

class ReceiptOut(BaseModel):
    id: int
    time_entry_id: int | None
    entry_date: date
    original_filename: str | None
    mime_type: str | None
    size_bytes: int | None
    created_date: datetime
    class Config: from_attributes = True

class ExpenseOut(BaseModel):
    id: int
    receipt_id: int
    time_entry_id: int | None
    entry_date: date
    vendor_name: str | None
    total_amount: Decimal | None
    currency: str | None
    status: str
    created_date: datetime
    class Config: from_attributes = True

class ExpenseDailyOut(BaseModel):
    date: date
    count: int
    total: Decimal | None

class ExpenseGroupOut(BaseModel):
    bucket: str
    count: int
    total: Decimal | None



class PayrollProfileOut(BaseModel):
    created_by: str
    username: str | None
    tax_code: str | None
    ni_number: str | None
    region: str
    pension_employee_percent: Decimal | None
    baseline_gross: Decimal | None
    baseline_paye: Decimal | None
    baseline_ni: Decimal | None
    baseline_pension: Decimal | None
    baseline_net: Decimal | None
    tax_offset: Decimal
    ni_offset: Decimal
    created_date: datetime
    updated_date: datetime
    class Config: from_attributes = True

class WeeklyEarningsOut(BaseModel):
    id: int
    week_start: date
    gross_pay: Decimal | None
    paye_tax: Decimal | None
    national_insurance: Decimal | None
    pension: Decimal | None
    net_pay: Decimal | None
    created_at: datetime
    class Config: from_attributes = True