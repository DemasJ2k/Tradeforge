"""Simple symmetric encryption for API keys stored in DB.

Uses Fernet (AES-128-CBC) via the `cryptography` package if available,
otherwise falls back to base64 obfuscation (not truly secure, but prevents
plain-text storage until the user installs the cryptography package).
"""

import base64
import hashlib

from app.core.config import settings

_FERNET = None
try:
    from cryptography.fernet import Fernet
    # Derive a 32-byte URL-safe key from the app secret
    key = base64.urlsafe_b64encode(
        hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    )
    _FERNET = Fernet(key)
except ImportError:
    pass


def encrypt_value(plain: str) -> str:
    """Encrypt a string value for DB storage."""
    if not plain:
        return ""
    if _FERNET:
        return _FERNET.encrypt(plain.encode()).decode()
    # Fallback: base64 encode (NOT secure, just obfuscation)
    return "b64:" + base64.b64encode(plain.encode()).decode()


def decrypt_value(encrypted: str) -> str:
    """Decrypt a stored value back to plain text."""
    if not encrypted:
        return ""
    if encrypted.startswith("b64:"):
        return base64.b64decode(encrypted[4:]).decode()
    if _FERNET:
        try:
            return _FERNET.decrypt(encrypted.encode()).decode()
        except Exception:
            return ""
    return ""
