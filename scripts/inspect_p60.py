import asyncio
import sys
from pathlib import Path
from sqlalchemy import select
from dotenv import load_dotenv

dotenv_path = Path(__file__).resolve().parents[1] / '.env'
load_dotenv(dotenv_path=dotenv_path)

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.db import AsyncSessionLocal
from app.models import PayslipFile, User

async def inspect_db():
    import os
    async with AsyncSessionLocal() as session:
        # Get all users
        users_result = await session.execute(select(User))
        users = users_result.scalars().all()
        print(f"=== DB USER ANALYSIS ===")
        for u in users:
            # Count P60s
            p60s_count = (await session.execute(
                select(PayslipFile).where(PayslipFile.created_by == u.email, PayslipFile.tax_week == 0)
            )).scalars().all()
            
            # Count standard payslips
            payslips_count = (await session.execute(
                select(PayslipFile).where(PayslipFile.created_by == u.email, PayslipFile.tax_week != 0)
            )).scalars().all()
            
            print(f"\nUser Email: {u.email} ({u.full_name})")
            print(f"  Role: {u.role}")
            print(f"  DB P60s: {len(p60s_count)}")
            print(f"  DB Payslips: {len(payslips_count)}")
            
            # Check folder on disk
            safe_email = u.email.replace("@", "_").replace(".", "_") # Wait, how is folder name determined?
            # Let's check folders in media: we saw 'bogdan.tirnauca', 'tinauca.bogdan', 'lenazamurca'
            # Let's check for these folders specifically:
            possible_folders = [
                u.email.split("@")[0],
                u.email
            ]
            for f in possible_folders:
                folder_path = Path("/srv/timesheet-backend/media") / f / "payslips_pdf"
                if folder_path.exists():
                    files = os.listdir(folder_path)
                    p60s_on_disk = [x for x in files if x.endswith("_0.pdf")]
                    payslips_on_disk = [x for x in files if not x.endswith("_0.pdf") and x.endswith(".pdf")]
                    print(f"  Disk Folder: {folder_path}")
                    print(f"    P60s on Disk: {len(p60s_on_disk)}")
                    print(f"    Payslips on Disk: {len(payslips_on_disk)}")

if __name__ == "__main__":
    asyncio.run(inspect_db())
