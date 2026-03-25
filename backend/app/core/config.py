from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    APP_NAME: str = "Tradeforge"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False

    # Database — overridden by DATABASE_URL env var on Render (PostgreSQL)
    DATABASE_URL: str = f"sqlite:///{Path(__file__).resolve().parent.parent.parent / 'data' / 'tradeforge.db'}"

    # Auth
    SECRET_KEY: str = "tradeforge-dev-secret-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60  # 1 hour (use /api/auth/refresh to extend)
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 10080  # 7 days

    # CORS — overridden by FRONTEND_URL env var on Render
    FRONTEND_URL: str = "http://localhost:3000"

    # File uploads
    UPLOAD_DIR: str = str(Path(__file__).resolve().parent.parent.parent / "data" / "uploads")
    MAX_UPLOAD_SIZE_MB: int = 500

    # News APIs
    FINNHUB_API_KEY: str = ""
    ALPHAVANTAGE_API_KEY: str = ""
    NEWSAPI_ORG_KEY: str = ""
    NEWS_CACHE_TTL_MINUTES: int = 15

    # SMTP (app-level, for notifications + invitations + 2FA)
    SMTP_SERVER: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    NOTIFICATION_EMAIL: str = ""

    # Telegram (app-level bot token)
    TELEGRAM_BOT_TOKEN: str = ""

    # Platform-level LLM key (all users get AI access without their own key)
    PLATFORM_LLM_API_KEY: str = ""

    # Databento (CME futures data — requires subscription)
    DATABENTO_API_KEY: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()

import warnings
import logging as _logging

_DEFAULT_SECRETS = {"flowrexalgo-dev-secret-change-in-production", "tradeforge-dev-secret-change-in-production"}
if settings.SECRET_KEY in _DEFAULT_SECRETS:
    warnings.warn(
        "Using default SECRET_KEY - this is insecure for production! "
        "Set SECRET_KEY environment variable to a random value.",
        stacklevel=1,
    )
    # Block production startup with default key (#50)
    if not settings.DEBUG and not settings.DATABASE_URL.startswith("sqlite"):
        raise RuntimeError(
            "FATAL: Default SECRET_KEY detected in production (non-SQLite DB, DEBUG=False). "
            "Set a unique SECRET_KEY in your environment to start the server."
        )
