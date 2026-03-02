from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, Text
from sqlalchemy.orm import relationship

from app.core.database import Base


class UserSettings(Base):
    __tablename__ = "user_settings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)

    # --- Profile ---
    display_name = Column(String(100), default="")

    # --- Appearance ---
    theme = Column(String(20), default="dark")  # dark, light, system
    accent_color = Column(String(20), default="blue")  # blue, green, orange, purple, red
    font_size = Column(String(10), default="normal")  # small, normal, large
    compact_mode = Column(Integer, default=0)  # 0=off, 1=on

    # --- Chart Preferences ---
    chart_up_color = Column(String(10), default="#22c55e")
    chart_down_color = Column(String(10), default="#ef4444")
    chart_volume_color = Column(String(10), default="#3b82f6")
    chart_grid = Column(Integer, default=1)
    chart_crosshair = Column(Integer, default=1)

    # --- LLM Configuration ---
    llm_provider = Column(String(20), default="")  # claude, openai, gemini
    llm_api_key_encrypted = Column(Text, default="")
    llm_model = Column(String(50), default="")
    llm_temperature = Column(String(10), default="0.7")
    llm_max_tokens = Column(String(10), default="4096")
    llm_system_prompt = Column(Text, default="")

    # --- Default Trading Parameters ---
    default_balance = Column(String(20), default="10000")
    default_spread = Column(String(10), default="0.3")
    default_commission = Column(String(10), default="7.0")
    default_point_value = Column(String(10), default="1.0")
    default_risk_pct = Column(String(10), default="2.0")
    preferred_instruments = Column(Text, default="")  # comma-separated
    preferred_timeframes = Column(Text, default="")  # comma-separated

    # --- Broker Defaults ---
    default_broker = Column(String(20), default="")
    broker_api_keys = Column(Text, default="")  # encrypted JSON blob

    # --- Data Management ---
    csv_retention_days = Column(Integer, default=0)  # 0=keep forever
    export_format = Column(String(10), default="csv")  # csv, json
    max_storage_mb = Column(Integer, default=0)  # 0=unlimited

    # --- Platform ---
    session_timeout_minutes = Column(Integer, default=0)  # 0=no timeout
    notifications = Column(JSON, default=dict)  # {backtest: true, optimize: true, trade: true}

    # --- Notification Channels ---
    notification_email = Column(String(200), default="")       # recipient email address
    notification_smtp_host = Column(String(200), default="")   # e.g. smtp.gmail.com
    notification_smtp_port = Column(Integer, default=587)
    notification_smtp_user = Column(String(200), default="")
    notification_smtp_pass_encrypted = Column(Text, default="")  # encrypted password
    notification_smtp_use_tls = Column(Integer, default=1)       # 1=STARTTLS, 0=none
    notification_telegram_bot_token_encrypted = Column(Text, default="")
    notification_telegram_chat_id = Column(String(100), default="")

    # --- Timestamps ---
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User", backref="settings")
