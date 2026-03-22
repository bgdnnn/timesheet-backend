from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, update
from datetime import date, timedelta, datetime
import json
from pathlib import Path

from ..models import WeeklyEarnings, TimeEntry, User, PayrollProfile
from ..db import AsyncSessionLocal
from ..lib.uk_tax import calc_income_tax_annual, calc_employee_ni_period, D, UkTaxConfig
from ..utils.tax_year import get_tax_year_start_date, tax_period_to_date
from ..utils.users import user_slug_from_identity
from ..config import settings
from ..utils.dates import week_monday
from ..services.payroll import get_profile


async def recalculate_all_earnings(user_obj: User):
    async with AsyncSessionLocal() as session:
        # Refresh user from DB to get latest employment_type/wage/guild_tax
        q_user = select(User).where(User.email == user_obj.email)
        user = (await session.execute(q_user)).scalars().first()
        if not user:
            return

        # Fetch all existing weekly earnings BEFORE clearing them, to preserve historical hourly_wage
        all_existing_weekly_earnings_query = select(WeeklyEarnings).where(
            WeeklyEarnings.created_by == user.email
        )
        all_existing_weekly_earnings = (await session.execute(all_existing_weekly_earnings_query)).scalars().all()
        # Create map including both the wage and the manual flag
        existing_we_map = {we.week_start: {"wage": we.hourly_wage, "manual": we.is_manual_wage} for we in all_existing_weekly_earnings}

        # Clear all existing weekly earnings for the user first
        await session.execute(delete(WeeklyEarnings).where(WeeklyEarnings.created_by == user.email))
        await session.flush()  # Ensure the delete is processed before we add new rows

        # 1. Get user's profile
        profile = await get_profile(session, user)
        if not profile and user.employment_type == "employed":
            return

        # 2. Get the payslip date anchor
        safe_user = user_slug_from_identity(user)
        json_path = Path(settings.MEDIA_ROOT) / safe_user / "payslip.json"
        
        payslip_week_start = None
        payslip_data = {}
        if json_path.exists():
            with open(json_path, "r") as f:
                payslip_data = json.load(f)
            
            process_date_str = payslip_data.get("process_date")
            tax_period = payslip_data.get("tax_period")
            
            if process_date_str:
                try:
                    process_date = datetime.strptime(process_date_str, "%d/%m/%Y").date()
                    payslip_week_start = week_monday(process_date - timedelta(weeks=2))
                except (ValueError, TypeError):
                    pass

            if payslip_week_start is None and tax_period:
                today = date.today()
                tax_year = today.year
                if today.month < 4 or (today.month == 4 and today.day < 6):
                    tax_year -= 1
                
                try:
                    payslip_date_from_period = tax_period_to_date(tax_year, int(tax_period))
                    payslip_week_start = week_monday(payslip_date_from_period - timedelta(weeks=2))
                except (ValueError, TypeError):
                    pass

        # 3. Anchor week (Only if employed)
        if payslip_week_start and user.employment_type == "employed" and profile:
            # Preservation logic
            hourly_wage_for_payslip_week = D(user.wage or 0)
            is_manual = False
            if payslip_week_start in existing_we_map:
                if existing_we_map[payslip_week_start]["wage"] is not None:
                    hourly_wage_for_payslip_week = D(existing_we_map[payslip_week_start]["wage"])
                is_manual = existing_we_map[payslip_week_start]["manual"]

            payslip_week_earnings = WeeklyEarnings(
                created_by=user.email,
                week_start=payslip_week_start,
                gross_pay=profile.baseline_gross,
                paye_tax=profile.baseline_paye,
                national_insurance=profile.baseline_ni,
                pension=profile.baseline_pension,
                net_pay=profile.baseline_net,
                hourly_wage=float(hourly_wage_for_payslip_week),
                is_manual_wage=is_manual,
                employment_type="employed"
            )
            session.add(payslip_week_earnings)

        # 4. Calculation Loop
        today = date.today()
        current_week_start = week_monday(today)
        tax_year_start = get_tax_year_start_date(today)
        
        q_te = select(TimeEntry).where(
            TimeEntry.created_by == user.email,
            TimeEntry.date >= tax_year_start
        ).order_by(TimeEntry.date)
        time_entries = (await session.execute(q_te)).scalars().all()

        entries_by_week = {}
        for entry in time_entries:
            ws = week_monday(entry.date)
            if ws not in entries_by_week:
                entries_by_week[ws] = []
            entries_by_week[ws].append(entry)

        pension_rate = D("0.05") # 5% per user instruction
        effective_tax_rate_employed = D("0.20")
        if profile and profile.baseline_gross > 0:
            effective_tax_rate_employed = profile.baseline_paye / profile.baseline_gross

        ytd_gross = D(payslip_data.get("ytd_gross") or 0) if payslip_week_start else D(0)
        ytd_tax = D(payslip_data.get("ytd_tax") or 0) if payslip_week_start else D(0)
        ytd_ni = D(payslip_data.get("ytd_ni") or 0) if payslip_week_start else D(0)
        ytd_pension = D(payslip_data.get("ytd_pension") or 0) if payslip_week_start else D(0)

        week = week_monday(tax_year_start)
        while week <= current_week_start:
            if week == payslip_week_start and user.employment_type == "employed":
                week += timedelta(weeks=1)
                continue

            weekly_entries = entries_by_week.get(week, [])
            if not weekly_entries:
                week += timedelta(weeks=1)
                continue

            # PRESERVATION: Use existing week's wage if it exists
            hourly_rate = D(user.wage or 0)
            is_manual = False
            if week in existing_we_map:
                if existing_we_map[week]["wage"] is not None:
                    hourly_rate = D(existing_we_map[week]["wage"])
                is_manual = existing_we_map[week]["manual"]
            
            if not hourly_rate:
                week += timedelta(weeks=1)
                continue

            gross_pay = sum((D(str(e.hours_worked or 0)) + D(str(e.travel_time or 0))) * hourly_rate for e in weekly_entries)
            
            tax = D(0)
            ni = D(0)
            pension = D(0)
            guild_tax = D(0)
            net_pay = D(0)

            if user.employment_type == "self_employed":
                tax = (gross_pay * D("0.20")).quantize(D("0.01"))
                guild_tax = D(str(user.guild_tax or 0)).quantize(D("0.01"))
                net_pay = gross_pay - tax - guild_tax
            else:
                # NEW Pension Logic: 5% between 120 and 967
                pensionable_earnings = max(D(0), min(gross_pay, D("967")) - D("120"))
                pension = (pensionable_earnings * pension_rate).quantize(D("0.01"))

                if week > (payslip_week_start or date(2000,1,1)):
                    # Forward calc
                    taxable_pay = gross_pay - pension
                    annualized_taxable = taxable_pay * 52
                    cfg_tax = UkTaxConfig(tax_code=profile.tax_code if profile else "1257L")
                    annual_tax = calc_income_tax_annual(annualized_taxable, cfg_tax)
                    tax = (annual_tax / 52).quantize(D("0.01"))
                    cfg_ni = UkTaxConfig()
                    ni = calc_employee_ni_period(taxable_pay, "weekly", cfg_ni)
                else:
                    # Historical calc
                    tax = (gross_pay * effective_tax_rate_employed).quantize(D("0.01"))
                    taxable_for_ni = gross_pay - pension
                    ni = calc_employee_ni_period(taxable_for_ni, "weekly", UkTaxConfig())
                
                net_pay = gross_pay - tax - ni - pension

            new_we = WeeklyEarnings(
                created_by=user.email,
                week_start=week,
                gross_pay=gross_pay,
                paye_tax=tax,
                national_insurance=ni,
                pension=pension,
                net_pay=net_pay,
                hourly_wage=float(hourly_rate),
                is_manual_wage=is_manual,
                employment_type=user.employment_type,
                guild_tax=float(guild_tax) if guild_tax else None
            )
            session.add(new_we)

            if week >= (payslip_week_start or date(2000,1,1)):
                ytd_gross += gross_pay
                ytd_tax += tax
                ytd_ni += ni
                ytd_pension += pension

            week += timedelta(weeks=1)

        if profile:
            await session.execute(
                update(PayrollProfile).where(PayrollProfile.id == profile.id).values(
                    ytd_gross=ytd_gross,
                    ytd_tax=ytd_tax,
                    ytd_ni=ytd_ni,
                    ytd_pension=ytd_pension
                )
            )

        await session.commit()

