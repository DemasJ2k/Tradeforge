"""
Telegram Bot Webhook – handles incoming /start commands so users
can link their Telegram account by username instead of pasting a Chat ID.

Flow:
  1. User enters their Telegram username in Settings
  2. User sends /start to the FlowrexAlgo bot on Telegram
  3. This webhook receives the message, matches the username → stores chat_id
  4. Bot replies "✅ Connected!" and notifications start working
"""

import logging

import httpx
from fastapi import APIRouter, Request
from sqlalchemy import func

from app.core.config import settings as app_settings
from app.core.database import SessionLocal
from app.models.settings import UserSettings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["telegram"])


async def _reply(chat_id: int, text: str) -> None:
    """Send a reply to a Telegram chat."""
    token = app_settings.TELEGRAM_BOT_TOKEN
    if not token:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
            })
    except Exception as exc:
        logger.error("Telegram reply failed: %s", exc)


async def setup_telegram_webhook(base_url: str) -> bool:
    """Register our webhook URL with the Telegram Bot API.
    Call once at startup (idempotent — Telegram ignores if unchanged).
    """
    token = app_settings.TELEGRAM_BOT_TOKEN
    if not token:
        logger.info("TELEGRAM_BOT_TOKEN not set — skipping webhook setup")
        return False

    webhook_url = f"{base_url}/api/telegram/webhook"
    api_url = f"https://api.telegram.org/bot{token}/setWebhook"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(api_url, json={"url": webhook_url})
            data = resp.json()
            if data.get("ok"):
                logger.info("Telegram webhook registered: %s", webhook_url)
                return True
            logger.error("Telegram setWebhook failed: %s", data)
            return False
    except Exception as exc:
        logger.error("Telegram setWebhook error: %s", exc)
        return False


@router.post("/api/telegram/webhook")
async def telegram_webhook(request: Request):
    """
    Receive updates from Telegram Bot API.
    Handles /start command to auto-link username → chat_id.
    """
    try:
        update = await request.json()
    except Exception:
        return {"ok": True}

    message = update.get("message")
    if not message:
        return {"ok": True}

    text = (message.get("text") or "").strip()
    chat = message.get("chat", {})
    from_user = message.get("from", {})
    chat_id = str(chat.get("id", ""))
    tg_username = (from_user.get("username") or "").lower().strip()
    first_name = from_user.get("first_name", "")

    # ── /start command ──
    if text.startswith("/start"):
        if not tg_username:
            await _reply(
                int(chat_id),
                "⚠️ Your Telegram account doesn't have a username set.\n\n"
                "Please set a username in <b>Telegram Settings → Username</b>, "
                "then try /start again.",
            )
            return {"ok": True}

        # Look up user by telegram username (case-insensitive)
        db = SessionLocal()
        try:
            user_settings = db.query(UserSettings).filter(
                func.lower(UserSettings.notification_telegram_username) == tg_username
            ).first()

            if user_settings:
                # Link the chat_id
                user_settings.notification_telegram_chat_id = chat_id
                db.commit()
                logger.info(
                    "Telegram linked: @%s → chat_id %s (user_id=%s)",
                    tg_username, chat_id, user_settings.user_id,
                )
                await _reply(
                    int(chat_id),
                    f"✅ <b>Connected!</b>\n\n"
                    f"Hey {first_name}! Your Telegram is now linked to FlowrexAlgo.\n"
                    f"You'll receive notifications for backtests, trades, alerts, and more right here.\n\n"
                    f"💡 Go back to <b>Settings → Notifications</b> to choose which events you want to be notified about.",
                )
            else:
                await _reply(
                    int(chat_id),
                    f"🔍 Username <b>@{tg_username}</b> not found in FlowrexAlgo.\n\n"
                    f"Make sure you've entered your Telegram username in:\n"
                    f"<b>Settings → Notifications → Telegram</b>\n\n"
                    f"Then come back and send /start again.",
                )
        except Exception as exc:
            db.rollback()
            logger.error("Telegram webhook DB error: %s", exc)
            await _reply(int(chat_id), "❌ Something went wrong. Please try again later.")
        finally:
            db.close()

    # ── /status command ──
    elif text.startswith("/status"):
        if tg_username:
            db = SessionLocal()
            try:
                user_settings = db.query(UserSettings).filter(
                    func.lower(UserSettings.notification_telegram_username) == tg_username
                ).first()
                if user_settings and user_settings.notification_telegram_chat_id == chat_id:
                    await _reply(int(chat_id), "✅ Your Telegram is <b>connected</b> to FlowrexAlgo. Notifications are active.")
                else:
                    await _reply(int(chat_id), "⚠️ Not connected. Send /start to link your account.")
            finally:
                db.close()

    # ── /disconnect command ──
    elif text.startswith("/disconnect"):
        if tg_username:
            db = SessionLocal()
            try:
                user_settings = db.query(UserSettings).filter(
                    func.lower(UserSettings.notification_telegram_username) == tg_username
                ).first()
                if user_settings and user_settings.notification_telegram_chat_id:
                    user_settings.notification_telegram_chat_id = ""
                    db.commit()
                    await _reply(int(chat_id), "🔌 <b>Disconnected.</b> You won't receive FlowrexAlgo notifications anymore.\n\nSend /start to reconnect.")
                else:
                    await _reply(int(chat_id), "You're not connected to FlowrexAlgo.")
            finally:
                db.close()

    # ── /help command ──
    elif text.startswith("/help"):
        await _reply(
            int(chat_id),
            "🤖 <b>FlowrexAlgo Bot Commands</b>\n\n"
            "/start — Link your Telegram to FlowrexAlgo\n"
            "/status — Check connection status\n"
            "/disconnect — Unlink your account\n"
            "/help — Show this help message\n\n"
            "💬 You can also send any message to chat with the AI assistant!\n"
            "Try: <i>\"list my strategies\"</i> or <i>\"what's my best backtest?\"</i>",
        )

    # ── Free-form AI chat ──
    elif text and not text.startswith("/"):
        if not tg_username:
            await _reply(int(chat_id), "Send /start first to link your account.")
            return {"ok": True}

        db = SessionLocal()
        try:
            user_settings = db.query(UserSettings).filter(
                func.lower(UserSettings.notification_telegram_username) == tg_username
            ).first()

            if not user_settings or user_settings.notification_telegram_chat_id != chat_id:
                await _reply(int(chat_id), "Not linked. Send /start first.")
                return {"ok": True}

            # Route to copilot engine
            from app.services.llm.telegram_handler import handle_telegram_message
            response_text = await handle_telegram_message(
                db=db,
                user_id=user_settings.user_id,
                message=text,
                chat_id=chat_id,
            )
            if response_text:
                await _reply(int(chat_id), response_text)
        except Exception as exc:
            logger.error("Telegram AI chat error: %s", exc)
            await _reply(int(chat_id), "Something went wrong processing your request. Try again.")
        finally:
            db.close()

    return {"ok": True}
