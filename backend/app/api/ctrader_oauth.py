"""
cTrader Open API OAuth2 endpoints.

Handles the OAuth2 authorization flow for cTrader:
  1. GET /auth-url   — returns the redirect URL for user consent
  2. GET /callback   — handles OAuth callback, exchanges code for tokens
  3. GET /accounts   — lists trading accounts linked to the access token
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


def _get_client_id() -> str:
    return os.getenv("CTRADER_CLIENT_ID", "")


def _get_client_secret() -> str:
    return os.getenv("CTRADER_CLIENT_SECRET", "")


def _get_redirect_uri() -> str:
    frontend = os.getenv("FRONTEND_URL", "http://localhost:3000")
    return f"{frontend}/settings/broker/ctrader/callback"


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
        raise HTTPException(400, "CTRADER_CLIENT_ID not configured")

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
    refresh_token: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Refresh an expired cTrader access token. Updates stored credentials."""
    client_id = _get_client_id()
    client_secret = _get_client_secret()

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(_TOKEN_URL, data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        })

    if resp.status_code != 200:
        raise HTTPException(400, f"Token refresh failed: {resp.text[:200]}")

    data = resp.json()
    new_access = data.get("accessToken", "")
    new_refresh = data.get("refreshToken", "")

    # Update stored credentials with new tokens
    _save_user_ctrader_tokens(db, user, new_access, new_refresh)

    return {
        "access_token": new_access,
        "refresh_token": new_refresh,
        "expires_in": data.get("expiresIn", 0),
    }


@router.get("/accounts")
async def list_ctrader_accounts(
    access_token: str = Query(..., description="cTrader OAuth access token"),
    user: User = Depends(get_current_user),
):
    """
    List trading accounts linked to the OAuth access token.
    Uses cTrader Open API to fetch account list.
    """
    client_id = _get_client_id()
    client_secret = _get_client_secret()

    if not client_id or not client_secret:
        raise HTTPException(400, "cTrader OAuth not configured")

    # Connect via WebSocket briefly to get accounts
    try:
        import ssl
        import json
        import websockets

        url = "wss://demo.ctraderapi.com:5035"
        ssl_ctx = ssl.create_default_context()

        async with websockets.connect(url, ssl=ssl_ctx) as ws:
            # App auth
            await ws.send(json.dumps({
                "clientMsgId": "auth_1",
                "payloadType": 2100,
                "payload": {
                    "clientId": client_id,
                    "clientSecret": client_secret,
                },
            }))
            resp = json.loads(await ws.recv())
            if resp.get("payloadType") != 2101:
                raise HTTPException(400, "cTrader app auth failed")

            # Get accounts by token
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

            accounts = resp.get("payload", {}).get("ctidTraderAccount", [])
            return {
                "accounts": [
                    {
                        "account_id": str(a.get("ctidTraderAccountId", "")),
                        "is_live": a.get("isLive", False),
                        "broker_title": a.get("traderLogin", ""),
                    }
                    for a in accounts
                ]
            }
    except ImportError:
        raise HTTPException(500, "websockets package not installed")
    except Exception as e:
        logger.error("cTrader account list failed: %s", e)
        raise HTTPException(400, f"Failed to list accounts: {str(e)}")


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
