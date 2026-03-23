from pydantic import BaseModel, EmailStr, field_validator
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
    is_calculator_enabled: bool = True
    employment_type: str = "employed"
    guild_tax: Optional[float] = None
    has_payslip: bool = False
    role: str
    created_date: datetime | None = None
    updated_date: datetime | None = None
    class Config: from_attributes = True

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    company: Optional[str] = None
    wage: Optional[float] = None
    is_calculator_enabled: Optional[bool] = None
    employment_type: Optional[str] = None
    guild_tax: Optional[float] = None

class AdminUserUpdate(BaseModel):
    full_name: Optional[str] = None
    company: Optional[str] = None
    wage: Optional[float] = None
    is_calculator_enabled: Optional[bool] = None
    employment_type: Optional[str] = None
    guild_tax: Optional[float] = None
    role: Optional[str] = None

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

class ExpenseIn(BaseModel):
    entry_date: date
    vendor: Optional[str] = None
    expense_type: Optional[str] = None
    total_amount: Decimal
    receipt_id: Optional[int] = None

class ExpenseOut(BaseModel):
    id: int
    receipt_id: int | None
    receipt_filename: Optional[str] = None
    time_entry_id: int | None
    entry_date: date
    vendor: str | None
    expense_type: str | None
    total_amount: Decimal | None
    currency: str | None
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
    hourly_wage: Decimal | None
    tax_week: Optional[int] = None
    employment_type: str = "employed"
    guild_tax: Decimal | None = None
    is_manual_wage: bool = False
    created_at: datetime
    class Config: from_attributes = True

class PayslipFileOut(BaseModel):
    id: int
    filename: str
    tax_year: str
    tax_week: int
    process_date: date
    created_at: datetime
    class Config: from_attributes = True

class TrainingOut(BaseModel):
    id: int
    name: str
    expiry_date: date
    filename: str
    mime_type: str
    created_at: datetime
    class Config: from_attributes = True

class TrainingUpdate(BaseModel):
    name: Optional[str] = None
    expiry_date: Optional[date] = None

class ManualPayslipIn(BaseModel):
    tax_code: str = ""
    total_gross_pay: Decimal = Decimal("0")
    gross_for_tax: Decimal = Decimal("0")
    paye_tax: Decimal = Decimal("0")
    national_insurance: Decimal = Decimal("0")
    pension: Decimal = Decimal("0")
    tax_period: int = 1
    ytd_gross: Decimal = Decimal("0")
    ytd_tax: Decimal = Decimal("0")
    ytd_ni: Decimal = Decimal("0")
    calculated_net_pay: Decimal = Decimal("0")
    deductions_total: Decimal = Decimal("0")
    process_date: Optional[str] = None

    @field_validator("process_date")
    @classmethod
    def validate_process_date(cls, v):
        if v is None:
            return v
        try:
            datetime.strptime(v, "%d/%m/%Y")
        except ValueError:
            raise ValueError("Process date must be in DD/MM/YYYY format")
        return v
