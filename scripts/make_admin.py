import asyncio
import sys
from pathlib import Path
from sqlalchemy import select, update
from dotenv import load_dotenv

# Load environment variables from .env file
# The .env file is in the parent directory of the scripts directory
dotenv_path = Path(__file__).resolve().parents[1] / '.env'
load_dotenv(dotenv_path=dotenv_path)

# Add the app directory to the Python path to allow for absolute imports
sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.db import AsyncSessionLocal
from app.models import User

async def set_admin_role(email: str):
    """
    Finds a user by email and updates their role to 'admin'.
    """
    print(f"Attempting to set admin role for {email}...")
    async with AsyncSessionLocal() as session:
        # Find the user
        user_result = await session.execute(select(User).where(User.email == email))
        user = user_result.scalar_one_or_none()

        if not user:
            print(f"Error: User with email '{email}' not found.")
            return

        # Update the user's role
        await session.execute(
            update(User).where(User.id == user.id).values(role="admin")
        )
        await session.commit()
        print(f"Successfully updated user '{email}' to role 'admin'.")

async def main():
    if len(sys.argv) != 2:
        print("Usage: python scripts/make_admin.py <user_email>")
        sys.exit(1)
    
    email_to_update = sys.argv[1]
    await set_admin_role(email_to_update)

if __name__ == "__main__":
    asyncio.run(main())