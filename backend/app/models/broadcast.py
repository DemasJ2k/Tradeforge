from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey

from app.core.database import Base


class Broadcast(Base):
    __tablename__ = "broadcasts"

    id = Column(Integer, primary_key=True, index=True)
    admin_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    category = Column(String(30), nullable=False)  # update, maintenance, new_feature, alert
    subject = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    recipients_count = Column(Integer, default=0)
    email_sent = Column(Integer, default=0)
    telegram_sent = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
