"""Bounded, reusable duplicate suggestions and durable false-positive decisions."""

from __future__ import annotations

import hashlib
import json
import time
from threading import BoundedSemaphore, RLock
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import DuplicateDismissal, PaymentStatus, Subscription
from app.services.recurrence import cadence_for, effective_status


DUPLICATE_MODEL_LIMIT = 60
DUPLICATE_CACHE_SECONDS = 600
DUPLICATE_CACHE_USER_LIMIT = 512

# Cache only bounded model output (integer indices and a short reason), never
# ORM objects or financial rows. A dismissal is applied after cache lookup, so
# the user's decision takes effect immediately without another model call.
_duplicate_cache: dict[str, tuple[str, float, list[tuple[int, int, str]]]] = {}
_duplicate_cache_lock = RLock()
_duplicate_model_slots = BoundedSemaphore(2)


def canonical_duplicate_pair(first: UUID, second: UUID) -> tuple[UUID, UUID]:
    if first == second:
        raise ValueError("A payment cannot be compared with itself")
    return (first, second) if str(first) < str(second) else (second, first)


def _fingerprint(rows: list[Subscription]) -> str:
    values = []
    for row in rows:
        cadence = cadence_for(row)
        values.append({
            "id": str(row.id),
            "name": row.name,
            "amount": round(row.amount, 4),
            "currency": row.currency,
            "unit": cadence.unit,
            "count": cadence.count,
            "source_domain": row.source_domain,
            "source_key": row.source_key,
        })
    return hashlib.sha256(
        json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _candidate_rows(db: Session, user_id: str) -> list[Subscription]:
    rows = (
        db.query(Subscription)
        .filter(
            Subscription.user_id == user_id,
            Subscription.is_active == True,  # noqa: E712
            Subscription.status.in_([
                PaymentStatus.active.value,
                PaymentStatus.cancelling.value,
            ]),
        )
        .order_by(Subscription.name, Subscription.id)
        .limit(DUPLICATE_MODEL_LIMIT)
        .all()
    )
    # A recurrence end or cancellation date can make a compatibility `active`
    # row terminal before it is lazily persisted. Keep it out of suggestions.
    return [
        row for row in rows
        if effective_status(row) in {
            PaymentStatus.active.value,
            PaymentStatus.cancelling.value,
        }
    ]


def _valid_model_pairs(
    raw_pairs: object,
    row_count: int,
) -> list[tuple[int, int, str]]:
    if not isinstance(raw_pairs, list):
        return []
    result: list[tuple[int, int, str]] = []
    seen: set[tuple[int, int]] = set()
    for value in raw_pairs:
        if not isinstance(value, (tuple, list)) or len(value) != 3:
            continue
        first, second, reason = value
        if not isinstance(first, int) or not isinstance(second, int):
            continue
        if first == second or not (0 <= first < row_count and 0 <= second < row_count):
            continue
        key = (min(first, second), max(first, second))
        if key in seen:
            continue
        seen.add(key)
        result.append((first, second, str(reason)[:300]))
    return result


def duplicate_suggestions(
    db: Session,
    user_id: str,
) -> tuple[list[Subscription], list[tuple[int, int, str]]]:
    """Return one bounded suggestion set shared by REST and assistant reads."""
    from app.gmail.analyzer import find_duplicates

    rows = _candidate_rows(db, user_id)
    fingerprint = _fingerprint(rows)
    now = time.monotonic()
    with _duplicate_cache_lock:
        cached = _duplicate_cache.get(user_id)
        pairs = (
            cached[2]
            if cached and cached[0] == fingerprint and cached[1] > now
            else None
        )

    if pairs is None:
        # The matcher is network-bound. Release the read transaction and its
        # connection before waiting, but retain the already-loaded detached
        # rows needed by the model and response.
        db.expunge_all()
        db.commit()
        if not _duplicate_model_slots.acquire(blocking=False):
            raise RuntimeError("Duplicate suggestions are busy. Try again shortly.")
        try:
            pairs = _valid_model_pairs(find_duplicates(rows), len(rows))
        finally:
            _duplicate_model_slots.release()
        with _duplicate_cache_lock:
            if len(_duplicate_cache) >= DUPLICATE_CACHE_USER_LIMIT and user_id not in _duplicate_cache:
                _duplicate_cache.pop(next(iter(_duplicate_cache)))
            _duplicate_cache[user_id] = (
                fingerprint,
                time.monotonic() + DUPLICATE_CACHE_SECONDS,
                pairs,
            )

    if not pairs:
        return rows, []

    # At most 60 candidate IDs enter this query, so even a pathological user
    # can return no more than C(60, 2) = 1,770 unique rows here.
    candidate_ids = [row.id for row in rows]
    dismissed = {
        (row.subscription_a_id, row.subscription_b_id)
        for row in db.query(DuplicateDismissal).filter(
            DuplicateDismissal.user_id == user_id,
            DuplicateDismissal.subscription_a_id.in_(candidate_ids),
            DuplicateDismissal.subscription_b_id.in_(candidate_ids),
        ).all()
    }
    visible = []
    for first, second, reason in pairs:
        pair = canonical_duplicate_pair(rows[first].id, rows[second].id)
        if pair not in dismissed:
            visible.append((first, second, reason))
    return rows, visible


def persist_duplicate_dismissal(
    db: Session,
    user_id: str,
    first: UUID,
    second: UUID,
) -> tuple[DuplicateDismissal, bool]:
    """Idempotently persist a canonical pair without committing its caller."""
    subscription_a_id, subscription_b_id = canonical_duplicate_pair(first, second)
    existing = db.query(DuplicateDismissal).filter(
        DuplicateDismissal.user_id == user_id,
        DuplicateDismissal.subscription_a_id == subscription_a_id,
        DuplicateDismissal.subscription_b_id == subscription_b_id,
    ).first()
    if existing:
        return existing, False

    row = DuplicateDismissal(
        id=uuid4(),
        user_id=user_id,
        subscription_a_id=subscription_a_id,
        subscription_b_id=subscription_b_id,
    )
    try:
        # The unique constraint is the final defence against two browser tabs
        # dismissing the same pair concurrently. A savepoint avoids rolling
        # back the assistant confirmation transaction on that harmless race.
        with db.begin_nested():
            db.add(row)
            db.flush()
        return row, True
    except IntegrityError:
        existing = db.query(DuplicateDismissal).filter(
            DuplicateDismissal.user_id == user_id,
            DuplicateDismissal.subscription_a_id == subscription_a_id,
            DuplicateDismissal.subscription_b_id == subscription_b_id,
        ).one()
        return existing, False


def delete_duplicate_dismissals_for_subscription(
    db: Session,
    user_id: str,
    subscription_id: UUID,
) -> int:
    """Portable cleanup in addition to the production FK cascades."""
    return db.query(DuplicateDismissal).filter(
        DuplicateDismissal.user_id == user_id,
        (
            (DuplicateDismissal.subscription_a_id == subscription_id)
            | (DuplicateDismissal.subscription_b_id == subscription_id)
        ),
    ).delete(synchronize_session=False)
