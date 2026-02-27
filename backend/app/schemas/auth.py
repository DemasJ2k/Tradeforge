from typing import Optional
from pydantic import BaseModel


# ─── Existing ───

class UserCreate(BaseModel):
    username: str
    password: str


class UserLogin(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    email: str = ""
    phone: str = ""
    is_admin: bool = False
    totp_enabled: bool = False
    must_change_password: bool = False

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    must_change_password: bool = False
    totp_required: bool = False


# ─── Invitation ───

class InvitationCreate(BaseModel):
    email: str
    temp_password: str
    username: str


class InvitationResponse(BaseModel):
    id: int
    email: str
    username: str = ""
    status: str
    created_at: str

    class Config:
        from_attributes = True


# ─── Forced Password Change ───

class ForceChangePasswordRequest(BaseModel):
    new_password: str


# ─── TOTP / 2FA ───

class TOTPSetupResponse(BaseModel):
    secret: str
    provisioning_uri: str
    qr_base64: str


class TOTPVerifyRequest(BaseModel):
    code: str


class TOTPVerifyResponse(BaseModel):
    valid: bool


# ─── Profile Update ───

class ProfileUpdate(BaseModel):
    email: Optional[str] = None
    phone: Optional[str] = None
