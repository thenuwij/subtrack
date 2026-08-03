import logging
import os
import re
from datetime import datetime, timedelta, timezone

# Google returns scopes in a different order/spelling than requested (and drops
# any the user declines). Without this, oauthlib aborts the exchange with a raw
# "Scope has changed" error. We relax it here and check the granted scopes
# ourselves below, so a declined permission produces a useful message.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

import jwt
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal, get_db
from app.gmail.crypto import decrypt_token, encrypt_token
from app.middleware.auth import verify_token
from app.models import (
    DetectedSubscription,
    DetectionStatus,
    GmailAccount,
    Subscription,
)

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
        "scan_status": account.scan_status or "idle",
        "scan_error": account.scan_error,
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


AMOUNT_TOLERANCE = 0.05  # ignore sub-5-cent differences (rounding, FX wobble)

SCAN_MONTHS = 6      # deep enough for quarterly and annual bills


def _norm(text: str) -> str:
    """Loose comparison key — case, punctuation and spacing all vary."""
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _billed_amount(sub: Subscription) -> float:
    """What the biller charges, which is what a receipt shows. For a shared
    bill that's the whole cost, not this user's share."""
    return sub.full_amount if sub.full_amount is not None else sub.amount


def _same_price(sub: Subscription, found) -> bool:
    return abs(_billed_amount(sub) - found.amount) <= AMOUNT_TOLERANCE


def _match_subscription(subs: list[Subscription], found) -> Subscription | None:
    """Find the tracked subscription this detection refers to.

    Identity has to survive the analyzer rewording things between scans, so the
    stable source key is tried first. Name matching is only a fallback for
    subscriptions added by hand, and is deliberately narrow: it also requires
    the same billing cycle, so Apple Music and iCloud don't collapse into each
    other just because both are "Apple".
    """
    key = (found.product_key or "").strip().lower()
    if key:
        for sub in subs:
            if sub.source_key == key and sub.source_domain == found.sender_domain:
                return sub

    # Subscriptions added by hand — or approved before product keys existed —
    # have nothing stable to match on, so fall back to what they bill.
    unkeyed = [s for s in subs if not s.source_key]

    name = _norm(found.merchant)
    by_name = [s for s in unkeyed if _norm(s.name) == name and s.cycle == found.cycle]
    if len(by_name) == 1:
        return by_name[0]
    if len(by_name) > 1:
        # Two subscriptions share a name (a generic "Apple" for two different
        # products). Only the amount can tell them apart; if it can't, do
        # nothing rather than update the wrong one.
        exact = [s for s in by_name if _same_price(s, found)]
        return exact[0] if len(exact) == 1 else None

    # A generic existing name ("Apple") won't match a specific detection
    # ("Apple Music"), but an identical amount and cycle almost certainly means
    # the same bill. Only accept it when exactly one candidate fits.
    same_bill = [s for s in unkeyed if s.cycle == found.cycle and _same_price(s, found)]
    return same_bill[0] if len(same_bill) == 1 else None


def _match_detection(rows: list[DetectedSubscription], found) -> DetectedSubscription | None:
    """Find an earlier detection for the same bill, so a rescan updates it
    rather than stacking near-duplicates."""
    key = (found.product_key or "").strip().lower()
    if key:
        for row in rows:
            if (row.product_key or "").strip().lower() == key \
                    and row.sender_domain == found.sender_domain:
                return row

    for row in rows:
        if row.sender_domain != found.sender_domain:
            continue
        if _norm(row.merchant) == _norm(found.merchant):
            return row
        # Rows created before product keys existed, and rows the analyzer has
        # since reworded, can only be recognised by what they bill: same sender,
        # same amount, same cycle is the same bill in practice.
        if not (row.product_key or "").strip() \
                and row.cycle == found.cycle \
                and abs(row.amount - found.amount) <= AMOUNT_TOLERANCE:
            return row
        # Same bill after a price change: the old amount is what it used to be.
        if found.previous_amount is not None \
                and abs(row.amount - found.previous_amount) <= AMOUNT_TOLERANCE \
                and row.status == DetectionStatus.pending:
            return row
    return None


def _run_scan(user_id: str):
    """The scan itself. Runs as a background task with its own DB session —
    the request that started it has long since returned."""
    from datetime import datetime

    from app.gmail.analyzer import analyze
    from app.gmail.scanner import scan

    db = SessionLocal()
    try:
        account = db.query(GmailAccount).filter(GmailAccount.user_id == user_id).first()
        if not account:
            return

        try:
            candidates = scan(decrypt_token(account.refresh_token_encrypted),
                              months=SCAN_MONTHS, max_messages=400)
            detected = analyze(candidates)
        except Exception as exc:
            logger.error("Scan failed for %s: %s", user_id, exc)
            account.scan_status = "error"
            account.scan_error = str(exc)[:500]
            db.commit()
            return

        subscriptions = db.query(Subscription).filter(
            Subscription.user_id == user_id
        ).all()

        existing_detections = db.query(DetectedSubscription).filter(
            DetectedSubscription.user_id == user_id
        ).all()

        for found in detected:
            tracked = _match_subscription(subscriptions, found)
            previous = _match_detection(existing_detections, found)

            # Dismissed means "stop suggesting this" — a rescan must not nag.
            # Approved means it already became a subscription; changes to it are
            # handled through the tracked-subscription branch below.
            if previous is not None and previous.status != DetectionStatus.pending:
                if tracked is None or _same_price(tracked, found):
                    continue

            existing_sub_id = None
            if tracked is not None:
                if _same_price(tracked, found) and tracked.is_active:
                    continue   # already tracked at this price — nothing to review
                existing_sub_id = tracked.id

            if previous is not None and previous.status == DetectionStatus.pending:
                row = previous          # refresh the pending suggestion in place
            else:
                row = DetectedSubscription(user_id=user_id)
                db.add(row)
                existing_detections.append(row)

            row.merchant = found.merchant
            row.sender_domain = found.sender_domain
            row.product_key = (found.product_key or "").strip().lower()
            row.category = found.category
            row.cycle = found.cycle
            row.amount = found.amount
            row.currency = found.currency
            row.previous_amount = found.previous_amount
            row.cancelled = found.cancelled
            row.confidence = found.confidence
            row.charge_count = found.charge_count
            row.existing_subscription_id = existing_sub_id
            row.status = DetectionStatus.pending
            row.resolved_at = None

        account.scan_status = "done"
        account.scan_error = None
        account.last_scanned_at = datetime.utcnow()
        db.commit()
        logger.info("Scan complete for %s: %d candidates", user_id, len(detected))
    finally:
        db.close()


@router.post("/scan")
def start_scan(
    background: BackgroundTasks,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    account = db.query(GmailAccount).filter(GmailAccount.user_id == user_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="No Gmail account connected")
    if account.scan_status == "running":
        return {"status": "running"}

    account.scan_status = "running"
    account.scan_error = None
    db.commit()

    background.add_task(_run_scan, user_id)
    return {"status": "running"}


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
