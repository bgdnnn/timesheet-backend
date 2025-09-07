import asyncio
from app.db import engine
from app.models import Expense

async def drop_expenses_table():
    async with engine.begin() as conn:
        print("Dropping expenses table...")
        await conn.run_sync(Expense.__table__.drop)
        print("Expenses table dropped.")

if __name__ == "__main__":
    asyncio.run(drop_expenses_table())
