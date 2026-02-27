from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    APP_NAME: str = "TradeForge"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False

    # Database — overridden by DATABASE_URL env var on Render (PostgreSQL)
    DATABASE_URL: str = f"sqlite:///{Path(__file__).resolve().parent.parent.parent / 'data' / 'tradeforge.db'}"

    # Auth
    SECRET_KEY: str = "tradeforge-dev-secret-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours

    # CORS — overridden by FRONTEND_URL env var on Render
    FRONTEND_URL: str = "http://localhost:3000"

    # File uploads
    UPLOAD_DIR: str = str(Path(__file__).resolve().parent.parent.parent / "data" / "uploads")
    MAX_UPLOAD_SIZE_MB: int = 500

    # SMTP (for invitation emails)
    SMTP_SERVER: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    NOTIFICATION_EMAIL: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
