from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import Integer, String, Boolean, DateTime, ForeignKey, Float, Date
from datetime import datetime, date
from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey, Numeric, func, Index, UniqueConstraint, text

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    wage: Mapped[float | None] = mapped_column(Numeric(10, 2, asdecimal=False), nullable=True)
    is_calculator_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    employment_type: Mapped[str] = mapped_column(String(32), default="employed") # "employed" or "self_employed"
    guild_tax: Mapped[float | None] = mapped_column(Numeric(10, 2, asdecimal=False), nullable=True)
    has_payslip: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Automatic upload settings
    is_auto_upload_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_upload_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    auto_upload_folder: Mapped[str | None] = mapped_column(String(255), nullable=True)
    auto_upload_company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    auto_upload_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    auto_upload_app_password: Mapped[str | None] = mapped_column(String(512), nullable=True)
    pdf_password: Mapped[str | None] = mapped_column(String(512), nullable=True)
    @property
    def hourly_rate(self) -> float | None:
        return self.wage

    @hourly_rate.setter
    def hourly_rate(self, value: float | None) -> None:
        self.wage = value
    role: Mapped[str] = mapped_column(String(32), default="user")
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
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
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
    __table_args__ = (Index("ix_time_entries_created_by_date", "created_by", "date"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    project_name: Mapped[str] = mapped_column(String(255))
    date: Mapped[datetime | Date] = mapped_column(Date)  # yyyy-mm-dd
    hours_worked: Mapped[float] = mapped_column(Float, default=0.0)
    travel_time: Mapped[float] = mapped_column(Float, default=0.0)
    hotel_id: Mapped[int | None] = mapped_column(ForeignKey("hotels.id", ondelete="SET NULL"), nullable=True)
    hotel_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
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
    id = Column(Integer, primary_key=True)
    created_by = Column(String, index=True, nullable=False)
    receipt_id = Column(Integer, ForeignKey("receipts.id"), nullable=True)
    time_entry_id = Column(Integer, ForeignKey("time_entries.id"), nullable=True)
    entry_date = Column(Date, index=True, nullable=False)
    vendor = Column(String, nullable=True)
    expense_type = Column(String, nullable=True)
    total_amount = Column(Numeric(10, 2), nullable=True)
    currency = Column(String(3), nullable=True, default="GBP")
    created_date = Column(DateTime, server_default=func.now(), nullable=False)



class PayrollProfile(Base):
    __tablename__ = "payroll_profiles"
    id = Column(Integer, primary_key=True)
    created_by = Column(String, unique=True, index=True, nullable=False)  # user email
    tax_code = Column(String, nullable=True)

    created_date = Column(DateTime, server_default=func.now(), nullable=False)
    updated_date = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

class WeeklyEarnings(Base):
    __tablename__ = "weekly_earnings"
    __table_args__ = (UniqueConstraint("created_by", "week_start", name="uq_weekly_earnings_user_week"),)
    id = Column(Integer, primary_key=True)
    created_by = Column(String, index=True, nullable=False)
    week_start = Column(Date, index=True, nullable=False)
    gross_pay = Column(Numeric(10,2), nullable=True)
    paye_tax = Column(Numeric(10,2), nullable=True)
    national_insurance = Column(Numeric(10,2), nullable=True)
    pension = Column(Numeric(10,2), nullable=True)
    net_pay = Column(Numeric(10,2), nullable=True)
    hourly_wage: Mapped[float | None] = mapped_column(Numeric(10, 2, asdecimal=False), nullable=True)
    employment_type: Mapped[str] = mapped_column(String(32), default="employed")
    guild_tax: Mapped[float | None] = mapped_column(Numeric(10, 2, asdecimal=False), nullable=True)
    is_manual_wage: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

class PayslipFile(Base):
    __tablename__ = "payslip_files"
    # One payslip/P60 per user, tax year and week; "document" rows (letters, policies...) are exempt
    __table_args__ = (
        Index("uq_payslip_files_user_year_week", "created_by", "tax_year", "tax_week",
              unique=True, postgresql_where=text("doc_type <> 'document'")),
    )
    id = Column(Integer, primary_key=True)
    created_by = Column(String, index=True, nullable=False)
    file_path = Column(String, nullable=False)
    filename = Column(String, nullable=False) # e.g. 25-26_50.pdf
    doc_type = Column(String(16), nullable=False, default="payslip", server_default="payslip") # "payslip" (incl. P60 = week 0) or "document"
    tax_year = Column(String(10), nullable=False) # e.g. 25-26
    tax_week = Column(Integer, nullable=False)
    process_date = Column(Date, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    
    gross_pay = Column(Numeric(10, 2), nullable=True)
    paye_tax = Column(Numeric(10, 2), nullable=True)
    national_insurance = Column(Numeric(10, 2), nullable=True)
    pension = Column(Numeric(10, 2), nullable=True)
    net_pay = Column(Numeric(10, 2), nullable=True)
    tax_code = Column(String(32), nullable=True)
    tax_period = Column(Integer, nullable=True)
    ytd_gross = Column(Numeric(10, 2), nullable=True)
    ytd_tax = Column(Numeric(10, 2), nullable=True)
    ytd_ni = Column(Numeric(10, 2), nullable=True)
    deductions_total = Column(Numeric(10, 2), nullable=True)

class Training(Base):
    __tablename__ = "trainings"
    id = Column(Integer, primary_key=True)
    created_by = Column(String, index=True, nullable=False)
    name = Column(String, nullable=False)
    expiry_date = Column(Date, nullable=True)
    file_path = Column(String, nullable=False)
    filename = Column(String, nullable=False)
    mime_type = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

class Note(Base):
    __tablename__ = "notes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_by: Mapped[str] = mapped_column(String(255), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    content: Mapped[str] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class RevokedToken(Base):
    """JWT IDs invalidated by logout; rows can be dropped once the token would have expired anyway."""
    __tablename__ = "revoked_tokens"
    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)

class SystemSetting(Base):
    __tablename__ = "system_settings"
    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), nullable=False)

class Holiday(Base):
    __tablename__ = "holidays"
    __table_args__ = (UniqueConstraint("created_by", "date", name="uq_holidays_user_date"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_by: Mapped[str] = mapped_column(String(255), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    type: Mapped[str] = mapped_column(String(32), default="paid") # "paid" or "unpaid"
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class ConstructionDetail(Base):
    __tablename__ = "construction_details"
    id = Column(Integer, primary_key=True)
    created_by = Column(String(255), index=True, nullable=False)
    name = Column(String(255), nullable=False)
    manufacturer = Column(String(255), index=True, nullable=False)
    details = Column(String(2000), nullable=True)
    file_path = Column(String, nullable=False)
    filename = Column(String, nullable=False)
    mime_type = Column(String, nullable=True)
    size_bytes = Column(Integer, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=datetime.utcnow, nullable=False)

