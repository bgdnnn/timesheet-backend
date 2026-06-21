from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, update
from datetime import date, timedelta, datetime
import json
import re
from decimal import ROUND_HALF_EVEN
from pathlib import Path

from ..models import WeeklyEarnings, TimeEntry, User, PayrollProfile, PayslipFile
from ..db import AsyncSessionLocal
from ..lib.uk_tax import calc_income_tax_annual, calc_employee_ni_period, D, UkTaxConfig
from ..utils.tax_year import get_tax_year_start_date, tax_period_to_date
from ..utils.users import user_slug_from_identity
from ..config import settings
from ..utils.dates import week_monday
from ..services.payroll import get_profile


def get_tax_week(dt: date) -> int:
    year = dt.year
    tax_start = date(year, 4, 6)
    if dt < tax_start:
        tax_start = date(year - 1, 4, 6)
    delta = dt - tax_start
    return (delta.days // 7) + 1


def calc_cumulative_tax(ytd_taxable_pay, tax_week, tax_code):
    pa = D("12570")
    if tax_code:
        tax_code = tax_code.upper()
        if tax_code in ["BR", "0T"]:
            pa = D("0")
        else:
            numeric_match = re.match(r"(\d+)", tax_code)
            if numeric_match:
                suffix = tax_code[-1]
                val = D(numeric_match.group(1)) * 10
                if suffix in ["L", "M", "N"]:
                    pa = val + 9
                else:
                    pa = val

    pa_cum = int(pa * tax_week / 52)
    taxable_cum = max(D("0"), ytd_taxable_pay - pa_cum)
    taxable_cum_rounded = int(taxable_cum)
    
    basic_limit_cum = int(D("37700") * tax_week / 52)
    higher_limit_cum = int(D("125140") * tax_week / 52)
    
    basic_band = min(taxable_cum_rounded, basic_limit_cum)
    higher_band = min(max(0, taxable_cum_rounded - basic_limit_cum), max(0, higher_limit_cum - basic_limit_cum))
    additional_band = max(0, taxable_cum_rounded - higher_limit_cum)
    
    cumulative_tax = D(basic_band) * D("0.20") + D(higher_band) * D("0.40") + D(additional_band) * D("0.45")
    return cumulative_tax


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

        # 2. Get the latest payslip from database for tax code and anchoring
        q_latest_pf = select(PayslipFile).where(
            PayslipFile.created_by == user.email,
            PayslipFile.gross_pay.isnot(None),
            PayslipFile.paye_tax.isnot(None),
            PayslipFile.net_pay.isnot(None)
        ).order_by(PayslipFile.tax_year.desc(), PayslipFile.tax_week.desc())
        latest_pf = (await session.execute(q_latest_pf)).scalars().first()

        # Update profile with the latest parsed payslip values if they exist
        if latest_pf and profile:
            profile.tax_code = latest_pf.tax_code or profile.tax_code
            profile.baseline_gross = latest_pf.gross_pay
            profile.baseline_paye = latest_pf.paye_tax
            profile.baseline_ni = latest_pf.national_insurance
            profile.baseline_pension = latest_pf.pension
            profile.baseline_net = latest_pf.net_pay
            session.add(profile)
            await session.flush()

        safe_user = user_slug_from_identity(user)
        db_payslip_date = latest_pf.process_date if latest_pf else None

        json_path = Path(settings.MEDIA_ROOT) / safe_user / "payslip.json"
        json_payslip_date = None
        json_data = {}
        if json_path.exists():
            try:
                with open(json_path, "r") as f:
                    json_data = json.load(f)
                p_date_str = json_data.get("process_date")
                if p_date_str:
                    json_payslip_date = datetime.strptime(p_date_str, "%d/%m/%Y").date()
            except Exception:
                pass

        use_db = False
        if db_payslip_date and json_payslip_date:
            if db_payslip_date >= json_payslip_date:
                use_db = True
        elif db_payslip_date:
            use_db = True

        payslip_week_start = None
        payslip_data = {}
        if use_db and latest_pf:
            payslip_data = {
                "tax_code": latest_pf.tax_code,
                "total_gross_pay": latest_pf.gross_pay,
                "paye_tax": latest_pf.paye_tax,
                "national_insurance": latest_pf.national_insurance,
                "pension": latest_pf.pension,
                "tax_period": latest_pf.tax_week,
                "ytd_gross": latest_pf.ytd_gross,
                "ytd_tax": latest_pf.ytd_tax,
                "ytd_ni": latest_pf.ytd_ni,
                "calculated_net_pay": latest_pf.net_pay,
                "process_date": latest_pf.process_date,
                "source": "db"
            }
            payslip_week_start = week_monday(latest_pf.process_date - timedelta(weeks=2))
        elif json_data:
            payslip_data = json_data
            if json_payslip_date:
                payslip_week_start = week_monday(json_payslip_date - timedelta(weeks=2))

        today = date.today()
        tax_year_start = get_tax_year_start_date(today)
        if payslip_week_start and payslip_week_start < (tax_year_start - timedelta(weeks=2)):
            payslip_week_start = None
            payslip_data = {}

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
        q_te = select(TimeEntry).where(
            TimeEntry.created_by == user.email,
            TimeEntry.date >= (tax_year_start - timedelta(weeks=2))
        ).order_by(TimeEntry.date)
        time_entries = (await session.execute(q_te)).scalars().all()

        entries_by_week = {}
        for entry in time_entries:
            ws = week_monday(entry.date)
            if ws not in entries_by_week:
                entries_by_week[ws] = []
            entries_by_week[ws].append(entry)

        max_entry_week = max(entries_by_week.keys()) if entries_by_week else week_monday(today)
        end_week = max(week_monday(today), max_entry_week)

        ytd_gross = D(payslip_data.get("ytd_gross") or 0) if payslip_week_start else D(0)
        ytd_tax = D(payslip_data.get("ytd_tax") or 0) if payslip_week_start else D(0)
        ytd_ni = D(payslip_data.get("ytd_ni") or 0) if payslip_week_start else D(0)
        
        # Estimate YTD pension using anchor tax period
        tax_period_val = payslip_data.get("tax_period")
        ytd_pension = D(str(payslip_data.get("pension") or 0)) * D(str(tax_period_val or 0)) if payslip_week_start else D(0)

        week = week_monday(tax_year_start - timedelta(weeks=2))
        while week <= end_week:
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
                tax_code = profile.tax_code if (profile and profile.tax_code) else "1257L"
                tax_week = get_tax_week(week + timedelta(weeks=2))
                
                # Pension: 5% between 120 and 967
                pensionable_earnings = max(D(0), min(gross_pay, D("967")) - D("120"))
                pension = (pensionable_earnings * D("0.05")).quantize(D("0.01"))

                ytd_gross += gross_pay
                ytd_pension += pension

                # Cumulative Tax calculation
                cum_tax = calc_cumulative_tax(ytd_gross - ytd_pension, tax_week, tax_code)
                tax = cum_tax - ytd_tax
                if tax < D("0"):
                    tax = D("0")
                ytd_tax = cum_tax

                # NI calculation (calculated weekly on gross pay, before pension)
                PT = D("242")
                UEL = D("967")
                main_ni_rate = D("0.08")
                above_uel_rate = D("0.02")
                
                main_band = max(D("0"), min(gross_pay, UEL) - PT)
                above_band = max(D("0"), gross_pay - UEL)
                
                ni_raw = main_band * main_ni_rate + above_band * above_uel_rate
                ni = ni_raw.quantize(D("0.01"), rounding=ROUND_HALF_EVEN)
                ytd_ni += ni
                
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
        # Pension: 5% between 120 and 967
        pensionable_earnings = max(D(0), min(gross_pay, D("967")) - D("120"))
        pension = (pensionable_earnings * D("0.05")).quantize(D("0.01"))

        profile = await get_profile(session, user)
        taxable_pay = gross_pay - pension
        annualized_taxable = taxable_pay * 52
        cfg_tax = UkTaxConfig(tax_code=profile.tax_code if profile else "1257L")
        annual_tax = calc_income_tax_annual(annualized_taxable, cfg_tax)
        tax = (annual_tax / 52).quantize(D("0.01"))
        ni = calc_employee_ni_period(gross_pay, "weekly", UkTaxConfig())
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
