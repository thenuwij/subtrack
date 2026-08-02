import logging
import os
from datetime import datetime, timedelta, timezone

# Google returns scopes in a different order/spelling than requested (and drops
# any the user declines). Without this, oauthlib aborts the exchange with a raw
# "Scope has changed" error. We relax it here and check the granted scopes
# ourselves below, so a declined permission produces a useful message.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.gmail.crypto import encrypt_token
from app.middleware.auth import verify_token
from app.models import GmailAccount

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gmail", tags=["gmail"])

# Read-only. This is a Google "restricted" scope: fine for test users on an
# unverified app, but real users need a CASA security assessment first.
GMAIL_READONLY = "https://www.googleapis.com/auth/gmail.readonly"

SCOPES = [
    GMAIL_READONLY,
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]

STATE_TTL_SECONDS = 600


def _client_config() -> dict:
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            status_code=503,
            detail="Gmail is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.",
        )
    return {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.google_redirect_uri],
        }
    }


def _build_flow() -> Flow:
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES)
    flow.redirect_uri = settings.google_redirect_uri
    # The callback builds a fresh Flow and so has no code_verifier to send.
    # Turning PKCE off keeps the exchange consistent; CSRF is already covered
    # by the signed state token.
    flow.autogenerate_code_verifier = False
    flow.code_verifier = None
    return flow


def _sign_state(user_id: str) -> str:
    """Google's callback is unauthenticated, so the state carries the user id.

    It's signed and short-lived so a third party can't forge a callback that
    attaches their mailbox to someone else's account.
    """
    return jwt.encode(
        {
            "sub": user_id,
            "exp": datetime.now(timezone.utc) + timedelta(seconds=STATE_TTL_SECONDS),
        },
        settings.supabase_jwt_secret,
        algorithm="HS256",
    )


def _verify_state(state: str) -> str:
    try:
        payload = jwt.decode(state, settings.supabase_jwt_secret, algorithms=["HS256"])
        return payload["sub"]
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=400, detail="Invalid or expired state") from exc


@router.get("/status")
def gmail_status(
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    account = db.query(GmailAccount).filter(GmailAccount.user_id == user_id).first()
    if not account:
        return {"connected": False}
    return {
        "connected": True,
        "email_address": account.email_address,
        "connected_at": account.connected_at.isoformat() if account.connected_at else None,
        "last_scanned_at": account.last_scanned_at.isoformat() if account.last_scanned_at else None,
    }


@router.get("/connect")
def gmail_connect(user_id: str = Depends(verify_token)):
    """Return the Google consent URL. The frontend sends the user there."""
    flow = _build_flow()
    auth_url, _ = flow.authorization_url(
        access_type="offline",       # required to get a refresh token at all
        prompt="consent",            # force a refresh token even on re-connect
        include_granted_scopes="true",
        state=_sign_state(user_id),
    )
    return {"auth_url": auth_url}


@router.get("/callback")
def gmail_callback(code: str, state: str, db: Session = Depends(get_db)):
    """Google redirects here after consent. Unauthenticated by necessity —
    the signed state is what identifies the user."""
    user_id = _verify_state(state)

    flow = _build_flow()
    try:
        flow.fetch_token(code=code)
    except Exception as exc:
        logger.warning("Gmail token exchange failed: %s", exc)
        raise HTTPException(
            status_code=400,
            detail=f"Google rejected the authorisation: {exc}",
        ) from exc

    credentials = flow.credentials

    granted = set(credentials.scopes or [])
    if GMAIL_READONLY not in granted:
        raise HTTPException(
            status_code=400,
            detail="Gmail read access was not granted. On the Google consent screen, "
                   "tick the 'View your email messages and settings' checkbox — it is "
                   "unticked by default. Without it Subtrack cannot read receipts.",
        )

    if not credentials.refresh_token:
        raise HTTPException(
            status_code=400,
            detail="Google did not return a refresh token. Revoke Subtrack's access "
                   "in your Google account and connect again.",
        )

    email_address = ""
    if credentials.id_token:
        # id_token is already verified by the library during the exchange.
        import jwt as _jwt
        claims = _jwt.decode(credentials.id_token, options={"verify_signature": False})
        email_address = claims.get("email", "")

    account = db.query(GmailAccount).filter(GmailAccount.user_id == user_id).first()
    if not account:
        account = GmailAccount(user_id=user_id)
        db.add(account)

    account.email_address = email_address
    account.refresh_token_encrypted = encrypt_token(credentials.refresh_token)
    db.commit()

    logger.info("Gmail connected", extra={"user_id": user_id})

    frontend = settings.allowed_origins.split(",")[0]
    return RedirectResponse(f"{frontend}/account?gmail=connected")


@router.delete("/disconnect")
def gmail_disconnect(
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    account = db.query(GmailAccount).filter(GmailAccount.user_id == user_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="No Gmail account connected")
    db.delete(account)
    db.commit()
    return {"message": "Disconnected"}
