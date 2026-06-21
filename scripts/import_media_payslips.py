import os
import sys
import asyncio
import re
from pathlib import Path
from datetime import datetime, date, timedelta
from sqlalchemy import select, delete

# Add parent directory to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from app.db import get_session
from app.models import PayslipFile, User
from app.utils.payslip_ocr import extract_payslip_text, parse_payslip_text
from app.utils.security import decrypt_value
from app.services.weekly_calculator import recalculate_all_earnings

def get_safe_user_slug(email_addr):
    raw = email_addr.split("@")[0]
    slug = re.sub(r"[^a-z0-9._-]+", "-", raw.lower()).strip("-._")
    return slug or "user"

def estimate_date_from_tax_info(tax_year_str: str, tax_week: int) -> date:
    try:
        parts = tax_year_str.split("-")
        start_yy = int(parts[0])
        year = 2000 + start_yy
        tax_start = date(year, 4, 6)
        if tax_week > 0:
            return tax_start + timedelta(weeks=tax_week - 1)
        else:
            end_year = 2000 + int(parts[1])
            return date(end_year, 4, 5)
    except Exception:
        return date.today()

def parse_tax_info_from_filename(filename, fallback_date):
    is_p60 = "p60" in filename.lower() or bool(re.search(r'(^|[^a-zA-Z0-9])p6([^a-zA-Z0-9]|$)', filename.lower()))
    
    # Check for YY-YY_WW pattern (e.g. 22-23_48.pdf)
    yy_ww_match = re.search(r'\d{2}-\d{2}_(\d+)', filename)
    week_match = re.search(r'(?:week|period|wk)[_\s-]?(\d+)', filename, re.IGNORECASE)
    year_pattern = re.search(r'(\d{4})[_\-\s]?(\d{4})', filename)
    year_short_pattern = re.search(r'(\d{2})[_\-\s]?(\d{2})', filename)
    single_year_pattern = re.search(r'\b(20\d{2})\b', filename)
    
    tax_week = None
    tax_year = None
    
    if is_p60:
        tax_week = 0
    elif yy_ww_match:
        tax_week = int(yy_ww_match.group(1))
    elif week_match:
        try:
            tax_week = int(week_match.group(1))
        except ValueError:
            pass
            
    if year_pattern:
        start_y = year_pattern.group(1)
        end_y = year_pattern.group(2)
        tax_year = f"{start_y[2:]}-{end_y[2:]}"
    elif year_short_pattern:
        tax_year = f"{year_short_pattern.group(1)}-{year_short_pattern.group(2)}"
    elif single_year_pattern:
        yr = int(single_year_pattern.group(1))
        tax_year = f"{str(yr-1)[2:]}-{str(yr)[2:]}"
        
    # Helper to calculate tax week and year from date
    def get_tax_week(dt):
        tax_start = date(dt.year, 4, 6)
        if dt < tax_start:
            tax_start = date(dt.year - 1, 4, 6)
        delta = dt - tax_start
        return (delta.days // 7) + 1

    def get_tax_year(dt):
        if dt.month < 4 or (dt.month == 4 and dt.day < 6):
            start_y, end_y = dt.year - 1, dt.year
        else:
            start_y, end_y = dt.year, dt.year + 1
        return f"{str(start_y)[2:]}-{str(end_y)[2:]}"

    if tax_week is None and not is_p60:
        tax_week = get_tax_week(fallback_date)
    if not tax_year:
        tax_year = get_tax_year(fallback_date)
        
    return tax_year, tax_week

async def main():
    media_root = Path("/srv/timesheet-backend/media")
    if not media_root.exists():
        print(f"Error: Media root {media_root} does not exist.")
        return

    async for session in get_session():
        # Clear existing entries in payslip_files to rebuild cleanly
        print("Clearing all current database records in payslip_files...")
        await session.execute(delete(PayslipFile))
        await session.commit()
        print("Database table cleared.")

        # Get all users to map their safe slugs and PDF passwords
        result = await session.execute(select(User))
        users = result.scalars().all()
        
        slug_to_user = {}
        for u in users:
            slug = get_safe_user_slug(u.email)
            slug_to_user[slug] = u

        print(f"Loaded {len(slug_to_user)} users from DB.")

        for slug, user in slug_to_user.items():
            user_dir = media_root / slug / "payslips_pdf"
            if not user_dir.exists():
                print(f"No payslips folder for user slug: {slug} at {user_dir}")
                continue

            pdf_pw = decrypt_value(user.pdf_password) if user.pdf_password else None
            pdf_files = list(user_dir.glob("*.pdf"))
            print(f"\nProcessing {len(pdf_files)} PDFs for user {user.email}...")

            user_modified = False
            for pdf_path in pdf_files:
                filename = pdf_path.name

                # Determine file modification date as basic fallback date
                mtime = os.path.getmtime(pdf_path)
                mtime_date = datetime.fromtimestamp(mtime).date()

                # Extract OCR fields
                print(f"  OCR parsing: {filename}...")
                try:
                    raw_text = extract_payslip_text(str(pdf_path), pdf_pw)
                    parsed = parse_payslip_text(raw_text)
                except Exception as ocr_err:
                    print(f"    OCR extraction failed for {filename}: {ocr_err}")
                    parsed = {}

                # Determine tax year, week, and process date
                # Helper to calculate tax year from date
                def get_tax_year_helper(dt):
                    if dt.month < 4 or (dt.month == 4 and dt.day < 6):
                        start_y, end_y = dt.year - 1, dt.year
                    else:
                        start_y, end_y = dt.year, dt.year + 1
                    return f"{str(start_y)[2:]}-{str(end_y)[2:]}"

                # Prioritize parsed process date from PDF text
                process_date = None
                parsed_process_date_str = parsed.get("process_date")
                if parsed_process_date_str:
                    try:
                        process_date = datetime.strptime(parsed_process_date_str, "%d/%m/%Y").date()
                    except Exception:
                        pass
                
                # Determine tax year, week from filename first
                tax_year, tax_week = parse_tax_info_from_filename(filename, mtime_date)

                # Estimate process date if OCR parsing failed
                if not process_date:
                    process_date = estimate_date_from_tax_info(tax_year, tax_week)

                # Prioritize parsed tax period (week) and year calculated from process date if available!
                if parsed.get("tax_period") is not None:
                    tax_week = int(parsed.get("tax_period"))
                if parsed_process_date_str:
                    tax_year = get_tax_year_helper(process_date)

                # Register in DB
                pf = PayslipFile(
                    created_by=user.email,
                    file_path=str(pdf_path),
                    filename=filename,
                    tax_year=tax_year,
                    tax_week=tax_week,
                    process_date=process_date
                )
                session.add(pf)

                # Populate parsed values
                pf.gross_pay = parsed.get("total_gross_pay")
                pf.paye_tax = parsed.get("paye_tax")
                pf.national_insurance = parsed.get("national_insurance")
                pf.pension = parsed.get("pension")
                pf.net_pay = parsed.get("calculated_net_pay")
                pf.tax_code = parsed.get("tax_code")
                pf.tax_period = parsed.get("tax_period")
                pf.ytd_gross = parsed.get("ytd_gross")
                pf.ytd_tax = parsed.get("ytd_tax")
                pf.ytd_ni = parsed.get("ytd_ni")
                pf.deductions_total = parsed.get("deductions_total")

                user_modified = True
                print(f"    Saved values: Gross={pf.gross_pay}, Net={pf.net_pay}, TaxWeek={pf.tax_week}, TaxYear={pf.tax_year}, ProcessDate={pf.process_date}")

            if user_modified:
                await session.commit()
                print(f"  Committed DB changes for user {user.email}. Recalculating weekly earnings...")
                try:
                    await recalculate_all_earnings(user)
                    print(f"  Weekly recalculation completed for {user.email}.")
                except Exception as recalc_err:
                    print(f"  Recalculation error for {user.email}: {recalc_err}")

        print("\nAll media payslips processed and imported successfully!")
        break

if __name__ == "__main__":
    asyncio.run(main())
