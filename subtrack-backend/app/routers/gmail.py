import hashlib
import logging
import os
import re
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import BoundedSemaphore
from urllib.parse import urlencode
from uuid import uuid4

# Google returns scopes in a different order/spelling than requested (and drops
# any the user declines). Without this, oauthlib aborts the exchange with a raw
# "Scope has changed" error. We relax it here and check the granted scopes
# ourselves below, so a declined permission produces a useful message.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from google.auth.exceptions import GoogleAuthError, RefreshError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token as google_id_token
from google_auth_oauthlib.flow import Flow
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal, get_db
from app.gmail.crypto import (
    TokenUndecryptable,
    check_configured as check_token_encryption_configured,
    decrypt_token,
    encrypt_token,
)
from app.middleware.auth import verify_token
from app.models import (
    BillingCycle,
    DetectedSubscription,
    DetectionStatus,
    GmailAccount,
    GmailOAuthState,
    PaymentStatus,
    Subscription,
)
from app.services.gmail_access import revoke_encrypted_refresh_token
from app.services.recurrence import Cadence, cadence_for, legacy_cycle_for, utc_naive

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
OAUTH_CLEANUP_LIMIT = 100
FRONTEND_GMAIL_CALLBACK_PATH = "/auth/gmail/callback"
GOOGLE_IDENTITY_TIMEOUT_SECONDS = 10
GOOGLE_TOKEN_EXCHANGE_TIMEOUT_SECONDS = 20


def gmail_is_configured() -> bool:
    configured = bool(
        settings.google_client_id
        and settings.google_client_secret
        and settings.google_redirect_uri
        and settings.token_encryption_key
    )
    if not configured:
        return False
    try:
        check_token_encryption_configured()
    except RuntimeError:
        return False
    return True


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
            "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.google_redirect_uri],
        }
    }


def _build_flow(
    *,
    state: str | None = None,
    code_verifier: str | None = None,
) -> Flow:
    flow = Flow.from_client_config(
        _client_config(),
        scopes=SCOPES,
        state=state,
        code_verifier=code_verifier,
        autogenerate_code_verifier=False,
    )
    flow.redirect_uri = settings.google_redirect_uri
    return flow


def _state_hash(state: str) -> str:
    return hashlib.sha256(state.encode("ascii")).hexdigest()


def _new_oauth_secret(size: int) -> str:
    """RFC 7636-compatible base64url entropy without padding."""
    return secrets.token_urlsafe(size)


def _cleanup_oauth_states(db: Session, now: datetime) -> None:
    """Bound opportunistic cleanup so connect latency cannot grow with history."""
    expired = db.query(GmailOAuthState).filter(
        GmailOAuthState.expires_at <= now,
    ).order_by(GmailOAuthState.expires_at).limit(OAUTH_CLEANUP_LIMIT).all()
    for row in expired:
        db.delete(row)


def _replace_user_oauth_state(
    db: Session,
    user_id: str,
    *,
    state: str,
    code_verifier: str,
) -> None:
    now = _utcnow()
    _cleanup_oauth_states(db, now)

    # The newest Connect click wins. Keeping one active flow per user prevents
    # an authenticated client from accumulating state rows and makes old tabs
    # fail closed with a clean retry.
    stale_for_user = db.query(GmailOAuthState).filter(
        GmailOAuthState.user_id == user_id,
    ).limit(OAUTH_CLEANUP_LIMIT).all()
    for row in stale_for_user:
        db.delete(row)

    db.add(GmailOAuthState(
        state_hash=_state_hash(state),
        user_id=user_id,
        code_verifier_encrypted=encrypt_token(code_verifier),
        expires_at=now + timedelta(seconds=STATE_TTL_SECONDS),
    ))
    db.commit()


