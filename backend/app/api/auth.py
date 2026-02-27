import io
import base64
from datetime import datetime, timezone

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
from app.schemas.auth import (
    UserCreate, UserLogin, UserResponse, Token,
    InvitationCreate, InvitationResponse,
    ForceChangePasswordRequest,
    TOTPSetupResponse, TOTPVerifyRequest, TOTPVerifyResponse,
    ProfileUpdate,
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


# ─── Admin: Revoke invitation ───
@router.delete("/invitations/{invite_id}")
def revoke_invitation(
    invite_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    invite = db.query(Invitation).filter(Invitation.id == invite_id).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if invite.status != "pending":
        raise HTTPException(status_code=400, detail="Can only revoke pending invitations")

    invite.status = "revoked"
    db.commit()
    return {"status": "ok", "message": "Invitation revoked"}
