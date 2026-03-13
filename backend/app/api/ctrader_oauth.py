"""
cTrader Open API OAuth2 endpoints.

Handles the OAuth2 authorization flow for cTrader:
  1. GET  /auth-url      — returns the redirect URL for user consent
  2. GET  /callback      — handles OAuth callback, exchanges code for tokens
  3. POST /refresh-token — refresh expired access token
  4. GET  /accounts      — lists trading accounts linked to the access token
  5. POST /save-account  — saves selected trading account
"""

import logging
import os

import httpx
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.database import get_db
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/broker/ctrader", tags=["cTrader OAuth"])

# cTrader OAuth2 endpoints
_AUTH_URL = "https://openapi.ctrader.com/apps/auth"
_TOKEN_URL = "https://openapi.ctrader.com/apps/token"

# WebSocket hosts for Open API
_DEMO_WS_HOST = "demo.ctraderapi.com"
_LIVE_WS_HOST = "live.ctraderapi.com"
_WS_PORT = 5035


def _get_client_id() -> str:
    return os.getenv("CTRADER_CLIENT_ID", "")


def _get_client_secret() -> str:
    return os.getenv("CTRADER_CLIENT_SECRET", "")


def _get_redirect_uri() -> str:
    frontend = os.getenv("FRONTEND_URL", "http://localhost:3000")
    return f"{frontend}/settings/broker/ctrader/callback"


def _load_user_ctrader_creds(db: Session, user: User) -> dict:
    """Load the user's stored cTrader credentials (decrypted)."""
    import json
    from app.core.encryption import decrypt_value
    from app.models.settings import UserSettings

    s = db.query(UserSettings).filter(UserSettings.user_id == user.id).first()
    if not s or not s.broker_api_keys:
        return {}
    try:
        creds = json.loads(decrypt_value(s.broker_api_keys))
        return creds.get("ctrader", {})
    except Exception:
        return {}


def _save_user_ctrader_tokens(
    db: Session, user: User, access_token: str, refresh_token: str
):
    """Persist cTrader OAuth tokens to the user's encrypted broker credentials."""
    import json
    from app.core.encryption import encrypt_value, decrypt_value
    from app.models.settings import UserSettings

    s = db.query(UserSettings).filter(UserSettings.user_id == user.id).first()
    if not s:
        s = UserSettings(user_id=user.id)
        db.add(s)
        db.commit()
        db.refresh(s)

    # Load existing broker creds
    creds: dict = {}
    if s.broker_api_keys:
        try:
            creds = json.loads(decrypt_value(s.broker_api_keys))
        except Exception:
            creds = {}

    # Merge tokens into ctrader entry (preserve account_id etc. if already set)
    entry = creds.get("ctrader", {})
    entry["broker"] = "ctrader"
    entry["access_token"] = access_token
    entry["refresh_token"] = refresh_token
    creds["ctrader"] = entry

    s.broker_api_keys = encrypt_value(json.dumps(creds))
    db.commit()
    logger.info("Saved cTrader OAuth tokens for user %s", user.id)


async def _refresh_tokens_if_needed(
    db: Session, user: User, entry: dict
) -> dict:
    """Attempt to refresh cTrader tokens using stored refresh_token.

    Returns updated entry dict with new tokens, or raises HTTPException
    if refresh fails (user must re-authorize).
    """
    refresh_tok = entry.get("refresh_token", "")
    if not refresh_tok:
        raise HTTPException(401, "No refresh token — please re-authorize with cTrader")

    client_id = _get_client_id()
    client_secret = _get_client_secret()

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(_TOKEN_URL, data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_tok,
            "client_id": client_id,
            "client_secret": client_secret,
        })

    if resp.status_code != 200:
        logger.warning("cTrader token refresh failed (%d): %s", resp.status_code, resp.text[:300])
        raise HTTPException(401, "Token refresh failed — please re-authorize with cTrader")

    data = resp.json()
    new_access = data.get("accessToken", "")
    new_refresh = data.get("refreshToken", refresh_tok)

    # Persist refreshed tokens
    _save_user_ctrader_tokens(db, user, new_access, new_refresh)

    entry["access_token"] = new_access
    entry["refresh_token"] = new_refresh
    logger.info("Auto-refreshed cTrader tokens for user %s", user.id)
    return entry


