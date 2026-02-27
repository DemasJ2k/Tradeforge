import os
import shutil
from pathlib import Path
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user, hash_password, verify_password
from app.core.config import settings as app_settings
from app.core.encryption import encrypt_value, decrypt_value
from app.models.user import User
from app.models.settings import UserSettings
from app.models.datasource import DataSource
from app.schemas.settings import (
    SettingsUpdate,
    SettingsResponse,
    LLMTestRequest,
    LLMTestResponse,
    PasswordChangeRequest,
    StorageInfo,
    BrokerCredentialsSave,
    BrokerCredentialMasked,
    BrokerCredentialsResponse,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _get_or_create_settings(db: Session, user: User) -> UserSettings:
    """Get existing settings or create defaults for user."""
    s = db.query(UserSettings).filter(UserSettings.user_id == user.id).first()
    if not s:
        s = UserSettings(user_id=user.id)
        db.add(s)
        db.commit()
        db.refresh(s)
    return s


def _settings_to_response(s: UserSettings) -> SettingsResponse:
    """Convert DB model to response (never leak raw API keys)."""
    return SettingsResponse(
        display_name=s.display_name or "",
        theme=s.theme or "dark",
        accent_color=s.accent_color or "blue",
        font_size=s.font_size or "normal",
        compact_mode=bool(s.compact_mode),
        chart_up_color=s.chart_up_color or "#22c55e",
        chart_down_color=s.chart_down_color or "#ef4444",
        chart_volume_color=s.chart_volume_color or "#3b82f6",
        chart_grid=bool(s.chart_grid),
        chart_crosshair=bool(s.chart_crosshair),
        llm_provider=s.llm_provider or "",
        llm_api_key_set=bool(s.llm_api_key_encrypted),
        llm_model=s.llm_model or "",
        llm_temperature=s.llm_temperature or "0.7",
        llm_max_tokens=s.llm_max_tokens or "4096",
        llm_system_prompt=s.llm_system_prompt or "",
        default_balance=s.default_balance or "10000",
        default_spread=s.default_spread or "0.3",
        default_commission=s.default_commission or "7.0",
        default_point_value=s.default_point_value or "1.0",
        default_risk_pct=s.default_risk_pct or "2.0",
        preferred_instruments=s.preferred_instruments or "",
        preferred_timeframes=s.preferred_timeframes or "",
        default_broker=s.default_broker or "",
        csv_retention_days=s.csv_retention_days or 0,
        export_format=s.export_format or "csv",
        max_storage_mb=s.max_storage_mb or 0,
        session_timeout_minutes=s.session_timeout_minutes or 0,
        notifications=s.notifications or {},
    )


# ─── GET all settings ───
@router.get("", response_model=SettingsResponse)
def get_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = _get_or_create_settings(db, current_user)
    return _settings_to_response(s)


# ─── PUT partial update ───
@router.put("", response_model=SettingsResponse)
def update_settings(
    payload: SettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = _get_or_create_settings(db, current_user)
    data = payload.model_dump(exclude_none=True)

    # Handle LLM API key separately (encrypt before storing)
    if "llm_api_key" in data:
        raw_key = data.pop("llm_api_key")
        if raw_key:
            s.llm_api_key_encrypted = encrypt_value(raw_key)
        else:
            s.llm_api_key_encrypted = ""

    # Map boolean fields to int for SQLite
    bool_to_int = {"compact_mode", "chart_grid", "chart_crosshair"}
    for key, val in data.items():
        if key in bool_to_int:
            setattr(s, key, int(val))
        elif hasattr(s, key):
            setattr(s, key, val)

    s.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(s)
    return _settings_to_response(s)


# ─── Test LLM connection ───
@router.post("/test-llm", response_model=LLMTestResponse)
async def test_llm_connection(
    payload: LLMTestRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    provider = payload.provider.lower()
    api_key = payload.api_key
    model = payload.model

    # If frontend sends "stored", decrypt the saved key from DB
    if api_key == "stored":
        user_settings = db.query(UserSettings).filter(UserSettings.user_id == current_user.id).first()
        if user_settings and user_settings.llm_api_key_encrypted:
            api_key = decrypt_value(user_settings.llm_api_key_encrypted)
        else:
            return LLMTestResponse(success=False, message="No stored API key found. Please enter your API key first.")

    if not api_key:
        return LLMTestResponse(success=False, message="No API key provided")

    try:
        if provider == "claude":
            try:
                import anthropic
            except ImportError:
                return LLMTestResponse(success=False, message="anthropic package not installed. Run: pip install anthropic")
            client = anthropic.Anthropic(api_key=api_key)
            model_name = model or "claude-sonnet-4-20250514"
            msg = client.messages.create(
                model=model_name,
                max_tokens=50,
                messages=[{"role": "user", "content": "Reply with exactly: CONNECTION_OK"}],
            )
            return LLMTestResponse(success=True, message="Connected to Claude API", model_used=model_name)

        elif provider == "openai":
            try:
                import openai
            except ImportError:
                return LLMTestResponse(success=False, message="openai package not installed. Run: pip install openai")
            client = openai.OpenAI(api_key=api_key)
            model_name = model or "gpt-4o-mini"
            resp = client.chat.completions.create(
                model=model_name,
                max_tokens=50,
                messages=[{"role": "user", "content": "Reply with exactly: CONNECTION_OK"}],
            )
            return LLMTestResponse(success=True, message="Connected to OpenAI API", model_used=model_name)

        elif provider == "gemini":
            try:
                import google.generativeai as genai
            except ImportError:
                return LLMTestResponse(success=False, message="google-generativeai package not installed. Run: pip install google-generativeai")
            genai.configure(api_key=api_key)
            model_name = model or "gemini-2.0-flash"
            gm = genai.GenerativeModel(model_name)
            resp = gm.generate_content("Reply with exactly: CONNECTION_OK")
            return LLMTestResponse(success=True, message="Connected to Gemini API", model_used=model_name)

        else:
            return LLMTestResponse(success=False, message=f"Unknown provider: {provider}")

    except Exception as e:
        return LLMTestResponse(success=False, message=f"Connection failed: {str(e)[:200]}")


# ─── Change password ───
@router.post("/change-password")
def change_password(
    payload: PasswordChangeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    if len(payload.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")

    current_user.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"status": "ok", "message": "Password changed successfully"}


# ─── Storage info ───
@router.get("/storage", response_model=StorageInfo)
def get_storage_info(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    upload_dir = Path(app_settings.UPLOAD_DIR)
    files = list(upload_dir.glob("*.csv"))
    total_size = sum(f.stat().st_size for f in files) / (1024 * 1024)
    oldest = min(files, key=lambda f: f.stat().st_mtime).name if files else ""
    newest = max(files, key=lambda f: f.stat().st_mtime).name if files else ""

    return StorageInfo(
        total_csvs=len(files),
        total_size_mb=round(total_size, 2),
        oldest_file=oldest,
        newest_file=newest,
    )


# ─── Database backup (download) ───
@router.get("/backup")
def download_backup(
    current_user: User = Depends(get_current_user),
):
    db_path = Path(app_settings.DATABASE_URL.replace("sqlite:///", ""))
    if not db_path.exists():
        raise HTTPException(status_code=404, detail="Database file not found")

    # Copy to temp to avoid locking issues
    backup_path = db_path.parent / f"backup_{int(datetime.now().timestamp())}.db"
    shutil.copy2(db_path, backup_path)

    return FileResponse(
        path=str(backup_path),
        filename=f"tradeforge_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db",
        media_type="application/octet-stream",
    )


# ─── Clear all CSV data ───
@router.delete("/clear-data")
def clear_all_data(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    upload_dir = Path(app_settings.UPLOAD_DIR)
    deleted = 0
    for f in upload_dir.glob("*.csv"):
        try:
            f.unlink()
            deleted += 1
        except OSError:
            pass

    # Remove datasource records
    db.query(DataSource).delete()
    db.commit()

    return {"status": "ok", "deleted_files": deleted}


# ─── Broker Credentials ───

import json
import logging

_logger = logging.getLogger(__name__)

def _load_broker_creds(s: UserSettings) -> dict:
    """Decrypt and parse the broker_api_keys JSON blob."""
    if not s.broker_api_keys:
        return {}
    try:
        raw = decrypt_value(s.broker_api_keys)
        return json.loads(raw)
    except Exception:
        return {}


def _save_broker_creds(s: UserSettings, creds: dict, db: Session):
    """Encrypt and persist the broker credentials blob."""
    s.broker_api_keys = encrypt_value(json.dumps(creds))
    s.updated_at = datetime.now(timezone.utc)
    db.commit()


@router.get("/broker-credentials", response_model=BrokerCredentialsResponse)
async def get_broker_credentials(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return masked broker credential info (never sends raw keys)."""
    from app.services.broker.manager import broker_manager

    s = _get_or_create_settings(db, current_user)
    creds = _load_broker_creds(s)
    status = await broker_manager.get_status()

    brokers = []
    for broker_name in ["mt5", "oanda", "coinbase", "tradovate"]:
        entry = creds.get(broker_name, {})
        configured = bool(entry)
        fields_set = [k for k, v in entry.items() if v and k not in ("broker", "auto_connect", "practice")] if entry else []
        connected = broker_name in status and status[broker_name].get("connected", False)
        brokers.append(BrokerCredentialMasked(
            broker=broker_name,
            configured=configured,
            auto_connect=entry.get("auto_connect", False),
            connected=connected,
            fields_set=fields_set,
        ))
    return BrokerCredentialsResponse(brokers=brokers)


@router.put("/broker-credentials")
def save_broker_credentials(
    payload: BrokerCredentialsSave,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Store encrypted credentials for a broker."""
    s = _get_or_create_settings(db, current_user)
    creds = _load_broker_creds(s)
    entry = payload.credentials
    creds[entry.broker] = entry.model_dump()
    _save_broker_creds(s, creds, db)
    return {"status": "ok", "broker": entry.broker}


@router.delete("/broker-credentials/{broker_name}")
def delete_broker_credentials(
    broker_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove stored credentials for a broker."""
    s = _get_or_create_settings(db, current_user)
    creds = _load_broker_creds(s)
    creds.pop(broker_name, None)
    _save_broker_creds(s, creds, db)
    return {"status": "ok", "broker": broker_name}


@router.post("/broker-credentials/{broker_name}/connect")
async def connect_saved_broker(
    broker_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Connect to a broker using stored credentials."""
    s = _get_or_create_settings(db, current_user)
    creds = _load_broker_creds(s)
    entry = creds.get(broker_name)
    if not entry:
        raise HTTPException(400, f"No saved credentials for {broker_name}")

    from app.services.broker.manager import broker_manager

    if broker_name == "mt5":
        from app.services.broker.mt5_bridge import MT5Adapter
        adapter = MT5Adapter(
            server=entry.get("server", ""),
            login=int(entry.get("login", "0")),
            password=entry.get("password", ""),
        )
    elif broker_name == "oanda":
        from app.services.broker.oanda import OandaAdapter
        adapter = OandaAdapter(
            api_key=entry.get("api_key", ""),
            account_id=entry.get("account_id", ""),
            practice=entry.get("practice", True),
        )
    elif broker_name == "coinbase":
        from app.services.broker.coinbase import CoinbaseAdapter
        adapter = CoinbaseAdapter(
            api_key=entry.get("api_key", ""),
            api_secret=entry.get("api_secret", ""),
        )
    elif broker_name == "tradovate":
        from app.services.broker.tradovate import TradovateAdapter
        adapter = TradovateAdapter(
            username=entry.get("username", ""),
            password=entry.get("password", ""),
            app_id=entry.get("app_id", ""),
            cid=entry.get("cid", ""),
            sec=entry.get("sec", ""),
        )
    else:
        raise HTTPException(400, f"Unsupported broker: {broker_name}")

    success = await broker_manager.connect_broker(broker_name, adapter)
    if not success:
        detail = getattr(adapter, "_last_error", "") or "Unknown error"
        raise HTTPException(400, f"Failed to connect to {broker_name}: {detail}")

    # Auto-register as market data provider
    try:
        from app.services.market.provider import market_data, BrokerProvider
        market_data.register("broker", BrokerProvider(adapter))
    except Exception as e:
        _logger.warning("Failed to register broker as market data provider: %s", e)

    return {"status": "connected", "broker": broker_name}


@router.post("/broker-auto-connect")
async def auto_connect_brokers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Auto-connect all brokers that have auto_connect=True."""
    s = _get_or_create_settings(db, current_user)
    creds = _load_broker_creds(s)
    results = {}

    for broker_name, entry in creds.items():
        if not entry.get("auto_connect"):
            continue
        try:
            # Re-use the connect endpoint logic
            from app.services.broker.manager import broker_manager
            status = await broker_manager.get_status()
            if broker_name in status and status[broker_name].get("connected"):
                results[broker_name] = "already_connected"
                continue

            # Build the adapter
            if broker_name == "mt5":
                from app.services.broker.mt5_bridge import MT5Adapter
                adapter = MT5Adapter(
                    server=entry.get("server", ""),
                    login=int(entry.get("login", "0")),
                    password=entry.get("password", ""),
                )
            elif broker_name == "oanda":
                from app.services.broker.oanda import OandaAdapter
                adapter = OandaAdapter(
                    api_key=entry.get("api_key", ""),
                    account_id=entry.get("account_id", ""),
                    practice=entry.get("practice", True),
                )
            elif broker_name == "coinbase":
                from app.services.broker.coinbase import CoinbaseAdapter
                adapter = CoinbaseAdapter(
                    api_key=entry.get("api_key", ""),
                    api_secret=entry.get("api_secret", ""),
                )
            elif broker_name == "tradovate":
                from app.services.broker.tradovate import TradovateAdapter
                adapter = TradovateAdapter(
                    username=entry.get("username", ""),
                    password=entry.get("password", ""),
                    app_id=entry.get("app_id", ""),
                    cid=entry.get("cid", ""),
                    sec=entry.get("sec", ""),
                )
            else:
                continue

            ok = await broker_manager.connect_broker(broker_name, adapter)
            results[broker_name] = "connected" if ok else "failed"

            if ok:
                try:
                    from app.services.market.provider import market_data, BrokerProvider
                    market_data.register("broker", BrokerProvider(adapter))
                except Exception:
                    pass

        except Exception as e:
            results[broker_name] = f"error: {e}"

    return {"results": results}
