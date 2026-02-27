from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, DateTime

from app.core.database import Base


class Invitation(Base):
    __tablename__ = "invitations"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), nullable=False, index=True)
    username = Column(String(50), nullable=False)
    temp_password_hash = Column(String(128), nullable=False)
    created_by = Column(Integer, nullable=False)  # admin user id
    status = Column(String(20), default="pending")  # pending, accepted, revoked
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    accepted_at = Column(DateTime, nullable=True)