# ── OAuth Endpoints ────────────────────────────────────────


@router.get("/auth-url")
async def get_auth_url(
    user: User = Depends(get_current_user),
):
    """
    Returns the cTrader OAuth2 authorization URL.
    Frontend redirects the user to this URL to grant access.
    """
    client_id = _get_client_id()
    if not client_id:
        raise HTTPException(400, "CTRADER_CLIENT_ID not configured on the server")

    redirect_uri = _get_redirect_uri()
    url = (
        f"{_AUTH_URL}"
        f"?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&scope=trading"
    )
    return {"auth_url": url, "redirect_uri": redirect_uri}


@router.get("/callback")
async def oauth_callback(
    code: str = Query(..., description="Authorization code from cTrader"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Exchange the OAuth2 authorization code for access + refresh tokens.
    Tokens are automatically saved to the user's encrypted broker credentials.
    """
    client_id = _get_client_id()
    client_secret = _get_client_secret()
    redirect_uri = _get_redirect_uri()

    if not client_id or not client_secret:
        raise HTTPException(400, "cTrader OAuth not configured (missing CTRADER_CLIENT_ID/SECRET)")

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(_TOKEN_URL, data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
        })

    if resp.status_code != 200:
        logger.error("cTrader token exchange failed: %s %s", resp.status_code, resp.text[:500])
        raise HTTPException(400, f"Token exchange failed: {resp.text[:200]}")

    data = resp.json()
    access_token = data.get("accessToken", "")
    refresh_tok = data.get("refreshToken", "")

    # Persist tokens to user's encrypted broker credentials
    _save_user_ctrader_tokens(db, user, access_token, refresh_tok)

    return {
        "access_token": access_token,
        "refresh_token": refresh_tok,
        "expires_in": data.get("expiresIn", 0),
        "token_type": data.get("tokenType", "Bearer"),
    }


@router.post("/refresh-token")
async def refresh_ctrader_token(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Refresh an expired cTrader access token using stored refresh token.

    Reads the refresh_token from user's stored credentials — no need to
    pass it explicitly. Updates stored credentials with new tokens.
    """
    entry = _load_user_ctrader_creds(db, user)
    if not entry.get("refresh_token"):
        raise HTTPException(400, "No cTrader refresh token found — complete OAuth flow first")

    updated = await _refresh_tokens_if_needed(db, user, entry)

    return {
        "access_token": updated["access_token"],
        "refresh_token": updated["refresh_token"],
        "expires_in": 0,  # cTrader doesn't always return this on refresh
    }


# ── Account Discovery ─────────────────────────────────────


async def _fetch_accounts_via_ws(access_token: str, client_id: str, client_secret: str) -> list[dict]:
    """Connect to cTrader Open API via WebSocket to list trading accounts.

    Uses the demo host for account discovery (works for both demo and live
    accounts — the Open API returns all accounts linked to the access token
    regardless of which host you connect to).
    """
    import ssl
    import json
    import websockets

    url = f"wss://{_DEMO_WS_HOST}:{_WS_PORT}"
    ssl_ctx = ssl.create_default_context()

    async with websockets.connect(url, ssl=ssl_ctx) as ws:
        # 1. Application auth
        await ws.send(json.dumps({
            "clientMsgId": "auth_1",
            "payloadType": 2100,
            "payload": {
                "clientId": client_id,
                "clientSecret": client_secret,
            },
        }))
        resp = json.loads(await ws.recv())

        # Skip heartbeats
        while resp.get("payloadType") == 51:
            resp = json.loads(await ws.recv())

        if resp.get("payloadType") != 2101:
            error_desc = resp.get("payload", {}).get("description", "Unknown error")
            raise RuntimeError(f"cTrader app auth failed: {error_desc}")

        # 2. Get accounts by access token
        await ws.send(json.dumps({
            "clientMsgId": "accounts_1",
            "payloadType": 2149,
            "payload": {
                "accessToken": access_token,
            },
        }))
        resp = json.loads(await ws.recv())

        # Skip heartbeats
        while resp.get("payloadType") == 51:
            resp = json.loads(await ws.recv())

        # Check for error (e.g. expired token)
        if resp.get("payloadType") == 2142:
            error_payload = resp.get("payload", {})
            raise RuntimeError(
                f"cTrader error {error_payload.get('errorCode', '?')}: "
                f"{error_payload.get('description', 'Unknown')}"
            )

        accounts = resp.get("payload", {}).get("ctidTraderAccount", [])
        return [
            {
                "account_id": str(a.get("ctidTraderAccountId", "")),
                "is_live": a.get("isLive", False),
                "broker_title": a.get("traderLogin", ""),
            }
            for a in accounts
        ]


@router.get("/accounts")
async def list_ctrader_accounts(
    access_token: str = Query(None, description="cTrader OAuth access token (optional — uses stored token if omitted)"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List trading accounts linked to the OAuth access token.

    If access_token is not provided, uses the stored token from user credentials.
    If the stored token is expired, automatically refreshes it before querying.
    """
    client_id = _get_client_id()
    client_secret = _get_client_secret()

    if not client_id or not client_secret:
        raise HTTPException(400, "cTrader OAuth not configured on the server")

    # Use stored token if not provided explicitly
    entry = _load_user_ctrader_creds(db, user)
    if not access_token:
        access_token = entry.get("access_token", "")
    if not access_token:
        raise HTTPException(400, "No access token available — complete OAuth flow first")

    try:
        import websockets  # noqa: F401
    except ImportError:
        raise HTTPException(500, "websockets package not installed")

    # First attempt
    try:
        accounts = await _fetch_accounts_via_ws(access_token, client_id, client_secret)
        return {"accounts": accounts}
    except RuntimeError as e:
        error_msg = str(e)
        # If token expired, try auto-refresh and retry once
        if "CH_ACCESS_TOKEN_INVALID" in error_msg or "INVALID_TOKEN" in error_msg:
            logger.info("cTrader access token expired, attempting refresh...")
            try:
                updated = await _refresh_tokens_if_needed(db, user, entry)
                access_token = updated["access_token"]
                accounts = await _fetch_accounts_via_ws(access_token, client_id, client_secret)
                return {"accounts": accounts}
            except HTTPException:
                raise HTTPException(401, "cTrader token expired and refresh failed — please re-authorize")
            except Exception as e2:
                logger.error("cTrader accounts failed after refresh: %s", e2)
                raise HTTPException(400, f"Failed to list accounts after refresh: {str(e2)}")
        else:
            logger.error("cTrader account list failed: %s", e)
            raise HTTPException(400, f"Failed to list accounts: {str(e)}")
    except Exception as e:
        logger.error("cTrader account list failed: %s", e)
        raise HTTPException(400, f"Failed to list accounts: {str(e)}")


# ── Account Selection ─────────────────────────────────────


@router.post("/save-account")
async def save_ctrader_account(
    account_id: str,
    is_live: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Save the selected cTrader account ID to user credentials.
    Called after the user picks an account from the /accounts list.
    """
    import json
    from app.core.encryption import encrypt_value, decrypt_value
    from app.models.settings import UserSettings

    s = db.query(UserSettings).filter(UserSettings.user_id == user.id).first()
    if not s:
        raise HTTPException(400, "No settings found — complete OAuth flow first")

    creds: dict = {}
    if s.broker_api_keys:
        try:
            creds = json.loads(decrypt_value(s.broker_api_keys))
        except Exception:
            creds = {}

    entry = creds.get("ctrader", {})
    if not entry.get("access_token"):
        raise HTTPException(400, "No cTrader tokens found — complete OAuth flow first")

    entry["account_id"] = account_id
    entry["practice"] = not is_live
    creds["ctrader"] = entry

    s.broker_api_keys = encrypt_value(json.dumps(creds))
    db.commit()

    return {"status": "ok", "account_id": account_id, "is_live": is_live}
