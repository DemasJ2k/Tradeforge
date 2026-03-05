"""
Notification service – sends email (SMTP) and Telegram messages
using app-level config (env vars) + per-user recipient addresses.
"""

import asyncio
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

import httpx

from sqlalchemy.orm import Session

from app.core.config import settings as app_settings
from app.models.settings import UserSettings

logger = logging.getLogger(__name__)

# ───────────────────────── helpers ─────────────────────────

def _get_user_settings(db: Session, user_id: int) -> Optional[UserSettings]:
    return db.query(UserSettings).filter(UserSettings.user_id == user_id).first()


# ───────────────────────── EMAIL ─────────────────────────

def _send_email(
    *,
    to_email: str,
    subject: str,
    body_text: str,
    body_html: Optional[str] = None,
    smtp_host: Optional[str] = None,
    smtp_port: Optional[int] = None,
    smtp_user: Optional[str] = None,
    smtp_pass: Optional[str] = None,
    use_tls: bool = True,
) -> bool:
    """Send an email via SMTP. Uses app-level config by default."""
    host = smtp_host or app_settings.SMTP_SERVER
    port = smtp_port or app_settings.SMTP_PORT
    user = smtp_user or app_settings.SMTP_USERNAME
    passwd = smtp_pass or app_settings.SMTP_PASSWORD

    if not all([to_email, host, user, passwd]):
        logger.debug("Email skipped – incomplete SMTP config")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = user
        msg["To"] = to_email

        msg.attach(MIMEText(body_text, "plain"))
        if body_html:
            msg.attach(MIMEText(body_html, "html"))

        with smtplib.SMTP(host, port, timeout=15) as server:
            server.ehlo()
            if use_tls:
                server.starttls()
                server.ehlo()
            server.login(user, passwd)
            server.sendmail(user, to_email, msg.as_string())

        logger.info("Notification email sent to %s", to_email)
        return True
    except Exception as exc:
        logger.error("Notification email failed (%s): %s", to_email, exc)
        return False


def send_email_notification(
    db: Session,
    user_id: int,
    subject: str,
    body_text: str,
    body_html: Optional[str] = None,
) -> bool:
    """Send an email notification using app-level SMTP + user's recipient email."""
    s = _get_user_settings(db, user_id)
    if not s:
        return False

    to_email = s.notification_email
    if not to_email:
        logger.debug("Email notification skipped – no recipient email for user %s", user_id)
        return False

    return _send_email(
        to_email=to_email,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
    )


# ───────────────────────── TELEGRAM ─────────────────────────

async def _send_telegram_async(bot_token: str, chat_id: str, text: str) -> bool:
    """Send a Telegram message using the Bot API."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                logger.info("Telegram notification sent to chat %s", chat_id)
                return True
            logger.error("Telegram API %s: %s", resp.status_code, resp.text[:200])
            return False
    except Exception as exc:
        logger.error("Telegram notification failed: %s", exc)
        return False


async def send_telegram_notification(
    db: Session,
    user_id: int,
    text: str,
) -> bool:
    """Send a Telegram notification using app-level bot token + user's chat_id."""
    s = _get_user_settings(db, user_id)
    if not s:
        return False

    bot_token = app_settings.TELEGRAM_BOT_TOKEN
    chat_id = s.notification_telegram_chat_id

    if not bot_token or not chat_id:
        logger.debug("Telegram notification skipped – incomplete config for user %s", user_id)
        return False

    return await _send_telegram_async(bot_token, chat_id, text)


# ───────────────────────── UNIFIED ─────────────────────────

# Event types that users can toggle on/off
NOTIFICATION_EVENTS = {
    "backtest_complete",
    "optimize_complete",
    "trade_executed",
    "agent_started",
    "agent_stopped",
    "agent_error",
    "signal_generated",
    "price_alert",
}


async def notify(
    db: Session,
    user_id: int,
    subject: str,
    body: str,
    body_html: Optional[str] = None,
    event_type: Optional[str] = None,
) -> dict:
    """
    Send notification to all configured channels for the user.
    Checks user's notification toggles if event_type is provided.
    Returns {"email": bool, "telegram": bool}.
    """
    results = {"email": False, "telegram": False}

    # Check if user has this event type enabled
    if event_type:
        s = _get_user_settings(db, user_id)
        if s:
            prefs = s.notifications if isinstance(s.notifications, dict) else {}
            # Default: all events enabled if not explicitly toggled off
            if not prefs.get(event_type, True):
                logger.debug("Notification '%s' disabled for user %s", event_type, user_id)
                return results

    # Email (sync, fast enough for SMTP)
    results["email"] = send_email_notification(db, user_id, subject, body, body_html)

    # Telegram (async)
    results["telegram"] = await send_telegram_notification(db, user_id, body)

    return results


# ───────────────────────── TEST helpers ─────────────────────────

def test_email_settings(*, to_email: str) -> bool:
    """Send a test email to the given address using app-level SMTP."""
    return _send_email(
        to_email=to_email,
        subject="FlowrexAlgo – Test Notification",
        body_text="This is a test email from FlowrexAlgo. If you received this, your email notifications are configured correctly!",
    )


async def test_telegram_settings(*, chat_id: str) -> bool:
    """Send a test Telegram message to the given chat_id using app-level bot token."""
    bot_token = app_settings.TELEGRAM_BOT_TOKEN
    if not bot_token:
        logger.error("TELEGRAM_BOT_TOKEN not configured")
        return False
    return await _send_telegram_async(
        bot_token, chat_id,
        "✅ <b>FlowrexAlgo</b> – Test notification received! Your Telegram notifications are configured correctly.",
    )
