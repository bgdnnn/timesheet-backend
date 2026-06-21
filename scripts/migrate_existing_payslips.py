import os
import sys
import asyncio
from sqlalchemy import select
from pathlib import Path

# Add parent dir to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from app.db import get_session
from app.models import PayslipFile, User
from app.utils.payslip_ocr import extract_payslip_text, parse_payslip_text
from app.utils.security import decrypt_value

async def main():
    async for session in get_session():
        # Get all users to map their passwords
        result = await session.execute(select(User))
        users = result.scalars().all()
        user_pw_map = {}
        for u in users:
            pdf_pw = decrypt_value(u.pdf_password) if hasattr(u, "pdf_password") and u.pdf_password else None
            user_pw_map[u.email] = pdf_pw

        # Get all payslips
        result = await session.execute(select(PayslipFile))
        pfs = result.scalars().all()
        
        print(f"Found {len(pfs)} payslips to migrate.")
        
        for pf in pfs:
            path = Path(pf.file_path)
            if not path.exists():
                print(f"Skipping {pf.filename}: file not found at {pf.file_path}")
                continue
            
            pdf_pw = user_pw_map.get(pf.created_by)
            print(f"Processing {pf.filename} for {pf.created_by}...")
            
            try:
                raw_text = extract_payslip_text(str(path), pdf_pw)
                parsed = parse_payslip_text(raw_text)
                
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
                
                session.add(pf)
                print(f"  Successfully parsed and updated database values.")
            except Exception as e:
                print(f"  Failed to parse {pf.filename}: {e}")
                
        await session.commit()
        print("Migration complete!")
        break

if __name__ == "__main__":
    asyncio.run(main())
