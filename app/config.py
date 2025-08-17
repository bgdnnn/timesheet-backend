from pydantic_settings import BaseSettings
from typing import List

class Settings(BaseSettings):
    DATABASE_URL: str
    JWT_SECRET: str
    JWT_ALG: str = "HS256"
    ACCESS_TOKEN_MINUTES: int = 60
    REFRESH_TOKEN_DAYS: int = 7

    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    OAUTH_REDIRECT_URI: str

    CORS_ORIGINS: str = ""

    class Config:
        env_file = ".env"

settings = Settings()

def cors_origins_list() -> List[str]:
    if not settings.CORS_ORIGINS:
        return []
    return [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
