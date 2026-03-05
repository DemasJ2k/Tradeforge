from datetime import datetime, timedelta, timezone

import bcrypt
import pyotp
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    from app.models.user import User

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id_str = payload.get("sub")
        if user_id_str is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.id == int(user_id_str)).first()
    if user is None:
        raise credentials_exception
    return user


def get_current_admin(
    current_user=Depends(get_current_user),
):
    """Dependency that ensures the current user is an admin."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


# ─── TOTP helpers (legacy, kept for backward compat) ───

def generate_totp_secret() -> str:
    return pyotp.random_base32()


def get_totp_provisioning_uri(secret: str, username: str) -> str:
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=username, issuer_name="TradeForge")


def verify_totp_code(secret: str, code: str) -> bool:
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)


# ─── Email OTP helpers ───

import secrets
import logging

_otp_log = logging.getLogger(__name__)


def generate_otp_code() -> str:
    """Generate a 6-digit numeric OTP code."""
    return f"{secrets.randbelow(1000000):06d}"


def store_otp(user, db: Session, expires_minutes: int = 10) -> str:
    """Generate and store OTP on user record. Returns the code."""
    code = generate_otp_code()
    user.otp_code = code
    user.otp_expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    db.commit()
    return code


def verify_otp(user, code: str) -> bool:
    """Verify OTP code against stored value. Returns True if valid and not expired."""
    if not user.otp_code or not user.otp_expires_at:
        return False
    if datetime.now(timezone.utc) > user.otp_expires_at.replace(tzinfo=timezone.utc) if user.otp_expires_at.tzinfo is None else user.otp_expires_at:
        _otp_log.debug("OTP expired for user %s", user.id)
        return False
    return secrets.compare_digest(user.otp_code, code.strip())


def send_otp_email(user, code: str) -> bool:
    """Send OTP code to user's email using app-level SMTP."""
    from app.services.notification import _send_email

    email = user.email
    if not email:
        _otp_log.warning("Cannot send OTP – user %s has no email", user.id)
        return False

    return _send_email(
        to_email=email,
        subject=f"TradeForge – Your verification code: {code}",
        body_text=f"Your TradeForge verification code is: {code}\n\nThis code expires in 10 minutes.\n\nIf you did not request this, please ignore this email.",
        body_html=f"""
        <div style="font-family: sans-serif; max-width: 400px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #3b82f6;">TradeForge</h2>
            <p>Your verification code is:</p>
            <div style="font-size: 32px; font-weight: bold; letter-spacing: 8px; text-align: center;
                        padding: 20px; background: #1a1a2e; color: #fff; border-radius: 8px; margin: 16px 0;">
                {code}
            </div>
            <p style="color: #888; font-size: 14px;">This code expires in 10 minutes.</p>
            <p style="color: #888; font-size: 12px;">If you did not request this, please ignore this email.</p>
        </div>
        """,
    )
