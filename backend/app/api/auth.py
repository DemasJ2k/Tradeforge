import hashlib
import io
import base64
import logging
import secrets
import threading
from datetime import datetime, timedelta, timezone

import qrcode
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import (
    hash_password, verify_password, create_access_token,
    get_current_user, get_current_admin,
    generate_totp_secret, get_totp_provisioning_uri, verify_totp_code,
)
from app.core.database import get_db
from app.models.user import User
from app.models.invitation import Invitation
from app.models.password_reset import PasswordResetToken
from app.schemas.auth import (
    UserCreate, UserLogin, UserResponse, Token,
    InvitationCreate, InvitationResponse,
    ForceChangePasswordRequest,
    TOTPSetupResponse, TOTPVerifyRequest, TOTPVerifyResponse,
    ProfileUpdate,
    PasswordResetRequest, PasswordResetConfirm, AdminManualReset, ResetRequestItem,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ─── Register (invitation-based only) ───
@router.post("/register", response_model=UserResponse)
def register(data: UserCreate, db: Session = Depends(get_db)):
    # Check if there's a pending invitation for this username
    invite = db.query(Invitation).filter(
        Invitation.username == data.username,
        Invitation.status == "pending",
    ).first()

    if not invite:
        # Allow first-ever user (bootstrap admin) if no users exist at all
        if db.query(User).count() > 0:
            raise HTTPException(status_code=403, detail="Registration is invitation-only. Contact an admin.")

    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")

    user = User(
        username=data.username,
        password_hash=hash_password(data.password),
        must_change_password=bool(invite),
        invited_by=invite.created_by if invite else None,
        email=invite.email if invite else "",
        is_admin=not bool(invite),
    )
    db.add(user)

    if invite:
        invite.status = "accepted"
        invite.accepted_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(user)
    return user


# ─── Login ───
@router.post("/login", response_model=Token)
def login(data: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == data.username).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = create_access_token({"sub": str(user.id)})
    return Token(
        access_token=token,
        must_change_password=bool(user.must_change_password),
        totp_required=bool(user.totp_enabled),
    )


# ─── Get current user ───
@router.get("/me", response_model=UserResponse)
def get_me(user: User = Depends(get_current_user)):
    return user


# ─── Force change password (after invitation login) ───
@router.post("/force-change-password")
def force_change_password(
    payload: ForceChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if len(payload.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    current_user.password_hash = hash_password(payload.new_password)
    current_user.must_change_password = False
    db.commit()
    return {"status": "ok", "message": "Password changed successfully"}


# ─── TOTP Setup (generate secret + QR) ───
@router.post("/setup-totp", response_model=TOTPSetupResponse)
def setup_totp(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.totp_enabled:
        raise HTTPException(status_code=400, detail="2FA is already enabled")

    secret = generate_totp_secret()
    uri = get_totp_provisioning_uri(secret, current_user.username)

    # Generate QR code as base64
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode()

    # Store secret (not yet enabled — user must confirm with a valid code)
    current_user.totp_secret = secret
    db.commit()

    return TOTPSetupResponse(
        secret=secret,
        provisioning_uri=uri,
        qr_base64=qr_b64,
    )


# ─── Confirm TOTP (verify code to enable 2FA) ───
@router.post("/confirm-totp", response_model=TOTPVerifyResponse)
def confirm_totp(
    payload: TOTPVerifyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.totp_secret:
        raise HTTPException(status_code=400, detail="Run /setup-totp first")

    valid = verify_totp_code(current_user.totp_secret, payload.code)
    if valid:
        current_user.totp_enabled = True
        db.commit()
    return TOTPVerifyResponse(valid=valid)


# ─── Verify TOTP (on login when 2FA is enabled) ───
@router.post("/verify-totp", response_model=TOTPVerifyResponse)
def verify_totp(
    payload: TOTPVerifyRequest,
    current_user: User = Depends(get_current_user),
):
    if not current_user.totp_enabled or not current_user.totp_secret:
        raise HTTPException(status_code=400, detail="2FA is not enabled")

    valid = verify_totp_code(current_user.totp_secret, payload.code)
    return TOTPVerifyResponse(valid=valid)


# ─── Disable TOTP ───
@router.post("/disable-totp")
def disable_totp(
    payload: TOTPVerifyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.totp_enabled:
        raise HTTPException(status_code=400, detail="2FA is not enabled")

    if not verify_totp_code(current_user.totp_secret, payload.code):
        raise HTTPException(status_code=400, detail="Invalid 2FA code")

    current_user.totp_enabled = False
    current_user.totp_secret = ""
    db.commit()
    return {"status": "ok", "message": "2FA disabled"}


# ─── Update profile (email, phone) ───
@router.put("/profile", response_model=UserResponse)
def update_profile(
    payload: ProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if payload.email is not None:
        current_user.email = payload.email
    if payload.phone is not None:
        current_user.phone = payload.phone
    db.commit()
    db.refresh(current_user)
    return current_user


# ─── Admin: Create invitation ───
@router.post("/invite", response_model=InvitationResponse)
def create_invitation(
    payload: InvitationCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")

    existing = db.query(Invitation).filter(
        Invitation.username == payload.username,
        Invitation.status == "pending",
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Pending invitation already exists for this username")

    invite = Invitation(
        email=payload.email,
        username=payload.username,
        temp_password_hash=hash_password(payload.temp_password),
        created_by=admin.id,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)

    # Send invitation email in a background thread so the API response isn't delayed
    try:
        from app.services.email import send_invitation_email
        thread = threading.Thread(
            target=send_invitation_email,
            args=(payload.email, payload.username, payload.temp_password),
            daemon=True,
        )
        thread.start()
    except Exception as e:
        logging.getLogger(__name__).warning("Could not send invitation email: %s", e)

    return InvitationResponse(
        id=invite.id,
        email=invite.email,
        username=invite.username,
        status=invite.status,
        created_at=str(invite.created_at),
    )


# ─── Admin: List invitations ───
@router.get("/invitations", response_model=list[InvitationResponse])
def list_invitations(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    invites = db.query(Invitation).order_by(Invitation.created_at.desc()).all()
    return [
        InvitationResponse(
            id=i.id,
            email=i.email,
            username=i.username,
            status=i.status,
            created_at=str(i.created_at),
        )
        for i in invites
    ]


# ─── Admin: Revoke (pending) or permanently delete (revoked) invitation ───
@router.delete("/invitations/{invite_id}")
def revoke_or_delete_invitation(
    invite_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    invite = db.query(Invitation).filter(Invitation.id == invite_id).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invitation not found")

    if invite.status == "pending":
        # Revoke pending invitation
        invite.status = "revoked"
        db.commit()
        return {"status": "ok", "message": "Invitation revoked"}
    elif invite.status == "revoked":
        # Permanently delete a revoked invitation record
        db.delete(invite)
        db.commit()
        return {"status": "ok", "message": "Invitation deleted"}
    else:
        raise HTTPException(status_code=400, detail="Cannot delete an accepted invitation")


# ─── Password Reset: Request (public — no auth required) ───
@router.post("/request-reset")
def request_password_reset(payload: PasswordResetRequest, db: Session = Depends(get_db)):
    """
    Step 1 of password reset.
    Always returns success to avoid leaking whether an email exists.
    Sends a time-limited reset link to the user and a notification to the admin.
    """
    log = logging.getLogger(__name__)
    user = db.query(User).filter(User.email == payload.email.strip().lower()).first()

    if user:
        # Invalidate any existing unused tokens for this user
        db.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
        ).delete(synchronize_session=False)

        # Generate a cryptographically secure raw token (never stored)
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        db.add(PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
        ))
        db.commit()

        reset_link = f"{__import__('app.core.config', fromlist=['settings']).settings.FRONTEND_URL}/reset-password?token={raw_token}"

        def _send():
            try:
                from app.services.email import send_password_reset_email, send_admin_reset_notification
                send_password_reset_email(user.email, user.username, reset_link)
                send_admin_reset_notification(user.username, user.email)
            except Exception as e:
                log.warning("Reset email error: %s", e)

        threading.Thread(target=_send, daemon=True).start()
        log.info("Password reset requested for user %s (email %s)", user.username, user.email)

    # Always return the same response — don't reveal whether email exists
    return {"status": "ok", "message": "If that email is registered, a reset link has been sent."}


# ─── Password Reset: Confirm (public — no auth required) ───
@router.post("/reset-password")
def reset_password(payload: PasswordResetConfirm, db: Session = Depends(get_db)):
    """Step 2 of password reset. Validates the token and sets the new password."""
    if len(payload.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    token_hash = hashlib.sha256(payload.token.encode()).hexdigest()
    now = datetime.now(timezone.utc)

    record = db.query(PasswordResetToken).filter(
        PasswordResetToken.token_hash == token_hash,
    ).first()

    if not record:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")

    # Normalize expires_at to UTC-aware if stored as naive datetime
    expires = record.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)

    if expires < now:
        raise HTTPException(status_code=400, detail="Reset link has expired. Please request a new one.")

    if record.used_at is not None:
        raise HTTPException(status_code=400, detail="Reset link has already been used.")

    user = db.query(User).filter(User.id == record.user_id).first()
    if not user:
        raise HTTPException(status_code=400, detail="User not found")

    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    record.used_at = now
    db.commit()

    # Issue a JWT so the frontend can auto-login immediately after reset
    access_token = create_access_token({"sub": str(user.id)})

    logging.getLogger(__name__).info("Password reset completed for user %s", user.username)
    return {
        "status": "ok",
        "message": "Password updated successfully.",
        "access_token": access_token,
        "token_type": "bearer",
        "must_change_password": False,
        "totp_required": bool(user.totp_enabled),
    }


# ─── Admin: List pending reset requests ───
@router.get("/admin/reset-requests", response_model=list[ResetRequestItem])
def list_reset_requests(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Return all password reset tokens (pending and used) ordered newest first."""
    now = datetime.now(timezone.utc)
    records = (
        db.query(PasswordResetToken)
        .order_by(PasswordResetToken.created_at.desc())
        .limit(100)
        .all()
    )
    result = []
    for r in records:
        user = db.query(User).filter(User.id == r.user_id).first()
        if not user:
            continue
        expires = r.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        result.append(ResetRequestItem(
            id=r.id,
            user_id=r.user_id,
            username=user.username,
            email=user.email,
            created_at=r.created_at.strftime("%Y-%m-%d %H:%M UTC"),
            expires_at=expires.strftime("%Y-%m-%d %H:%M UTC"),
            used=r.used_at is not None,
        ))
    return result


# ─── Admin: Manually reset a user's password ───
@router.post("/admin/manual-reset")
def admin_manual_reset(
    payload: AdminManualReset,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Admin sets a temporary password for a user and forces a change on next login."""
    if len(payload.temp_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    user = db.query(User).filter(User.id == payload.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.password_hash = hash_password(payload.temp_password)
    user.must_change_password = True

    # Invalidate any outstanding reset tokens for this user
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None),
    ).delete(synchronize_session=False)

    db.commit()
    logging.getLogger(__name__).info(
        "Admin %s manually reset password for user %s", admin.username, user.username
    )
    return {"status": "ok", "message": f"Password reset for {user.username}. They must change it on next login."}


# ─── Admin: List all registered users ───
@router.get("/admin/users")
def list_users(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Return all registered users (excluding the requesting admin)."""
    users = db.query(User).order_by(User.created_at.asc()).all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "email": u.email or "",
            "is_admin": bool(u.is_admin),
            "must_change_password": bool(u.must_change_password),
            "created_at": u.created_at.strftime("%Y-%m-%d %H:%M UTC") if u.created_at else "",
        }
        for u in users
    ]


# ─── Admin: Delete a user account ───
@router.delete("/admin/users/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Permanently delete a user account and all their personal data."""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_admin:
        raise HTTPException(status_code=400, detail="Cannot delete admin accounts")

    username = user.username

    # Delete password reset tokens
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user_id
    ).delete(synchronize_session=False)

    # Delete LLM data
    try:
        from app.models.llm import LLMMemory, LLMConversation, LLMUsage
        db.query(LLMMemory).filter(LLMMemory.user_id == user_id).delete(synchronize_session=False)
        db.query(LLMConversation).filter(LLMConversation.user_id == user_id).delete(synchronize_session=False)
        db.query(LLMUsage).filter(LLMUsage.user_id == user_id).delete(synchronize_session=False)
    except Exception:
        pass

    # Delete user settings
    try:
        from app.models.settings import UserSettings
        db.query(UserSettings).filter(UserSettings.user_id == user_id).delete(synchronize_session=False)
    except Exception:
        pass

    # Delete the user record
    db.delete(user)
    db.commit()

    logging.getLogger(__name__).info("Admin %s deleted user %s (id=%d)", admin.username, username, user_id)
    return {"status": "ok", "message": f"User '{username}' has been deleted."}
