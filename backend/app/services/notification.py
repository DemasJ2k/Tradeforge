"""
Notification service – sends email (SMTP) and Telegram messages
using per-user settings stored in UserSettings.
"""

import asyncio
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

import httpx

from sqlalchemy.orm import Session

from app.core.encryption import decrypt_value
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
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_pass: str,
    use_tls: bool = True,
) -> bool:
    """Send an email via user-configured SMTP. Returns True on success."""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = smtp_user
        msg["To"] = to_email

        msg.attach(MIMEText(body_text, "plain"))
        if body_html:
            msg.attach(MIMEText(body_html, "html"))

        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.ehlo()
            if use_tls:
                server.starttls()
                server.ehlo()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, to_email, msg.as_string())

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
    """Send an email notification using the user's stored SMTP settings."""
    s = _get_user_settings(db, user_id)
    if not s:
        return False

    to_email = s.notification_email
    smtp_host = s.notification_smtp_host
    smtp_user = s.notification_smtp_user
    smtp_pass_enc = s.notification_smtp_pass_encrypted

    if not all([to_email, smtp_host, smtp_user, smtp_pass_enc]):
        logger.debug("Email notification skipped – incomplete config for user %s", user_id)
        return False

    smtp_pass = decrypt_value(smtp_pass_enc)
    if not smtp_pass:
        return False

    return _send_email(
        to_email=to_email,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        smtp_host=smtp_host,
        smtp_port=s.notification_smtp_port or 587,
        smtp_user=smtp_user,
        smtp_pass=smtp_pass,
        use_tls=bool(s.notification_smtp_use_tls),
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


def _send_telegram_sync(bot_token: str, chat_id: str, text: str) -> bool:
    """Synchronous wrapper for Telegram sending."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Already inside an async context – schedule as task
        future = asyncio.ensure_future(_send_telegram_async(bot_token, chat_id, text))
        # Can't await here from sync context; fire-and-forget
        return True
    else:
        return asyncio.run(_send_telegram_async(bot_token, chat_id, text))


async def send_telegram_notification(
    db: Session,
    user_id: int,
    text: str,
) -> bool:
    """Send a Telegram notification using the user's stored bot token/chat_id."""
    s = _get_user_settings(db, user_id)
    if not s:
        return False

    token_enc = s.notification_telegram_bot_token_encrypted
    chat_id = s.notification_telegram_chat_id

    if not token_enc or not chat_id:
        logger.debug("Telegram notification skipped – incomplete config for user %s", user_id)
        return False

    bot_token = decrypt_value(token_enc)
    if not bot_token:
        return False

    return await _send_telegram_async(bot_token, chat_id, text)


# ───────────────────────── UNIFIED ─────────────────────────

async def notify(
    db: Session,
    user_id: int,
    subject: str,
    body: str,
    body_html: Optional[str] = None,
) -> dict:
    """
    Send notification to all configured channels for the user.
    Returns {"email": bool, "telegram": bool} indicating which channels succeeded.
    """
    results = {"email": False, "telegram": False}

    # Email (sync, fast enough for SMTP)
    results["email"] = send_email_notification(db, user_id, subject, body, body_html)

    # Telegram (async)
    results["telegram"] = await send_telegram_notification(db, user_id, body)

    return results


# ───────────────────────── TEST helpers ─────────────────────────

def test_email_settings(
    *,
    to_email: str,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_pass: str,
    use_tls: bool = True,
) -> bool:
    """Send a test email with the provided (raw) settings."""
    return _send_email(
        to_email=to_email,
        subject="FlowrexAlgo – Test Notification",
        body_text="This is a test email from FlowrexAlgo. If you received this, your email notifications are configured correctly!",
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        smtp_user=smtp_user,
        smtp_pass=smtp_pass,
        use_tls=use_tls,
    )


async def test_telegram_settings(*, bot_token: str, chat_id: str) -> bool:
    """Send a test Telegram message with the provided (raw) settings."""
    return await _send_telegram_async(
        bot_token, chat_id,
        "✅ <b>FlowrexAlgo</b> – Test notification received! Your Telegram notifications are configured correctly.",
    )