def _consume_oauth_state(db: Session, user_id: str, state: str) -> str:
    """Verify and irreversibly consume state before any external token call.

    The row lock serializes replays. Deleting and committing before the Google
    exchange means even a timeout or invalid code cannot make the state usable
    a second time; the safe recovery is always a fresh Connect click.
    """
    row = db.query(GmailOAuthState).filter(
        GmailOAuthState.state_hash == _state_hash(state),
    ).with_for_update().first()
    if not row:
        raise HTTPException(
            status_code=400,
            detail="This Gmail connection request is invalid or has already been used. Start again.",
        )
    if row.user_id != user_id:
        raise HTTPException(
            status_code=403,
            detail="This Gmail connection request belongs to a different signed-in user.",
        )
    if row.expires_at <= _utcnow():
        db.delete(row)
        db.commit()
        raise HTTPException(
            status_code=400,
            detail="This Gmail connection request expired. Start again.",
        )

    try:
        verifier = decrypt_token(row.code_verifier_encrypted)
    except TokenUndecryptable as exc:
        db.delete(row)
        db.commit()
        raise HTTPException(
            status_code=400,
            detail="This Gmail connection request cannot be completed. Start again.",
        ) from exc

    db.delete(row)
    db.commit()
    return verifier


def _scope_set(value) -> set[str]:
    if isinstance(value, str):
        return set(value.split())
    return {str(item) for item in (value or [])}


class GmailIdentityError(Exception):
    """The token response did not contain a verified Google mailbox identity."""


def _bounded_google_request(url, method="GET", body=None, headers=None, **kwargs):
    """Keep Google's certificate lookup from tying up a request worker."""
    requested_timeout = kwargs.get("timeout")
    try:
        requested_timeout = float(requested_timeout)
    except (TypeError, ValueError):
        requested_timeout = GOOGLE_IDENTITY_TIMEOUT_SECONDS
    kwargs["timeout"] = max(
        0.1,
        min(requested_timeout, GOOGLE_IDENTITY_TIMEOUT_SECONDS),
    )
    return GoogleAuthRequest()(url, method=method, body=body, headers=headers, **kwargs)


def _verify_google_identity(raw_id_token: str | None) -> str:
    if not raw_id_token:
        raise GmailIdentityError("missing ID token")
    try:
        claims = google_id_token.verify_oauth2_token(
            raw_id_token,
            _bounded_google_request,
            settings.google_client_id,
            clock_skew_in_seconds=30,
        )
    except (GoogleAuthError, ValueError) as exc:
        raise GmailIdentityError("invalid ID token") from exc

    if claims.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}:
        raise GmailIdentityError("invalid issuer")
    if claims.get("email_verified") is not True:
        raise GmailIdentityError("unverified email")
    if not isinstance(claims.get("sub"), str) or not claims["sub"]:
        raise GmailIdentityError("missing subject")

    email = claims.get("email")
    if not isinstance(email, str):
        raise GmailIdentityError("missing email")
    email = email.strip()
    if not email or len(email) > 254 or "@" not in email \
            or any(ord(char) < 33 for char in email):
        raise GmailIdentityError("invalid email")
    return email


def _frontend_oauth_redirect(params: dict[str, str]) -> RedirectResponse:
    target = f"{settings.frontend_url}{FRONTEND_GMAIL_CALLBACK_PATH}"
    if params:
        # The authorization code and one-time state are credentials. A URL
        # fragment reaches browser JavaScript but is never sent to Vercel,
        # proxies, analytics, or subsequent sites in the Referer header.
        target = f"{target}#{urlencode(params)}"
    return RedirectResponse(
        target,
        status_code=303,
        headers={
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "Referrer-Policy": "no-referrer",
        },
    )


