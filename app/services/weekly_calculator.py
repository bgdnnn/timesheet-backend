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


async def recalculate_all_earnings(user: User):
    async with AsyncSessionLocal() as session:
        # Clear all existing weekly earnings for the user first
        await session.execute(delete(WeeklyEarnings).where(WeeklyEarnings.created_by == user.email))
        await session.flush()  # Ensure the delete is processed before we add new rows

        # 1. Get user's profile, which is the source of truth for calculations
        profile = await get_profile(session, user)
        if not profile:
            return

        # 2. Get the payslip date from the json file to determine the anchor week
        safe_user = user_slug_from_identity(user)
        json_path = Path(settings.MEDIA_ROOT) / safe_user / "payslip.json"
        if not json_path.exists():
            return

        with open(json_path, "r") as f:
            payslip_data = json.load(f)
        
        # Try to get date from process_date, fallback to tax_period
        process_date_str = payslip_data.get("process_date")
        tax_period = payslip_data.get("tax_period")
        
        payslip_week_start = None
        if process_date_str:
            try:
                process_date = datetime.strptime(process_date_str, "%d/%m/%Y").date()
                payslip_week_start = week_monday(process_date)
            except (ValueError, TypeError):
                pass

        if payslip_week_start is None and tax_period:
            today = date.today()
            tax_year = today.year
            # Tax year starts in April. If we are in Jan-Mar, the tax year started last calendar year.
            if today.month < 4 or (today.month == 4 and today.day < 6):
                tax_year -= 1
            
            payslip_date_from_period = tax_period_to_date(tax_year, int(tax_period))
            payslip_week_start = week_monday(payslip_date_from_period)

        if not payslip_week_start:
            # Still no date, we cannot proceed
            return

        # 3. Populate the WeeklyEarnings for the payslip week itself
        payslip_week_earnings = WeeklyEarnings(
            created_by=user.email,
            week_start=payslip_week_start,
            gross_pay=profile.baseline_gross,
            paye_tax=profile.baseline_paye,
            national_insurance=profile.baseline_ni,
            pension=profile.baseline_pension,
            net_pay=profile.baseline_net,
        )
        session.add(payslip_week_earnings)

        # 4. Forward calculation (from payslip week + 1 to current week)
        # Initialize YTD totals directly from the payslip.json data, not the profile
        ytd_gross = D(payslip_data.get("ytd_gross") or 0)
        ytd_tax = D(payslip_data.get("ytd_tax") or 0)
        ytd_ni = D(payslip_data.get("ytd_ni") or 0)
        ytd_pension = D(payslip_data.get("ytd_pension") or 0)
        
        start_forward_week = payslip_week_start + timedelta(weeks=1)
        current_week_start = week_monday(date.today())

        q_te = select(TimeEntry).where(
            TimeEntry.created_by == user.email,
            TimeEntry.date >= start_forward_week
        ).order_by(TimeEntry.date)
        time_entries = (await session.execute(q_te)).scalars().all()

        entries_by_week = {}
        for entry in time_entries:
            ws = week_monday(entry.date)
            if ws not in entries_by_week:
                entries_by_week[ws] = []
            entries_by_week[ws].append(entry)

        hourly_rate = D(user.wage or 0)
        if hourly_rate > 0:
            week = start_forward_week
            while week <= current_week_start:
                weekly_entries = entries_by_week.get(week, [])
                
                gross_pay = sum((D(str(e.hours_worked or 0)) + D(str(e.travel_time or 0))) * hourly_rate for e in weekly_entries)
                
                pension_rate = D("0.04")
                pension_income_cap = D("1058.75")
                income_for_pension = min(gross_pay, pension_income_cap)
                pension = (income_for_pension * pension_rate).quantize(D("0.01"))

                taxable_pay = gross_pay - pension
                
                annualized_taxable = taxable_pay * 52
                cfg_tax = UkTaxConfig(tax_code=profile.tax_code)
                annual_tax = calc_income_tax_annual(annualized_taxable, cfg_tax)
                tax_for_period = (annual_tax / 52).quantize(D("0.01"))

                cfg_ni = UkTaxConfig()
                ni = calc_employee_ni_period(taxable_pay, "weekly", cfg_ni)

                net_pay = gross_pay - tax_for_period - ni - pension

                if weekly_entries:
                    new_we = WeeklyEarnings(
                        created_by=user.email,
                        week_start=week,
                        gross_pay=gross_pay,
                        paye_tax=tax_for_period,
                        national_insurance=ni,
                        pension=pension,
                        net_pay=net_pay,
                    )
                    session.add(new_we)
                    
                    # Update YTD totals for the final update
                    ytd_gross += gross_pay
                    ytd_tax += tax_for_period
                    ytd_ni += ni
                    ytd_pension += pension

                week += timedelta(weeks=1)

        # 5. Historical Calculation (pre-payslip)
        tax_year_start = get_tax_year_start_date(payslip_week_start)
        
        q_hist_te = select(TimeEntry).where(
            TimeEntry.created_by == user.email,
            TimeEntry.date >= tax_year_start,
            TimeEntry.date < payslip_week_start
        ).order_by(TimeEntry.date)
        hist_time_entries = (await session.execute(q_hist_te)).scalars().all()

        hist_entries_by_week = {}
        for entry in hist_time_entries:
            ws = week_monday(entry.date)
            if ws not in hist_entries_by_week:
                hist_entries_by_week[ws] = []
            hist_entries_by_week[ws].append(entry)

        if profile.baseline_gross > 0:
            effective_tax_rate = profile.baseline_paye / profile.baseline_gross
        else:
            effective_tax_rate = D("0.20") # Fallback

        week = week_monday(tax_year_start)
        while week < payslip_week_start:
            weekly_entries = hist_entries_by_week.get(week, [])
            
            gross_pay = sum((D(str(e.hours_worked or 0)) + D(str(e.travel_time or 0))) * hourly_rate for e in weekly_entries)
            
            # Pension calculation (same as forward)
            pension_rate = D("0.04")
            pension_income_cap = D("1058.75")
            income_for_pension = min(gross_pay, pension_income_cap)
            pension = (income_for_pension * pension_rate).quantize(D("0.01"))

            # Tax calculation based on effective rate
            tax = (gross_pay * effective_tax_rate).quantize(D("0.01"))

            # NI calculation (still an estimate)
            taxable_for_ni = gross_pay - pension
            cfg_ni = UkTaxConfig()
            ni = calc_employee_ni_period(taxable_for_ni, "weekly", cfg_ni)

            net_pay = gross_pay - tax - ni - pension

            if weekly_entries:
                new_we = WeeklyEarnings(
                    created_by=user.email,
                    week_start=week,
                    gross_pay=gross_pay,
                    paye_tax=tax,
                    national_insurance=ni,
                    pension=pension,
                    net_pay=net_pay,
                )
                session.add(new_we)
            
            week += timedelta(weeks=1)

        # 6. Final step: Update the payroll profile with the new YTD totals
        await session.execute(
            update(PayrollProfile).where(PayrollProfile.id == profile.id).values(
                ytd_gross=ytd_gross,
                ytd_tax=ytd_tax,
                ytd_ni=ytd_ni,
                ytd_pension=ytd_pension
            )
        )

        await session.commit()