"""
Admin broadcast API — send announcements to all users via email + Telegram.
"""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import get_current_admin
from app.core.config import settings as app_settings
from app.core.database import get_db
from app.models.broadcast import Broadcast
from app.models.user import User
from app.models.settings import UserSettings
from app.services.notification import _send_email, _send_telegram_async

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin-broadcast"])

# ── Category styling for emails ──────────────────────────────────

CATEGORY_STYLES = {
    "update": {
        "emoji": "\U0001f680",
        "label": "Update",
        "color": "#3b82f6",
        "bg": "#1e3a5f",
    },
    "maintenance": {
        "emoji": "\U0001f527",
        "label": "Maintenance",
        "color": "#f59e0b",
        "bg": "#3d2e0a",
    },
    "new_feature": {
        "emoji": "\u2728",
        "label": "New Feature",
        "color": "#10b981",
        "bg": "#0a3d2e",
    },
    "alert": {
        "emoji": "\u26a0\ufe0f",
        "label": "Alert",
        "color": "#ef4444",
        "bg": "#3d0a0a",
    },
}


# ── Schemas ──────────────────────────────────────────────────────

class BroadcastRequest(BaseModel):
    category: str  # update, maintenance, new_feature, alert
    subject: str
    body: str


class BroadcastResponse(BaseModel):
    id: int
    category: str
    subject: str
    body: str
    recipients_count: int
    email_sent: int
    telegram_sent: int
    created_at: str

    class Config:
        from_attributes = True


# ── Helpers ──────────────────────────────────────────────────────

def _build_email_html(category: str, subject: str, body: str) -> str:
    style = CATEGORY_STYLES.get(category, CATEGORY_STYLES["update"])
    app_name = app_settings.APP_NAME

    # Convert newlines to <br> for HTML rendering
    body_html = body.replace("\n", "<br/>")

    return f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 560px; margin: 0 auto; padding: 32px 24px; background: #0f0f23; color: #e0e0e0;">
        <div style="text-align: center; margin-bottom: 24px;">
            <h1 style="color: #00d4aa; font-size: 24px; margin: 0;">\u26a1 {app_name}</h1>
        </div>

        <div style="background: {style['bg']}; border: 1px solid {style['color']}40; border-radius: 12px; padding: 24px; margin-bottom: 24px;">
            <div style="display: inline-block; background: {style['color']}20; color: {style['color']}; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; padding: 4px 12px; border-radius: 6px; margin-bottom: 16px;">
                {style['emoji']} {style['label']}
            </div>
            <h2 style="color: #fff; font-size: 18px; margin: 0 0 16px 0;">{subject}</h2>
            <div style="color: #ccc; font-size: 14px; line-height: 1.7;">
                {body_html}
            </div>
        </div>

        <p style="color: #555; font-size: 11px; text-align: center; margin: 0;">
            You're receiving this because you have an account on {app_name}.
        </p>
    </div>
    """


def _build_telegram_text(category: str, subject: str, body: str) -> str:
    style = CATEGORY_STYLES.get(category, CATEGORY_STYLES["update"])
    return (
        f"{style['emoji']} <b>[{style['label']}] {subject}</b>\n\n"
        f"{body}\n\n"
        f"— {app_settings.APP_NAME}"
    )


# ── Endpoints ────────────────────────────────────────────────────

@router.post("/broadcast", response_model=BroadcastResponse)
async def send_broadcast(
    req: BroadcastRequest,
    admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Send a broadcast to all users via email and Telegram."""
    if req.category not in CATEGORY_STYLES:
        raise HTTPException(400, f"Invalid category. Must be one of: {', '.join(CATEGORY_STYLES)}")
    if not req.subject.strip():
        raise HTTPException(400, "Subject cannot be empty")
    if not req.body.strip():
        raise HTTPException(400, "Body cannot be empty")

    # Get all users with their settings
    users = db.query(User).all()
    user_ids = [u.id for u in users]
    settings_map: dict[int, UserSettings] = {}
    if user_ids:
        all_settings = db.query(UserSettings).filter(UserSettings.user_id.in_(user_ids)).all()
        settings_map = {s.user_id: s for s in all_settings}

    # Build messages
    email_subject = f"[{CATEGORY_STYLES[req.category]['label']}] {req.subject}"
    email_html = _build_email_html(req.category, req.subject, req.body)
    email_text = f"[{CATEGORY_STYLES[req.category]['label']}] {req.subject}\n\n{req.body}\n\n— {app_settings.APP_NAME}"
    telegram_text = _build_telegram_text(req.category, req.subject, req.body)

    bot_token = app_settings.TELEGRAM_BOT_TOKEN

    email_count = 0
    telegram_count = 0
    recipients = 0

    for u in users:
        s = settings_map.get(u.id)
        sent_any = False

        # Email: try notification_email from settings, fall back to user.email
        to_email = ""
        if s and s.notification_email:
            to_email = s.notification_email
        elif u.email:
            to_email = u.email

        if to_email:
            ok = _send_email(
                to_email=to_email,
                subject=email_subject,
                body_text=email_text,
                body_html=email_html,
            )
            if ok:
                email_count += 1
                sent_any = True

        # Telegram
        chat_id = s.notification_telegram_chat_id if s else ""
        if bot_token and chat_id:
            ok = await _send_telegram_async(bot_token, chat_id, telegram_text)
            if ok:
                telegram_count += 1
                sent_any = True

        if sent_any:
            recipients += 1

    # Save to history
    record = Broadcast(
        admin_id=admin.id,
        category=req.category,
        subject=req.subject.strip(),
        body=req.body.strip(),
        recipients_count=recipients,
        email_sent=email_count,
        telegram_sent=telegram_count,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    logger.info(
        "Broadcast #%d sent by admin %s: %d recipients (%d email, %d telegram)",
        record.id, admin.username, recipients, email_count, telegram_count,
    )

    return BroadcastResponse(
        id=record.id,
        category=record.category,
        subject=record.subject,
        body=record.body,
        recipients_count=record.recipients_count,
        email_sent=record.email_sent,
        telegram_sent=record.telegram_sent,
        created_at=record.created_at.isoformat() if record.created_at else "",
    )


@router.get("/broadcasts")
async def list_broadcasts(
    admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """List broadcast history (most recent first)."""
    records = (
        db.query(Broadcast)
        .order_by(Broadcast.created_at.desc())
        .limit(50)
        .all()
    )

    # Get admin usernames
    admin_ids = list({r.admin_id for r in records})
    admins = {}
    if admin_ids:
        admin_users = db.query(User).filter(User.id.in_(admin_ids)).all()
        admins = {u.id: u.username for u in admin_users}

    return [
        {
            "id": r.id,
            "category": r.category,
            "subject": r.subject,
            "body": r.body,
            "recipients_count": r.recipients_count,
            "email_sent": r.email_sent,
            "telegram_sent": r.telegram_sent,
            "admin_username": admins.get(r.admin_id, "unknown"),
            "created_at": r.created_at.isoformat() if r.created_at else "",
        }
        for r in records
    ]
