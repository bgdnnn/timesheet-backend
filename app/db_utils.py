import asyncio
from .db import engine
from .models import Base

async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
        # Execute raw SQL to ensure migration of the new columns on startup
        from sqlalchemy import text
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_auto_upload_enabled BOOLEAN DEFAULT FALSE;"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS auto_upload_provider VARCHAR(32) NULL;"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS auto_upload_folder VARCHAR(255) NULL;"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS auto_upload_company VARCHAR(255) NULL;"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS auto_upload_email VARCHAR(255) NULL;"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS auto_upload_app_password VARCHAR(512) NULL;"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS pdf_password VARCHAR(512) NULL;"))
