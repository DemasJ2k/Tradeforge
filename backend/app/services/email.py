"""
Email service for sending invitation emails via SMTP.

Uses the SMTP settings from app.core.config.settings.
Gracefully fails (logs warning) if SMTP is not configured.
"""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from app.core.config import settings

logger = logging.getLogger(__name__)


def send_invitation_email(
    to_email: str,
    username: str,
    temp_password: str,
) -> bool:
    """
    Send an invitation email with login credentials.

    Returns True if sent successfully, False otherwise.
    This is a synchronous function — call from a background thread or task.
    """
    if not settings.SMTP_SERVER or not settings.SMTP_USERNAME:
        logger.warning("SMTP not configured — skipping invitation email to %s", to_email)
        return False

    app_url = settings.FRONTEND_URL

    subject = f"You're invited to {settings.APP_NAME}!"

    html_body = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 560px; margin: 0 auto; padding: 32px 24px; background: #0f0f23; color: #e0e0e0;">
        <div style="text-align: center; margin-bottom: 32px;">
            <h1 style="color: #00d4aa; font-size: 28px; margin: 0;">⚡ {settings.APP_NAME}</h1>
            <p style="color: #888; font-size: 14px; margin-top: 8px;">Trading Platform</p>
        </div>

        <div style="background: #1a1a2e; border: 1px solid #2a2a4a; border-radius: 12px; padding: 24px; margin-bottom: 24px;">
            <h2 style="color: #fff; font-size: 18px; margin: 0 0 16px 0;">You've been invited!</h2>
            <p style="color: #ccc; font-size: 14px; line-height: 1.6; margin: 0 0 20px 0;">
                An admin has invited you to join {settings.APP_NAME}. Use the credentials below to log in and get started.
            </p>

            <div style="background: #12121f; border: 1px solid #2a2a4a; border-radius: 8px; padding: 16px; margin-bottom: 16px;">
                <div style="margin-bottom: 12px;">
                    <span style="color: #888; font-size: 12px; text-transform: uppercase;">Username</span>
                    <div style="color: #00d4aa; font-size: 16px; font-weight: 600; font-family: monospace;">{username}</div>
                </div>
                <div>
                    <span style="color: #888; font-size: 12px; text-transform: uppercase;">Temporary Password</span>
                    <div style="color: #00d4aa; font-size: 16px; font-weight: 600; font-family: monospace;">{temp_password}</div>
                </div>
            </div>

            <p style="color: #f59e0b; font-size: 13px; margin: 0 0 16px 0;">
                ⚠️ You'll be asked to change your password on first login.
            </p>

            <a href="{app_url}" style="display: inline-block; background: #00d4aa; color: #000; text-decoration: none; padding: 12px 32px; border-radius: 8px; font-weight: 600; font-size: 14px;">
                Log In to {settings.APP_NAME} →
            </a>
        </div>

        <p style="color: #555; font-size: 12px; text-align: center; margin: 0;">
            If you didn't expect this invitation, you can safely ignore this email.
        </p>
    </div>
    """

    text_body = f"""
You've been invited to {settings.APP_NAME}!

Login URL: {app_url}
Username: {username}
Temporary Password: {temp_password}