async def calculate_single_week_earnings(session: AsyncSession, user_obj: User, week_start: date, manual_wage: float | None = None):
    # Refresh user
    q_user = select(User).where(User.email == user_obj.email)
    user = (await session.execute(q_user)).scalars().first()
    if not user:
        return

    # Fetch time entries
    q_te = select(TimeEntry).where(
        TimeEntry.created_by == user.email,
        TimeEntry.date >= week_start,
        TimeEntry.date < week_start + timedelta(weeks=1)
    ).order_by(TimeEntry.date)
    result_te = await session.execute(q_te)
    time_entries = result_te.scalars().all()

    # Determine wage
    hourly_rate = D(user.wage or 0)
    is_manual = False
    
    if manual_wage is not None:
        hourly_rate = D(str(manual_wage))
        is_manual = True
    else:
        # Check if we already have a manual wage stored
        q_existing = select(WeeklyEarnings).where(
            WeeklyEarnings.created_by == user.email,
            WeeklyEarnings.week_start == week_start
        )
        existing_row = (await session.execute(q_existing)).scalars().first()
        if existing_row and existing_row.is_manual_wage:
            hourly_rate = D(str(existing_row.hourly_wage))
            is_manual = True

    if not hourly_rate:
        return

    gross_pay = sum((D(str(e.hours_worked or 0)) + D(str(e.travel_time or 0))) * hourly_rate for e in time_entries)

    tax = D(0)
    ni = D(0)
    pension = D(0)
    guild_tax = D(0)

    if user.employment_type == "self_employed":
        tax = (gross_pay * D("0.20")).quantize(D("0.01"))
        guild_tax = D(str(user.guild_tax or 0)).quantize(D("0.01"))
        net_pay = gross_pay - tax - guild_tax
    else:
        # NEW Pension Logic: 5% between 120 and 967
        pensionable_earnings = max(D(0), min(gross_pay, D("967")) - D("120"))
        pension = (pensionable_earnings * D("0.05")).quantize(D("0.01"))

        profile = await get_profile(session, user)
        taxable_pay = gross_pay - pension
        annualized_taxable = taxable_pay * 52
        cfg_tax = UkTaxConfig(tax_code=profile.tax_code if profile else "1257L")
        annual_tax = calc_income_tax_annual(annualized_taxable, cfg_tax)
        tax = (annual_tax / 52).quantize(D("0.01"))
        ni = calc_employee_ni_period(taxable_pay, "weekly", UkTaxConfig())
        net_pay = gross_pay - tax - ni - pension

    # Upsert
    result_we = await session.execute(
        select(WeeklyEarnings).where(
            WeeklyEarnings.created_by == user.email,
            WeeklyEarnings.week_start == week_start
        )
    )
    existing_we = result_we.scalars().first()

    if existing_we:
        existing_we.gross_pay = gross_pay
        existing_we.paye_tax = tax
        existing_we.national_insurance = ni
        existing_we.pension = pension
        existing_we.net_pay = net_pay
        existing_we.hourly_wage = float(hourly_rate)
        existing_we.employment_type = user.employment_type
        existing_we.guild_tax = float(guild_tax) if guild_tax else None
        existing_we.is_manual_wage = is_manual
    else:
        new_we = WeeklyEarnings(
            created_by=user.email,
            week_start=week_start,
            gross_pay=gross_pay,
            paye_tax=tax,
            national_insurance=ni,
            pension=pension,
            net_pay=net_pay,
            hourly_wage=float(hourly_rate),
            is_manual_wage=is_manual,
            employment_type=user.employment_type,
            guild_tax=float(guild_tax) if guild_tax else None
        )
        session.add(new_we)
    
    await session.commit()
