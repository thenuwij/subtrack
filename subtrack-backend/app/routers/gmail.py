import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import BoundedSemaphore
from urllib.parse import quote
from uuid import uuid4

# Google returns scopes in a different order/spelling than requested (and drops
# any the user declines). Without this, oauthlib aborts the exchange with a raw
# "Scope has changed" error. We relax it here and check the granted scopes
# ourselves below, so a declined permission produces a useful message.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from google.auth.exceptions import RefreshError
from google_auth_oauthlib.flow import Flow
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal, get_db
from app.gmail.crypto import TokenUndecryptable, decrypt_token, encrypt_token
from app.middleware.auth import verify_token
from app.models import (
    DetectedSubscription,
    DetectionStatus,
    GmailAccount,
    Subscription,
)
from app.services.schedules import utc_naive

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
    frontend = settings.allowed_origins.split(",")[0]

    def failed(reason: str, detail: str = "") -> RedirectResponse:
        """Land back in the app with something readable.

        Google has already redirected the browser here, so raising would leave
        the user staring at raw JSON on an API domain with no way back.
        """
        logger.error("Gmail connect failed for %s: %s %s", user_id, reason, detail)
        return RedirectResponse(f"{frontend}/account?gmail_error={quote(reason)}")

    flow = _build_flow()
    try:
        flow.fetch_token(code=code)
    except Exception as exc:
        return failed(
            "Google rejected the sign-in. If this account isn't listed under Test "
            "users on the OAuth consent screen, add it and try again.",
            str(exc),
        )

    credentials = flow.credentials

    granted = set(credentials.scopes or [])
    if GMAIL_READONLY not in granted:
        return failed(
            "Gmail access wasn't granted. On the Google screen, tick "
            "\u201cView your email messages and settings\u201d \u2014 it is unticked by default."
        )

    if not credentials.refresh_token:
        return failed(
            "Google didn't return long-lived access. Remove Subtrack at "
            "myaccount.google.com/permissions, then connect again."
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
    return RedirectResponse(f"{frontend}/account?gmail=connected")


AMOUNT_TOLERANCE = 0.05  # ignore sub-5-cent differences (rounding, FX wobble)

# Every scan looks back 3 months. Six was measured to be better at catching
# slow-cycling bills — an every-2-months energy bill shows 4 charges in 6
# months but only 1 in 3, too few to establish a cycle — but it costs roughly
# double the emails, model calls and wall time on every scan. While the app is
# early, speed wins; revisit the deeper window (or a deep first scan and
# shallow rescans, which is what this used to do) once scans feel fast.
SCAN_MONTHS = 3

# Scans stop accepting work at 105 seconds. The remaining 15 seconds before the
# two-minute UX promise cover the last database commit and the frontend's next
# poll. A heartbeat older than three minutes therefore cannot be legitimate.
SCAN_TIME_LIMIT_SECONDS = 105
SCAN_FETCH_BUDGET_SECONDS = 35
STALE_SCAN_MINUTES = 3
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


def _scan_is_stale(account: GmailAccount) -> bool:
    """Has a scan been marked running for longer than one could possibly take?

    Without this a single crashed scan locks the user out permanently: the
    endpoint sees "running" and declines to start another, forever.
    """
    heartbeat = account.scan_heartbeat_at or account.scan_started_at
    if heartbeat is None:
        return True      # pre-dates the timestamp, or never recorded — don't stay stuck
    return _utcnow() - heartbeat > timedelta(minutes=STALE_SCAN_MINUTES)


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
        if previous is not None and previous.status != DetectionStatus.pending:
            if tracked is None or (_same_price(tracked, found) and not trial_changed):
                continue

        existing_sub_id = None
        if tracked is not None:
            if _same_price(tracked, found) and tracked.is_active and not trial_changed:
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
        row.trial_ends_at = utc_naive(found.trial_ends_at) if found.trial_ends_at else None
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
            fetch_deadline = min(deadline, started + SCAN_FETCH_BUDGET_SECONDS)
            scan_result = scan(
                decrypt_token(account.refresh_token_encrypted),
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
    account = db.query(GmailAccount).filter(GmailAccount.user_id == user_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="No Gmail account connected")
    db.delete(account)
    db.commit()
    return {"message": "Disconnected"}
