from typing import Optional
from pydantic import BaseModel


class SettingsUpdate(BaseModel):
    """Partial update — every field is optional."""

    # Profile
    display_name: Optional[str] = None

    # Appearance
    theme: Optional[str] = None
    accent_color: Optional[str] = None
    font_size: Optional[str] = None
    compact_mode: Optional[bool] = None

    # Chart
    chart_up_color: Optional[str] = None
    chart_down_color: Optional[str] = None
    chart_volume_color: Optional[str] = None
    chart_grid: Optional[bool] = None
    chart_crosshair: Optional[bool] = None

    # LLM
    llm_provider: Optional[str] = None
    llm_api_key: Optional[str] = None  # plain text in request, encrypted in DB
    llm_model: Optional[str] = None
    llm_temperature: Optional[str] = None
    llm_max_tokens: Optional[str] = None
    llm_system_prompt: Optional[str] = None

    # Trading defaults
    default_balance: Optional[str] = None
    default_spread: Optional[str] = None
    default_commission: Optional[str] = None
    default_point_value: Optional[str] = None
    default_risk_pct: Optional[str] = None
    preferred_instruments: Optional[str] = None
    preferred_timeframes: Optional[str] = None

    # Broker
    default_broker: Optional[str] = None

    # Data management
    csv_retention_days: Optional[int] = None
    export_format: Optional[str] = None
    max_storage_mb: Optional[int] = None

    # Platform
    session_timeout_minutes: Optional[int] = None
    notifications: Optional[dict] = None


class SettingsResponse(BaseModel):
    # Profile
    display_name: str = ""

    # Appearance
    theme: str = "dark"
    accent_color: str = "blue"
    font_size: str = "normal"
    compact_mode: bool = False

    # Chart
    chart_up_color: str = "#22c55e"
    chart_down_color: str = "#ef4444"
    chart_volume_color: str = "#3b82f6"
    chart_grid: bool = True
    chart_crosshair: bool = True

    # LLM (never return the raw API key)
    llm_provider: str = ""
    llm_api_key_set: bool = False  # just tells frontend whether a key is stored
    llm_model: str = ""
    llm_temperature: str = "0.7"
    llm_max_tokens: str = "4096"
    llm_system_prompt: str = ""

    # Trading defaults
    default_balance: str = "10000"
    default_spread: str = "0.3"
    default_commission: str = "7.0"
    default_point_value: str = "1.0"
    default_risk_pct: str = "2.0"
    preferred_instruments: str = ""
    preferred_timeframes: str = ""

    # Broker
    default_broker: str = ""

    # Data management
    csv_retention_days: int = 0
    export_format: str = "csv"
    max_storage_mb: int = 0

    # Platform
    session_timeout_minutes: int = 0
    notifications: dict = {}


class LLMTestRequest(BaseModel):
    provider: str  # claude, openai, gemini
    api_key: str
    model: str = ""


class LLMTestResponse(BaseModel):
    success: bool
    message: str
    model_used: str = ""


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class StorageInfo(BaseModel):
    total_csvs: int
    total_size_mb: float
    oldest_file: str = ""
    newest_file: str = ""


# ─── Broker Credentials ───

class BrokerCredentialEntry(BaseModel):
    """Credential fields for a single broker (stored encrypted)."""
    broker: str  # "mt5", "oanda", "coinbase", "tradovate"
    # MT5 fields
    server: str = ""
    login: str = ""
    password: str = ""
    # Oanda / Coinbase fields
    api_key: str = ""
    account_id: str = ""
    api_secret: str = ""
    practice: bool = True
    # Tradovate fields
    username: str = ""
    app_id: str = ""
    cid: str = ""
    sec: str = ""
    # Auto-connect toggle
    auto_connect: bool = False


class BrokerCredentialsSave(BaseModel):
    """Request to store credentials for one broker."""
    credentials: BrokerCredentialEntry


class BrokerCredentialMasked(BaseModel):
    """Masked broker credential info returned to frontend."""
    broker: str
    configured: bool = False
    auto_connect: bool = False
    connected: bool = False
    # Show which fields are set (not their values)
    fields_set: list[str] = []  # e.g. ["server", "login", "password"]


class BrokerCredentialsResponse(BaseModel):
    brokers: list[BrokerCredentialMasked] = []
