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
    is_k_code = False
    if tax_code:
        tax_code = tax_code.upper()
        if tax_code in ["BR", "0T"]:
            pa = D("0")
        elif tax_code.startswith("K"):
            is_k_code = True
            numeric_match = re.match(r"K(\d+)", tax_code)
            if numeric_match:
                pa = D(numeric_match.group(1)) * 10
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
    
    # Personal Allowance Tapering (above £100,000 annualized)
    if not is_k_code:
        taper_start_cum = int(D("100000") * tax_week / 52)
        if ytd_taxable_pay > taper_start_cum:
            reduction_cum = int((ytd_taxable_pay - taper_start_cum) / 2)
            pa_cum = max(0, pa_cum - reduction_cum)

    if is_k_code:
        taxable_cum = ytd_taxable_pay + pa_cum
    else:
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

        today = date.today()
        tax_year_start = get_tax_year_start_date(today)

        # 2. Get all payslips from database and parse them
        payslips_by_week = {}
        q_pfs = select(PayslipFile).where(
            PayslipFile.created_by == user.email,
            PayslipFile.gross_pay.isnot(None),
            PayslipFile.paye_tax.isnot(None),
            PayslipFile.net_pay.isnot(None)
        ).order_by(PayslipFile.tax_week.asc())
        pfs = (await session.execute(q_pfs)).scalars().all()

        for pf in pfs:
            pf_week_start = week_monday(pf.process_date - timedelta(weeks=2))
            if pf_week_start >= (tax_year_start - timedelta(weeks=2)):
                payslips_by_week[pf_week_start] = {
                    "tax_code": pf.tax_code,
                    "total_gross_pay": pf.gross_pay,
                    "paye_tax": pf.paye_tax,
                    "national_insurance": pf.national_insurance,
                    "pension": pf.pension,
                    "tax_period": pf.tax_week,
                    "ytd_gross": pf.ytd_gross,
                    "ytd_tax": pf.ytd_tax,
                    "ytd_ni": pf.ytd_ni,
                    "calculated_net_pay": pf.net_pay,
                    "process_date": pf.process_date,
                    "source": "db"
                }

        # Load from JSON if it's newer or not in DB
        safe_user = user_slug_from_identity(user)
        json_path = Path(settings.MEDIA_ROOT) / safe_user / "payslip.json"
        if json_path.exists():
            try:
                with open(json_path, "r") as f:
                    json_data = json.load(f)
                p_date_str = json_data.get("process_date")
                if p_date_str:
                    json_payslip_date = datetime.strptime(p_date_str, "%d/%m/%Y").date()
                    json_week_start = week_monday(json_payslip_date - timedelta(weeks=2))
                    if json_week_start >= (tax_year_start - timedelta(weeks=2)):
                        existing = payslips_by_week.get(json_week_start)
                        if not existing or (existing.get("process_date") and json_payslip_date > existing["process_date"]):
                            payslips_by_week[json_week_start] = {
                                "tax_code": json_data.get("tax_code"),
                                "total_gross_pay": D(str(json_data.get("total_gross_pay") or 0)),
                                "paye_tax": D(str(json_data.get("paye_tax") or 0)),
                                "national_insurance": D(str(json_data.get("national_insurance") or 0)),
                                "pension": D(str(json_data.get("pension") or 0)),
                                "tax_period": json_data.get("tax_period"),
                                "ytd_gross": D(str(json_data.get("ytd_gross") or 0)),
                                "ytd_tax": D(str(json_data.get("ytd_tax") or 0)),
                                "ytd_ni": D(str(json_data.get("ytd_ni") or 0)),
                                "calculated_net_pay": D(str(json_data.get("calculated_net_pay") or 0)),
                                "process_date": json_payslip_date,
                                "source": "json"
                            }
            except Exception:
                pass

        # Update profile with the latest parsed payslip values if they exist
        latest_payslip_data = None
        if payslips_by_week:
            latest_week = max(payslips_by_week.keys())
            latest_payslip_data = payslips_by_week[latest_week]

        if latest_payslip_data and profile:
            profile.tax_code = latest_payslip_data.get("tax_code") or profile.tax_code
            profile.baseline_gross = latest_payslip_data.get("total_gross_pay")
            profile.baseline_paye = latest_payslip_data.get("paye_tax")
            profile.baseline_ni = latest_payslip_data.get("national_insurance")
            profile.baseline_pension = latest_payslip_data.get("pension")
            profile.baseline_net = latest_payslip_data.get("calculated_net_pay")
            session.add(profile)
            await session.flush()

        # 3. Calculation Loop
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

        # Initialize YTD accumulators to 0
        ytd_gross = D(0)
        ytd_tax = D(0)
        ytd_ni = D(0)
        ytd_pension = D(0)

        week = week_monday(tax_year_start - timedelta(weeks=2))
        while week <= end_week:
            if week in payslips_by_week and user.employment_type == "employed":
                p_data = payslips_by_week[week]
                ytd_gross = D(str(p_data.get("ytd_gross") or 0))
                ytd_tax = D(str(p_data.get("ytd_tax") or 0))
                ytd_ni = D(str(p_data.get("ytd_ni") or 0))
                
                tax_period_val = p_data.get("tax_period")
                ytd_pension = D(str(p_data.get("pension") or 0)) * D(str(tax_period_val or 0))

                # Preservation logic for hourly wage in anchor week
                hourly_wage_for_payslip_week = D(user.wage or 0)
                is_manual = False
                if week in existing_we_map:
                    if existing_we_map[week]["wage"] is not None:
                        hourly_wage_for_payslip_week = D(existing_we_map[week]["wage"])
                    is_manual = existing_we_map[week]["manual"]

                payslip_week_earnings = WeeklyEarnings(
                    created_by=user.email,
                    week_start=week,
                    gross_pay=D(str(p_data["total_gross_pay"])),
                    paye_tax=D(str(p_data["paye_tax"])),
                    national_insurance=D(str(p_data["national_insurance"])),
                    pension=D(str(p_data["pension"])),
                    net_pay=D(str(p_data["calculated_net_pay"])),
                    hourly_wage=float(hourly_wage_for_payslip_week),
                    is_manual_wage=is_manual,
                    employment_type="employed"
                )
                session.add(payslip_week_earnings)

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