You'll be asked to change your password on first login.
    """.strip()

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{settings.APP_NAME} <{settings.SMTP_USERNAME}>"
        msg["To"] = to_email

        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(settings.SMTP_SERVER, settings.SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_USERNAME, to_email, msg.as_string())

        logger.info("Invitation email sent to %s for user %s", to_email, username)
        return True

    except Exception as e:
        logger.error("Failed to send invitation email to %s: %s", to_email, e)
        return False


def send_password_reset_email(
    to_email: str,
    username: str,
    reset_link: str,
) -> bool:
    """
    Send a password reset email with a time-limited link.
    The link expires in 1 hour and is single-use.
    """
    if not settings.SMTP_SERVER or not settings.SMTP_USERNAME:
        logger.warning("SMTP not configured — skipping password reset email to %s", to_email)
        return False

    subject = f"Reset your {settings.APP_NAME} password"

    html_body = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 560px; margin: 0 auto; padding: 32px 24px; background: #0f0f23; color: #e0e0e0;">
        <div style="text-align: center; margin-bottom: 32px;">
            <h1 style="color: #00d4aa; font-size: 28px; margin: 0;">⚡ {settings.APP_NAME}</h1>
            <p style="color: #888; font-size: 14px; margin-top: 8px;">Trading Platform</p>
        </div>

        <div style="background: #1a1a2e; border: 1px solid #2a2a4a; border-radius: 12px; padding: 24px; margin-bottom: 24px;">
            <h2 style="color: #fff; font-size: 18px; margin: 0 0 16px 0;">Password Reset Request</h2>
            <p style="color: #ccc; font-size: 14px; line-height: 1.6; margin: 0 0 20px 0;">
                Hi <strong style="color: #00d4aa;">{username}</strong>, we received a request to reset your password.
                Click the button below to set a new password. This link expires in <strong>1 hour</strong> and can only be used once.
            </p>

            <a href="{reset_link}" style="display: inline-block; background: #00d4aa; color: #000; text-decoration: none; padding: 12px 32px; border-radius: 8px; font-weight: 600; font-size: 14px;">
                Reset My Password →
            </a>

            <p style="color: #f59e0b; font-size: 13px; margin: 20px 0 0 0;">
                ⚠️ If you didn't request a password reset, you can safely ignore this email. Your password won't change.
            </p>
        </div>

        <p style="color: #555; font-size: 12px; text-align: center; margin: 0;">
            If the button doesn't work, copy this link into your browser:<br/>
            <span style="color: #00d4aa; word-break: break-all;">{reset_link}</span>
        </p>
    </div>
    """

    text_body = f"""
Password Reset Request for {settings.APP_NAME}

Hi {username},

We received a request to reset your password. Use the link below (expires in 1 hour):

{reset_link}

If you didn't request this, you can safely ignore this email.
    """.strip()

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{settings.APP_NAME} <{settings.SMTP_USERNAME}>"
        msg["To"] = to_email

        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(settings.SMTP_SERVER, settings.SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_USERNAME, to_email, msg.as_string())

        logger.info("Password reset email sent to %s (user %s)", to_email, username)
        return True

    except Exception as e:
        logger.error("Failed to send password reset email to %s: %s", to_email, e)
        return False


def send_admin_reset_notification(username: str, user_email: str) -> bool:
    """
    Notify the admin that a user has requested a password reset.
    Sends to settings.NOTIFICATION_EMAIL if configured.
    """
    admin_email = settings.NOTIFICATION_EMAIL or settings.SMTP_USERNAME
    if not settings.SMTP_SERVER or not admin_email:
        logger.warning("SMTP not configured — skipping admin reset notification")
        return False

    subject = f"[{settings.APP_NAME}] Password reset requested by {username}"

    html_body = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 560px; margin: 0 auto; padding: 32px 24px; background: #0f0f23; color: #e0e0e0;">
        <div style="text-align: center; margin-bottom: 32px;">
            <h1 style="color: #00d4aa; font-size: 28px; margin: 0;">⚡ {settings.APP_NAME}</h1>
            <p style="color: #888; font-size: 14px; margin-top: 8px;">Admin Notification</p>
        </div>

        <div style="background: #1a1a2e; border: 1px solid #2a2a4a; border-radius: 12px; padding: 24px;">
            <h2 style="color: #fff; font-size: 18px; margin: 0 0 16px 0;">🔑 Password Reset Request</h2>
            <p style="color: #ccc; font-size: 14px; line-height: 1.6; margin: 0 0 16px 0;">
                A user has requested a password reset. A reset link has been automatically emailed to them.
            </p>
            <div style="background: #12121f; border: 1px solid #2a2a4a; border-radius: 8px; padding: 16px;">
                <div style="margin-bottom: 10px;">
                    <span style="color: #888; font-size: 12px; text-transform: uppercase;">Username</span>
                    <div style="color: #00d4aa; font-size: 15px; font-family: monospace;">{username}</div>
                </div>
                <div>
                    <span style="color: #888; font-size: 12px; text-transform: uppercase;">Email</span>
                    <div style="color: #00d4aa; font-size: 15px; font-family: monospace;">{user_email}</div>
                </div>
            </div>
            <p style="color: #888; font-size: 13px; margin: 16px 0 0 0;">
                You can also manually reset their password from the Settings → Profile → Password Reset Requests section.
            </p>
        </div>
    </div>
    """

    text_body = f"""
[{settings.APP_NAME}] Admin Notification: Password reset requested

User: {username}
Email: {user_email}

A reset link has been emailed to them automatically.
You can also manually reset from Settings → Password Reset Requests.
    """.strip()

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{settings.APP_NAME} <{settings.SMTP_USERNAME}>"
        msg["To"] = admin_email

        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(settings.SMTP_SERVER, settings.SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_USERNAME, admin_email, msg.as_string())

        logger.info("Admin reset notification sent to %s", admin_email)
        return True

    except Exception as e:
        logger.error("Failed to send admin reset notification: %s", e)
        return False
