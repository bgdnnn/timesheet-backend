import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.path.join(BASE_DIR, ".env")

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    SESSION_COOKIE_NAME: str = "ts_session"
    SESSION_COOKIE_DOMAIN: str = ".home-clouds.com"   
    SESSION_SAMESITE: str = "none"                    
    SESSION_HTTPS_ONLY: bool = True                   
    DATABASE_URL: str
    JWT_SECRET: str
    JWT_ALG: str = "HS256"
    ACCESS_TOKEN_MINUTES: int = 60
    REFRESH_TOKEN_DAYS: int = 7

    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    OAUTH_REDIRECT_URI: str

    CORS_ORIGINS: str = ""
    MEDIA_ROOT: str = "/srv/timesheet-backend/media"

    RESEND_API_KEY: Optional[str] = None
    RESEND_FROM_EMAIL: Optional[str] = None
    BACKUP_ALERT_EMAIL: Optional[str] = None

    def frontend_origin(self) -> str:
        # already present in your codebase or add:
        return "https://timesheet.home-clouds.com"

settings = Settings()

def cors_origins_list() -> List[str]:
    if not settings.CORS_ORIGINS:
        return []
    return [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
