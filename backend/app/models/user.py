from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, DateTime, Boolean
from sqlalchemy.orm import relationship

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(128), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Profile fields
    email = Column(String(255), default="")
    phone = Column(String(50), default="")

    # 2FA / TOTP (legacy columns kept for migration compat)
    totp_secret = Column(String(64), default="")
    totp_enabled = Column(Boolean, default=False)

    # 2FA Email OTP
    otp_code = Column(String(10), default="")
    otp_expires_at = Column(DateTime, nullable=True)

    # Admin & invitation
    is_admin = Column(Boolean, default=False)
    must_change_password = Column(Boolean, default=False)
    invited_by = Column(Integer, default=None, nullable=True)

    strategies = relationship("Strategy", back_populates="creator")
