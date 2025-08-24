from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import Integer, String, Boolean, DateTime, ForeignKey, Float, Date
from datetime import datetime
from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey, Numeric, func

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    wage: Mapped[float | None] = mapped_column(Float, nullable=True)
    @property
    def hourly_rate(self) -> float | None:
        return self.wage

    @hourly_rate.setter
    def hourly_rate(self, value: float | None) -> None:
        self.wage = value
    role: Mapped[str] = mapped_column(String(32), default="user")
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)  # optional local login
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    client: Mapped[str] = mapped_column(String(255))
    contract: Mapped[str | None] = mapped_column(String(255), nullable=True)
    default_hours_worked: Mapped[float] = mapped_column(Float, default=8.0)
    default_travel_time: Mapped[float] = mapped_column(Float, default=0.0)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_by: Mapped[str] = mapped_column(String(255))  # store email snapshot
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Hotel(Base):
    __tablename__ = "hotels"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class TimeEntry(Base):
    __tablename__ = "time_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    project_name: Mapped[str] = mapped_column(String(255))
    date: Mapped[datetime | Date] = mapped_column(Date)  # yyyy-mm-dd
    hours_worked: Mapped[float] = mapped_column(Float, default=0.0)
    travel_time: Mapped[float] = mapped_column(Float, default=0.0)
    hotel_id: Mapped[int | None] = mapped_column(ForeignKey("hotels.id"), nullable=True)
    hotel_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=0)  # computed
    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Receipt(Base):
    __tablename__ = "receipts"
    id = Column(Integer, primary_key=True)
    created_by = Column(String, index=True, nullable=False)
    time_entry_id = Column(Integer, ForeignKey("time_entries.id"), nullable=True)
    entry_date = Column(Date, index=True, nullable=False)
    file_path = Column(String, nullable=False)
    original_filename = Column(String, nullable=True)
    mime_type = Column(String, nullable=True)
    size_bytes = Column(Integer, nullable=True)
    created_date = Column(DateTime, server_default=func.now(), nullable=False)

class Expense(Base):
    __tablename__ = "expenses"
    id = Column(Integer, primary_key=True, index=True)
    created_by = Column(String, index=True, nullable=False)
    receipt_id = Column(Integer, ForeignKey("receipts.id"), nullable=False)
    time_entry_id = Column(Integer, ForeignKey("time_entries.id"), nullable=True)
    entry_date = Column(Date, index=True, nullable=False)
    vendor_name = Column(String, nullable=True)
    total_amount = Column(Numeric(10, 2), nullable=True)
    currency = Column(String(3), nullable=True, default="GBP")
    status = Column(String(20), nullable=False, default="parsed")  # parsed|needs_review
    raw_text = Column(String, nullable=True)
    created_date = Column(DateTime, server_default=func.now(), nullable=False)



class PayrollProfile(Base):
    __tablename__ = "payroll_profiles"
    id = Column(Integer, primary_key=True)
    created_by = Column(String, unique=True, index=True, nullable=False)  # user email
    username = Column(String, index=True, nullable=True)

    tax_code = Column(String, nullable=True)
    ni_number = Column(String, nullable=True)
    region = Column(String, nullable=False, default="rUK")
    pension_employee_percent = Column(Numeric(5,4), nullable=True)  # 0.0500 -> 5%

    baseline_gross = Column(Numeric(10,2), nullable=True)
    baseline_paye = Column(Numeric(10,2), nullable=True)
    baseline_ni = Column(Numeric(10,2), nullable=True)
    baseline_pension = Column(Numeric(10,2), nullable=True)
    baseline_net = Column(Numeric(10,2), nullable=True)

    ytd_gross = Column(Numeric(10,2), nullable=True)
    ytd_tax = Column(Numeric(10,2), nullable=True)
    ytd_ni = Column(Numeric(10,2), nullable=True)
    ytd_pension = Column(Numeric(10,2), nullable=True)

    # offsets to align calc with payslip
    tax_offset = Column(Numeric(10,2), nullable=False, default=0)
    ni_offset = Column(Numeric(10,2), nullable=False, default=0)

    created_date = Column(DateTime, server_default=func.now(), nullable=False)
    updated_date = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

class WeeklyEarnings(Base):
    __tablename__ = "weekly_earnings"
    id = Column(Integer, primary_key=True)
    created_by = Column(String, index=True, nullable=False)
    week_start = Column(Date, index=True, nullable=False)
    gross_pay = Column(Numeric(10,2), nullable=True)
    paye_tax = Column(Numeric(10,2), nullable=True)
    national_insurance = Column(Numeric(10,2), nullable=True)
    pension = Column(Numeric(10,2), nullable=True)
    net_pay = Column(Numeric(10,2), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)