@router.get("/status")
def gmail_status(
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    account = db.query(GmailAccount).filter(GmailAccount.user_id == user_id).first()
    if not account:
        return {"connected": False, "configured": gmail_is_configured()}

    # A scan that died without cleaning up would otherwise report "running"
    # here for the full staleness window: the user stares at a spinner with
    # the scan button disabled and no error, ever. Flip it to a visible,
    # retryable failure the moment it's recognisably dead.
    if account.scan_status == "running" and _scan_is_stale(account):
        logger.warning("Marking stale scan as failed for %s", user_id)
        account.scan_status = "error"
        account.scan_error = INTERRUPTED_MESSAGE
        account.scan_stage = None
        account.scan_message = None
        db.commit()

    return {
        "connected": True,
        "configured": gmail_is_configured(),
        "email_address": account.email_address,
        "connected_at": account.connected_at.isoformat() if account.connected_at else None,
        "last_scanned_at": account.last_scanned_at.isoformat() if account.last_scanned_at else None,
        "scan_status": account.scan_status or "idle",
        "scan_error": account.scan_error,
        "scan_stage": account.scan_stage,
        "scan_processed": account.scan_processed or 0,
        "scan_total": account.scan_total or 0,
        "scan_partial": bool(account.scan_partial),
        "scan_message": account.scan_message,
    }


@router.get("/connect")
def gmail_connect(
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Create a short-lived, user-bound PKCE flow and return Google's URL."""
    if not gmail_is_configured():
        raise HTTPException(
            status_code=503,
            detail="Gmail is not configured for this deployment.",
        )
    state = _new_oauth_secret(32)
    code_verifier = _new_oauth_secret(64)
    flow = _build_flow(state=state, code_verifier=code_verifier)
    auth_url, _ = flow.authorization_url(
        access_type="offline",       # required to get a refresh token at all
        prompt="consent",            # force a refresh token even on re-connect
        include_granted_scopes="true",
        state=state,
    )
    _replace_user_oauth_state(
        db,
        user_id,
        state=state,
        code_verifier=code_verifier,
    )
    return {"auth_url": auth_url}


@router.get("/callback")
def gmail_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    """Non-mutating bridge to an authenticated frontend completion page."""
    valid_state = bool(
        state
        and 32 <= len(state) <= 256
        and re.fullmatch(r"[A-Za-z0-9_-]+", state)
    )
    if error:
        safe_error = (
            error
            if re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", error)
            else "oauth_error"
        )
        params = {"error": safe_error}
        if valid_state:
            params["state"] = state
        return _frontend_oauth_redirect(params)

    valid_code = bool(
        code
        and len(code) <= 4096
        and not any(ord(char) < 33 for char in code)
    )
    if not valid_state or not valid_code:
        return _frontend_oauth_redirect({"error": "invalid_oauth_response"})
    return _frontend_oauth_redirect({"code": code, "state": state})


class GmailOAuthComplete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(
        min_length=1,
        max_length=4096,
        pattern=r"^[\x21-\x7e]+$",
    )
    state: str = Field(
        min_length=32,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]+$",
    )


@router.post("/oauth/complete")
def gmail_oauth_complete(
    payload: GmailOAuthComplete,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Consume one-time state, exchange with PKCE, then link the mailbox."""
    if not gmail_is_configured():
        raise HTTPException(
            status_code=503,
            detail="Gmail is not configured for this deployment.",
        )
    code_verifier = _consume_oauth_state(db, user_id, payload.state)
    flow = _build_flow(state=payload.state, code_verifier=code_verifier)

    try:
        flow.fetch_token(
            code=payload.code,
            timeout=GOOGLE_TOKEN_EXCHANGE_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        # Provider errors can contain request details. Log only the exception
        # class, never the code, state, verifier, or response body.
        logger.warning(
            "Gmail token exchange failed for %s (%s)",
            user_id,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=400,
            detail="Google could not complete this connection. Start again.",
        ) from exc

    try:
        credentials = flow.credentials
    except (GoogleAuthError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail="Google returned an invalid connection response. Start again.",
        ) from exc

    # Per OAuth, an omitted response scope means it equals the requested set;
    # when Google returns a reduced set, granted_scopes is authoritative. An
    # empty value is the omitted case rather than "nothing was granted" —
    # Google does not issue a token at all when the user grants nothing — so it
    # falls back too. Reading it literally produced a false refusal on a
    # connection that had actually succeeded.
    reported = _scope_set(credentials.granted_scopes)
    granted = reported or _scope_set(credentials.scopes)
    if GMAIL_READONLY not in granted:
        # Gmail read access is a Google "restricted" scope, so consent renders
        # it as its own checkbox that starts unticked. Continuing past it
        # returns a perfectly valid token that cannot read any mail, which is
        # why this is the most common first-attempt failure. Name the checkbox
        # rather than saying "allow access" — the user has to find that box.
        raise HTTPException(
            status_code=422,
            detail=(
                "Google did not grant permission to read your email. On the "
                "consent screen there is a tickbox for viewing your email "
                "messages — it starts unticked, and Subtrack cannot scan "
                "without it. Connect again and tick that box."
            ),
        )

    if not credentials.refresh_token:
        raise HTTPException(
            status_code=422,
            detail=(
                "Google did not return long-lived access. Remove Subtrack from "
                "your Google account permissions, then connect again."
            ),
        )

    try:
        email_address = _verify_google_identity(credentials.id_token)
    except GmailIdentityError as exc:
        logger.warning(
            "Gmail identity verification failed for %s (%s)",
            user_id,
            str(exc),
        )
        raise HTTPException(
            status_code=400,
            detail="Google did not return a verified mailbox identity. Start again.",
        ) from exc

    account = db.query(GmailAccount).filter(
        GmailAccount.user_id == user_id,
    ).with_for_update().first()
    if not account:
        account = GmailAccount(user_id=user_id)
        db.add(account)

    account.email_address = email_address
    account.refresh_token_encrypted = encrypt_token(credentials.refresh_token)
    db.commit()

    logger.info("Gmail connected", extra={"user_id": user_id})
    return {"connected": True, "email_address": email_address}


AMOUNT_TOLERANCE = 0.05  # ignore sub-5-cent differences (rounding, FX wobble)

# Every scan deliberately looks back three months to keep inbox and model work
# bounded. Slow cadences may have too little spacing evidence in that window,
# so the analyzer must use explicit wording or return unknown for user review.
SCAN_MONTHS = 3

# Scans stop accepting work at 105 seconds. The remaining 15 seconds before the
# two-minute UX promise cover the last database commit and the frontend's next
# poll. A heartbeat older than two minutes therefore cannot be legitimate.
SCAN_TIME_LIMIT_SECONDS = 105
SCAN_FETCH_BUDGET_SECONDS = 35
STALE_SCAN_MINUTES = 2
MAX_SCAN_MESSAGES = 300

# Gmail and model calls are network-bound but each scan still owns a database
# session and several HTTP connections. A dedicated bounded pool prevents a
# burst of scans from exhausting FastAPI's request workers. Horizontal Render
# instances each add two more scan slots.
MAX_CONCURRENT_SCANS = 2
_scan_executor = ThreadPoolExecutor(
    max_workers=MAX_CONCURRENT_SCANS,
    thread_name_prefix="gmail-scan",
)
_scan_slots = BoundedSemaphore(MAX_CONCURRENT_SCANS)

INTERRUPTED_MESSAGE = (
    "The scan was interrupted before it finished. "
    "Anything already found is saved — run it again to finish."
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _norm(text: str) -> str:
    """Loose comparison key — case, punctuation and spacing all vary."""
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _billed_amount(sub: Subscription) -> float:
    """What the biller charges, which is what a receipt shows. For a shared
    bill that's the whole cost, not this user's share."""
    return sub.full_amount if sub.full_amount is not None else sub.amount


def _same_price(sub: Subscription, found) -> bool:
    return abs(_billed_amount(sub) - found.amount) <= AMOUNT_TOLERANCE


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


def _cadence_signature(item, *, allow_legacy: bool = True) -> tuple[str, int] | None:
    """Return a known cadence without treating a compatibility cycle as proof.

    Detected rows keep a legacy non-null ``cycle`` for rolling-deploy safety.
    Their explicit unknown confidence must therefore win over that placeholder.
    Tracked subscriptions have no confidence field, so pre-migration rows may
    still fall back to their historical weekly/monthly/yearly value.
    """
    confidence = _enum_value(getattr(item, "cadence_confidence", None))
    if confidence == "unknown":
        return None

    unit = _enum_value(getattr(item, "interval_unit", None))
    count = getattr(item, "interval_count", None)
    if bool(unit) != bool(count):
        return None
    if unit and count:
        try:
            cadence = Cadence(str(unit), int(count))
        except (TypeError, ValueError):
            return None
        return cadence.unit, cadence.count

    cycle = getattr(item, "cycle", None)
    if not allow_legacy or cycle is None:
        return None
    try:
        cadence = cadence_for(cycle)
    except ValueError:
        return None
    return cadence.unit, cadence.count


def _same_cadence(left, right) -> bool:
    left_signature = _cadence_signature(left)
    right_signature = _cadence_signature(right)
    return bool(left_signature and right_signature and left_signature == right_signature)


def _match_subscription(subs: list[Subscription], found) -> Subscription | None:
    """Find the tracked subscription this detection refers to.

    Identity has to survive the analyzer rewording things between scans, so the
    stable source key is tried first. Name matching is only a fallback for
    subscriptions added by hand, and is deliberately narrow: it also requires
    the same known cadence, so Apple Music and iCloud don't collapse into each
    other just because both are "Apple". An unknown detected cadence is never
    silently interpreted as monthly for matching.
    """
    key = (found.product_key or "").strip().lower()
    if key:
        for sub in subs:
            if (sub.source_key or "").strip().lower() == key \
                    and (sub.source_domain or "").strip().lower() \
                    == (found.sender_domain or "").strip().lower():
                return sub

    # Subscriptions added by hand — or approved before product keys existed —
    # have nothing stable to match on, so fall back to what they bill.
    unkeyed = [s for s in subs if not s.source_key]

    if _cadence_signature(found) is None:
        return None

    name = _norm(found.merchant)
    by_name = [s for s in unkeyed if _norm(s.name) == name and _same_cadence(s, found)]
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
    same_bill = [s for s in unkeyed if _same_cadence(s, found) and _same_price(s, found)]
    return same_bill[0] if len(same_bill) == 1 else None


def _match_detection(rows: list[DetectedSubscription], found) -> DetectedSubscription | None:
    """Find an earlier detection for the same bill, so a rescan updates it
    rather than stacking near-duplicates."""
    key = (found.product_key or "").strip().lower()
    if key:
        for row in rows:
            if (row.product_key or "").strip().lower() == key \
                    and (row.sender_domain or "").strip().lower() \
                    == (found.sender_domain or "").strip().lower():
                return row

    for row in rows:
        if (row.sender_domain or "").strip().lower() \
                != (found.sender_domain or "").strip().lower():
            continue
        row_key = (row.product_key or "").strip().lower()
        # Stable, distinct product identities are authoritative. Apple Music
        # and iCloud can share sender, amount, cadence, and even a generic name.
        if key and row_key and key != row_key:
            continue
        if _norm(row.merchant) == _norm(found.merchant):
            return row
        # Rows created before product keys existed, and rows the analyzer has
        # since reworded, can only be recognised by what they bill: same sender,
        # same amount, same cycle is the same bill in practice.
        if not row_key \
                and _same_cadence(row, found) \
                and abs(row.amount - found.amount) <= AMOUNT_TOLERANCE:
            return row
        # Same bill after a price change: the old amount is what it used to be.
        if found.previous_amount is not None \
                and not row_key \
                and _same_cadence(row, found) \
                and abs(row.amount - found.previous_amount) <= AMOUNT_TOLERANCE \
                and row.status == DetectionStatus.pending:
            return row
    return None


def _has_material_change(tracked: Subscription, found, *, trial_changed: bool) -> bool:
    found_cadence = _cadence_signature(found)
    tracked_cadence = _cadence_signature(tracked)
    cadence_changed = bool(found_cadence and found_cadence != tracked_cadence)
    tracked_status = str(_enum_value(getattr(tracked, "status", "active")))
    cancellation_changed = bool(
        found.cancelled
        and (
            tracked.is_active
            or tracked_status not in {
                PaymentStatus.cancelled.value,
                PaymentStatus.ended.value,
            }
        )
    )
    reactivation_changed = bool(
        not found.cancelled and not tracked.is_active and found.charge_count > 0
    )
    amount_type_changed = str(_enum_value(getattr(tracked, "amount_type", "fixed"))) \
        != str(_enum_value(getattr(found, "amount_type", "fixed")))
    due_date_added = bool(found.next_due and not tracked.next_due)
    return bool(
        trial_changed
        or cancellation_changed
        or reactivation_changed
        or cadence_changed
        or amount_type_changed
        or due_date_added
    )


def _scan_is_stale(account: GmailAccount) -> bool:
    """Has a scan been marked running for longer than one could possibly take?

    Without this a single crashed scan locks the user out permanently: the
    endpoint sees "running" and declines to start another, forever.
    """
    now = _utcnow()
    if account.scan_started_at and (
        now - account.scan_started_at
        >= timedelta(seconds=SCAN_TIME_LIMIT_SECONDS + 15)
    ):
        # A runaway worker must not keep the UI spinning beyond the public
        # two-minute promise merely by continuing to write heartbeats.
        return True
    heartbeat = account.scan_heartbeat_at or account.scan_started_at
    if heartbeat is None:
        return True      # pre-dates the timestamp, or never recorded — don't stay stuck
    return now - heartbeat > timedelta(minutes=STALE_SCAN_MINUTES)


def _apply_detections(db, user_id, subscriptions, existing_detections, detected):
    """Fold a batch of analyzer results into the review queue.

    Mutates `existing_detections` in place as rows are added, so calling this
    per batch is equivalent to one pass over everything at the end.
    """
    for found in detected:
        tracked = _match_subscription(subscriptions, found)
        previous = _match_detection(existing_detections, found)

        # Dismissed means "stop suggesting this" — a rescan must not nag.
        # Approved means it already became a subscription; changes to it are
        # handled through the tracked-subscription branch below.
        trial_changed = bool(
            tracked
            and (
                (
                    found.trial_ends_at
                    and (
                        tracked.trial_ends_at is None
                        or utc_naive(tracked.trial_ends_at)
                        != utc_naive(found.trial_ends_at)
                    )
                )
                # Once Gmail has evidence of a successful charge, an existing
                # free trial has converted even if the price stayed exactly the
                # same as the post-trial price we already stored.  Surface that
                # transition for review so approval can clear the stale trial
                # badge and automatic cancellation reminder.
                or (
                    tracked.trial_ends_at is not None
                    and found.trial_ends_at is None
                    and found.charge_count > 0
                )
            )
        )
        material_change = bool(
            tracked and _has_material_change(
                tracked,
                found,
                trial_changed=trial_changed,
            )
        )
        if previous is not None \
                and previous.status != DetectionStatus.pending \
                and (tracked is None or (_same_price(tracked, found) and not material_change)):
            continue

        existing_sub_id = None
        if tracked is not None:
            if _same_price(tracked, found) and not material_change:
                continue   # already tracked at this price — nothing to review
            existing_sub_id = tracked.id

        refreshing_pending = bool(
            previous is not None and previous.status == DetectionStatus.pending
        )
        if refreshing_pending:
            row = previous          # refresh the pending suggestion in place
        else:
            row = DetectedSubscription(user_id=user_id)
            db.add(row)
            existing_detections.append(row)

        row.merchant = found.merchant
        row.sender_domain = found.sender_domain
        row.product_key = (
            (found.product_key or "").strip().lower()
            or ((row.product_key or "").strip().lower() if refreshing_pending else "")
        )
        row.category = found.category
        found_cadence = _cadence_signature(found)
        if found_cadence is None:
            # ``cycle`` is non-null only for old instances sharing this table.
            # Confidence prevents this placeholder from ever becoming monthly
            # evidence or being approved without a user correction.
            existing_cadence = _cadence_signature(row) if refreshing_pending else None
            if existing_cadence is None:
                row.cycle = BillingCycle.monthly
                row.interval_unit = None
                row.interval_count = None
                row.cadence_confidence = "unknown"
                row.cadence_evidence = None
        else:
            row.interval_unit, row.interval_count = found_cadence
            row.cycle = legacy_cycle_for(*found_cadence)
            row.cadence_confidence = found.cadence_confidence
            row.cadence_evidence = found.cadence_evidence
        row.amount_type = (
            "variable"
            if _enum_value(getattr(row, "amount_type", None)) == "variable"
            or found.amount_type == "variable"
            else "fixed"
        )
        row.amount = found.amount
        row.currency = found.currency.upper()
        row.previous_amount = found.previous_amount
        row.cancelled = found.cancelled
        row.confidence = found.confidence
        row.charge_count = found.charge_count
        row.trial_ends_at = utc_naive(found.trial_ends_at) if found.trial_ends_at else None
        if found.cancelled:
            row.next_due = None
            row.due_date_confidence = "unknown"
            row.due_date_evidence = None
        elif found.next_due is not None:
            row.next_due = utc_naive(found.next_due)
            row.due_date_confidence = found.due_date_confidence
            row.due_date_evidence = found.due_date_evidence
        elif not refreshing_pending:
            row.next_due = None
            row.due_date_confidence = "unknown"
            row.due_date_evidence = None
        row.existing_subscription_id = existing_sub_id
        row.status = DetectionStatus.pending
        row.resolved_at = None


class ScanSuperseded(Exception):
    """The mailbox was disconnected or a newer run took ownership."""


def _run_scan(user_id: str, run_id: str):
    """Run one bounded scan in the dedicated executor.

    Partial findings are committed after every model batch. A crash therefore
    loses at most one batch, while ``scan_run_id`` prevents an older worker from
    overwriting the status of a newer retry.
    """
    from app.gmail.analyzer import AnalysisFailed, analyze_bounded, find_similar
    from app.gmail.scanner import scan

    started = time.monotonic()
    deadline = started + SCAN_TIME_LIMIT_SECONDS
    db = SessionLocal()
    account = None

    def ensure_current() -> None:
        if account is None:
            raise ScanSuperseded()
        try:
            db.refresh(account)
        except Exception as exc:
            db.rollback()
            raise ScanSuperseded() from exc
        if account.scan_run_id != run_id or account.scan_status != "running":
            raise ScanSuperseded()

    def heartbeat(stage: str, processed: int = 0, total: int = 0) -> None:
        ensure_current()
        account.scan_heartbeat_at = _utcnow()
        account.scan_stage = stage
        account.scan_processed = max(0, processed)
        account.scan_total = max(0, total)
        db.commit()

    def fail(message: str) -> None:
        db.rollback()
        try:
            ensure_current()
        except ScanSuperseded:
            return
        account.scan_status = "error"
        account.scan_error = message
        account.scan_stage = None
        account.scan_heartbeat_at = _utcnow()
        db.commit()

    try:
        account = db.query(GmailAccount).filter(
            GmailAccount.user_id == user_id,
            GmailAccount.scan_run_id == run_id,
        ).first()
        if not account:
            return

        try:
            refresh_token = decrypt_token(account.refresh_token_encrypted)
            # Do not pin a database transaction or pooled connection while
            # Gmail performs network I/O. Heartbeats reopen short transactions
            # as needed and still verify scan ownership before every write.
            db.commit()
            fetch_deadline = min(deadline, started + SCAN_FETCH_BUDGET_SECONDS)
            scan_result = scan(
                refresh_token,
                months=SCAN_MONTHS,
                max_messages=MAX_SCAN_MESSAGES,
                on_progress=lambda done, total: heartbeat("reading", done, total),
                deadline=fetch_deadline,
            )
        except TokenUndecryptable:
            logger.error("Undecryptable Gmail token for %s — key mismatch", user_id)
            fail("Gmail needs reconnecting. Disconnect and connect again on the Account page.")
            return
        except RefreshError:
            logger.warning("Gmail refresh token rejected for %s", user_id)
            fail("Google no longer accepts Subtrack's access to this inbox. Disconnect and connect again on the Account page.")
            return

        subscriptions = db.query(Subscription).filter(
            Subscription.user_id == user_id
        ).all()
        existing_detections = db.query(DetectedSubscription).filter(
            DetectedSubscription.user_id == user_id
        ).all()

        def apply_batch(found):
            ensure_current()
            _apply_detections(db, user_id, subscriptions, existing_detections, found)
            account.scan_heartbeat_at = _utcnow()
            db.commit()

        # Reserve time for duplicate hints and the final durable status write.
        analysis_deadline = max(time.monotonic() + 1, deadline - 18)
        try:
            outcome = analyze_bounded(
                scan_result.candidates,
                on_batch=apply_batch,
                on_progress=lambda done, total: heartbeat("analysing", done, total),
                deadline=analysis_deadline,
            )
        except AnalysisFailed:
            logger.exception("Analysis failed entirely for %s", user_id)
            fail("Your inbox was read but couldn't be analysed this time. Try again in a few minutes.")
            return

        heartbeat("finalising", outcome.processed_domains, outcome.selected_domains)
        db.flush()
        pending = [
            row for row in existing_detections
            if row.status == DetectionStatus.pending
        ]
        active = [subscription for subscription in subscriptions if subscription.is_active]
        if pending and active and time.monotonic() < deadline - 2:
            for i, (j, reason) in find_similar(
                pending[:50],
                active[:100],
                deadline=deadline - 2,
            ).items():
                if pending[i].existing_subscription_id is None:
                    pending[i].similar_subscription_id = active[j].id
                    pending[i].similar_reason = reason[:300]

        ensure_current()
        partial = bool(scan_result.truncated or outcome.truncated)
        account.scan_status = "done"
        account.scan_error = None
        account.scan_stage = "complete"
        account.scan_partial = partial
        account.scan_message = (
            "Finished within two minutes using the strongest recurring-payment signals. Some lower-priority receipt emails were skipped."
            if partial
            else "Inbox scan complete. Review anything new below."
        )
        account.scan_processed = outcome.processed_domains
        account.scan_total = outcome.selected_domains
        account.scan_heartbeat_at = _utcnow()
        account.last_scanned_at = _utcnow()
        db.commit()
        logger.info(
            "Scan complete for %s in %.1fs: %d findings, partial=%s",
            user_id,
            time.monotonic() - started,
            len(outcome.subscriptions),
            partial,
        )
    except ScanSuperseded:
        logger.info("Scan %s for %s was superseded", run_id, user_id)
        db.rollback()
    except Exception:
        logger.exception("Scan failed for %s", user_id)
        fail("Could not finish reading your inbox. Try again, or reconnect Gmail if it keeps failing.")
    finally:
        db.close()


def _run_and_release(user_id: str, run_id: str) -> None:
    try:
        _run_scan(user_id, run_id)
    finally:
        _scan_slots.release()


def shutdown_scan_executor() -> None:
    """Let bounded active work finish during Render's shutdown grace period."""
    _scan_executor.shutdown(wait=True, cancel_futures=True)


@router.post("/scan")
def start_scan(
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    if not gmail_is_configured():
        raise HTTPException(
            status_code=503,
            detail="Gmail scanning is not configured for this deployment.",
        )
    account = (
        db.query(GmailAccount)
        .filter(GmailAccount.user_id == user_id)
        .with_for_update()
        .first()
    )
    if not account:
        raise HTTPException(status_code=404, detail="No Gmail account connected")
    if account.scan_status == "running" and not _scan_is_stale(account):
        return {"status": "running", "deadline_seconds": SCAN_TIME_LIMIT_SECONDS}
    if not _scan_slots.acquire(blocking=False):
        raise HTTPException(
            status_code=503,
            detail="The inbox scanner is busy right now. Try again in a minute.",
        )

    run_id = str(uuid4())
    now = _utcnow()
    account.scan_status = "running"
    account.scan_error = None
    account.scan_started_at = now
    account.scan_heartbeat_at = now
    account.scan_run_id = run_id
    account.scan_stage = "queued"
    account.scan_processed = 0
    account.scan_total = 0
    account.scan_partial = False
    account.scan_message = None
    try:
        db.commit()
        _scan_executor.submit(_run_and_release, user_id, run_id)
    except Exception:
        _scan_slots.release()
        db.rollback()
        failed_account = db.query(GmailAccount).filter(
            GmailAccount.user_id == user_id,
            GmailAccount.scan_run_id == run_id,
        ).first()
        if failed_account:
            failed_account.scan_status = "error"
            failed_account.scan_error = "Could not start the inbox scan. Try again shortly."
            failed_account.scan_stage = None
            db.commit()
        logger.exception("Could not queue Gmail scan for %s", user_id)
        raise HTTPException(status_code=503, detail="Could not start the inbox scan. Try again shortly.")

    return {"status": "running", "deadline_seconds": SCAN_TIME_LIMIT_SECONDS}


@router.delete("/disconnect")
def gmail_disconnect(
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    account = db.query(GmailAccount).filter(
        GmailAccount.user_id == user_id,
    ).with_for_update().first()
    if not account:
        raise HTTPException(status_code=404, detail="No Gmail account connected")

    encrypted_token = account.refresh_token_encrypted
    try:
        db.query(GmailOAuthState).filter(
            GmailOAuthState.user_id == user_id,
        ).delete(synchronize_session=False)
        db.delete(account)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error(
            "Gmail disconnect transaction failed (%s)",
            type(exc).__name__,
            extra={"user_id": user_id},
        )
        raise HTTPException(
            status_code=500,
            detail="Gmail could not be disconnected safely. Try again.",
        ) from exc

    # The local token is already gone, which is the privacy boundary Subtrack
    # controls. Google revocation is best-effort and bounded so an upstream
    # outage cannot strand the user's mailbox credentials in our database.
    revocation = revoke_encrypted_refresh_token(encrypted_token)
    return {
        "message": "Disconnected",
        "gmail_revocation": revocation.value,
    }
