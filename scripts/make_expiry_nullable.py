# scripts/make_expiry_nullable.py
import asyncio
from sqlalchemy import text
from app.db import engine

async def main():
    async with engine.begin() as conn:
        print("Dropping NOT NULL constraint from trainings.expiry_date...")
        await conn.execute(text("ALTER TABLE trainings ALTER COLUMN expiry_date DROP NOT NULL;"))
        print("Success!")

if __name__ == "__main__":
    asyncio.run(main())
