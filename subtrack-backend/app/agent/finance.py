"""Read-only, user-scoped finance analysis for the Subtrack assistant.

These helpers deliberately describe *tracked recurring commitments*.  Subtrack
does not ingest a bank ledger, so calling these values "all spending" would be
misleading.  Currency conversion metadata travels with every aggregate so the
model can distinguish exact totals, current-rate estimates, and incomplete
totals instead of quietly adding unlike currencies.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import (
    ChangeKind,
    DetectedSubscription,
    DetectionStatus,
    Subscription,
    SubscriptionChange,
    UserPreference,
)
from app.routers.rates import get_cached_rate_snapshot
from app.routers.subscriptions import monthly_equivalent
from app.services.schedules import project_next_occurrence
from app.services.reminders import list_user_reminders


SCOPE_NOTE = (
    "Tracked recurring commitments only; this is not a bank-transaction ledger "
    "or a total-spending report."
)


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


def _money(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


def _preference(db: Session, user_id: str) -> UserPreference | None:
    return db.query(UserPreference).filter(UserPreference.user_id == user_id).first()


@dataclass(frozen=True)
class CurrencyContext:
    base: str
    snapshot: dict | None

    @classmethod
    def for_user(cls, db: Session, user_id: str) -> "CurrencyContext":
        pref = _preference(db, user_id)
        base = pref.base_currency if pref else "AUD"
        return cls(base=base, snapshot=get_cached_rate_snapshot(base))

    def convert(
        self,
        amount: float | None,
        currency: str,
        *,
        stored_amount: float | None = None,
    ) -> tuple[float | None, str]:
        if amount is None:
            return None, "not_applicable"
        if currency == self.base:
            return amount, "exact_base_currency"
        if self.snapshot:
            rate = self.snapshot.get("rates", {}).get(currency)
            if rate and rate > 0:
                quality = "stale_current_rate" if self.snapshot.get("stale") else "current_rate"
                return amount / rate, quality
        if stored_amount is not None:
            # This was converted when the record was entered.  The old schema
            # did not record the target currency, so it is useful but must be
            # labelled as an estimate rather than asserted as exact.
            return stored_amount, "stored_entry_rate_estimate"
        return None, "unconverted"

    def metadata(self, qualities: Iterable[str]) -> dict:
        quality_set = set(qualities)
        incomplete = "unconverted" in quality_set
        estimated = bool(
            quality_set & {"stale_current_rate", "stored_entry_rate_estimate"}
        )
        if incomplete:
            status = "incomplete"
        elif estimated:
            status = "estimated"
        elif "current_rate" in quality_set:
            status = "current_rates"
        else:
            status = "exact"
        return {
            "base_currency": self.base,
            "status": status,
            "rates_as_of": self.snapshot.get("fetched_at") if self.snapshot else None,
            "rates_stale": bool(self.snapshot and self.snapshot.get("stale")),
            "warning": (
                "Some foreign-currency payments could not be converted and are excluded from aggregates."
                if incomplete
                else "Foreign-currency values use an older or stored rate and should be described as estimates."
                if estimated
                else None
            ),
        }


def _active_subscriptions(db: Session, user_id: str) -> list[Subscription]:
    return (
        db.query(Subscription)
        .filter(Subscription.user_id == user_id, Subscription.is_active == True)  # noqa: E712
        .all()
    )


def _payment_payload(sub: Subscription, currency: CurrencyContext) -> tuple[dict, str]:
    base_amount, quality = currency.convert(
        sub.amount,
        sub.currency,
        stored_amount=sub.converted_amount,
    )
    monthly = monthly_equivalent(base_amount, sub.cycle) if base_amount is not None else None
    return {
        "id": str(sub.id),
        "name": sub.name,
        "category": _enum_value(sub.category),
        "amount": _money(sub.amount),
        "currency": sub.currency,
        "cycle": _enum_value(sub.cycle),
        "monthly_in_base": _money(monthly),
        "base_currency": currency.base,
        "conversion_quality": quality,
        "next_due": sub.next_due.isoformat() if sub.next_due else None,
        "is_shared": sub.split_mode != "full",
        "user_share": _money(sub.amount),
        "full_bill": _money(sub.full_amount),
    }, quality


def financial_overview(db: Session, user_id: str) -> dict:
    subs = _active_subscriptions(db, user_id)
    currency = CurrencyContext.for_user(db, user_id)
    qualities: list[str] = []
    total = 0.0
    converted_count = 0
    categories: dict[str, float] = {}
    unconverted: list[dict] = []

    for sub in subs:
        base_amount, quality = currency.convert(
            sub.amount,
            sub.currency,
            stored_amount=sub.converted_amount,
        )
        qualities.append(quality)
        if base_amount is None:
            unconverted.append({
                "id": str(sub.id),
                "name": sub.name,
                "amount": _money(sub.amount),
                "currency": sub.currency,
                "cycle": _enum_value(sub.cycle),
            })
            continue
        monthly = monthly_equivalent(base_amount, sub.cycle)
        converted_count += 1
        total += monthly
        category = _enum_value(sub.category)
        categories[category] = categories.get(category, 0.0) + monthly

    pref = _preference(db, user_id)
    income = pref.monthly_income if pref else None
    category_rows = [
        {
            "category": category,
            "monthly": _money(amount),
            "share_of_recurring_total_percent": round(amount / total * 100, 1) if total else 0,
        }
        for category, amount in sorted(categories.items(), key=lambda item: item[1], reverse=True)
    ]
    return {
        "scope": SCOPE_NOTE,
        "active_payment_count": len(subs),
        "included_in_aggregate_count": converted_count,
        "monthly_recurring_total": _money(total),
        "yearly_recurring_total": _money(total * 12),
        "base_currency": currency.base,
        "monthly_income": _money(income),
        "recurring_share_of_income_percent": (
            round(total / income * 100, 1) if income and income > 0 else None
        ),
        "categories": category_rows,
        "unconverted_payments": unconverted,
        "currency_conversion": currency.metadata(qualities),
    }


def list_payments(db: Session, user_id: str, tool_input: dict) -> dict:
    subs = _active_subscriptions(db, user_id)
    selected = tool_input.get("subscription_ids") or []
    if selected:
        wanted = set(selected[:25])
        subs = [sub for sub in subs if str(sub.id) in wanted]
    category = tool_input.get("category")
    if category:
        subs = [sub for sub in subs if _enum_value(sub.category) == category]
    query = (tool_input.get("query") or "").strip().casefold()
    if query:
        subs = [sub for sub in subs if query in sub.name.casefold()]

    currency = CurrencyContext.for_user(db, user_id)
    rows_with_quality = [_payment_payload(sub, currency) for sub in subs]
    sort_by = tool_input.get("sort_by", "monthly_cost")
    if sort_by == "name":
        rows_with_quality.sort(key=lambda item: item[0]["name"].casefold())
    elif sort_by == "next_due":
        rows_with_quality.sort(key=lambda item: item[0]["next_due"] or "9999")
    else:
        rows_with_quality.sort(
            key=lambda item: item[0]["monthly_in_base"] if item[0]["monthly_in_base"] is not None else -1,
            reverse=True,
        )
    limit = max(1, min(int(tool_input.get("limit", 50)), 100))
    limited = rows_with_quality[:limit]
    rows = [row for row, _ in limited]
    return {
        "scope": SCOPE_NOTE,
        "payments": rows,
        "returned_count": len(rows),
        "matching_count": len(rows_with_quality),
        "currency_conversion": currency.metadata(quality for _, quality in limited),
    }


def payment_detail(db: Session, user_id: str, subscription_id: str) -> dict:
    try:
        identifier = UUID(subscription_id)
    except (TypeError, ValueError):
        return {"found": False, "reason": "invalid_subscription_id"}
    sub = db.query(Subscription).filter(
        Subscription.id == identifier,
        Subscription.user_id == user_id,
        Subscription.is_active == True,  # noqa: E712
    ).first()
    if not sub:
        return {"found": False, "reason": "payment_not_found"}
    currency = CurrencyContext.for_user(db, user_id)
    payload, quality = _payment_payload(sub, currency)
    return {
        "found": True,
        "scope": SCOPE_NOTE,
        "payment": payload,
        "currency_conversion": currency.metadata([quality]),
    }


def upcoming_charges(
    db: Session,
    user_id: str,
    days: int = 30,
    *,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    days = max(1, min(int(days), 365))
    end = now + timedelta(days=days)
    currency = CurrencyContext.for_user(db, user_id)
    rows: list[dict] = []
    qualities: list[str] = []
    missing_due_count = 0
    for sub in _active_subscriptions(db, user_id):
        due, source = project_next_occurrence(sub.next_due, sub.cycle, now)
        if not due:
            missing_due_count += 1
            continue
        if due > end:
            continue
        payload, quality = _payment_payload(sub, currency)
        qualities.append(quality)
        rows.append({
            **payload,
            "due_at": due.isoformat(),
            "days_until_due": max(0, (due.date() - now.date()).days),
            "due_date_source": source,
        })
    rows.sort(key=lambda row: (row["due_at"], row["name"].casefold()))
    return {
        "scope": SCOPE_NOTE,
        "window_days": days,
        "charges": rows,
        "missing_due_date_count": missing_due_count,
        "currency_conversion": currency.metadata(qualities),
    }


def _period_start(period: str, now: datetime) -> datetime:
    if period == "last_90_days":
        return now - timedelta(days=90)
    if period == "last_30_days":
        return now - timedelta(days=30)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def commitment_changes(
    db: Session,
    user_id: str,
    period: str = "current_month",
    *,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    period = period if period in {"current_month", "last_30_days", "last_90_days"} else "current_month"
    start = _period_start(period, now)
    changes = (
        db.query(SubscriptionChange)
        .filter(
            SubscriptionChange.user_id == user_id,
            SubscriptionChange.changed_at >= start,
            SubscriptionChange.changed_at <= now,
        )
        .order_by(SubscriptionChange.changed_at.desc())
        .all()
    )
    currency = CurrencyContext.for_user(db, user_id)
    rows: list[dict] = []
    qualities: list[str] = []
    net = 0.0
    incomplete = False
    for change in changes:
        old_base, old_quality = currency.convert(change.old_monthly, change.currency)
        new_base, new_quality = currency.convert(change.new_monthly, change.currency)
        relevant = [q for q in (old_quality, new_quality) if q != "not_applicable"]
        qualities.extend(relevant)
        delta = None
        if (change.old_monthly is None or old_base is not None) and (
            change.new_monthly is None or new_base is not None
        ):
            delta = (new_base or 0) - (old_base or 0)
            net += delta
        else:
            incomplete = True
        rows.append({
            "id": str(change.id),
            "subscription_id": str(change.subscription_id),
            "name": change.name,
            "kind": _enum_value(change.kind),
            "old_monthly_native": _money(change.old_monthly),
            "new_monthly_native": _money(change.new_monthly),
            "native_currency": change.currency,
            "delta_monthly_in_base": _money(delta),
            "base_currency": currency.base,
            "changed_at": change.changed_at.isoformat() if change.changed_at else None,
        })
    conversion = currency.metadata(qualities + (["unconverted"] if incomplete else []))
    return {
        "scope": SCOPE_NOTE,
        "period": period,
        "period_start": start.isoformat(),
        "period_end": now.isoformat(),
        "net_monthly_commitment_change": _money(net),
        "base_currency": currency.base,
        "changes": rows,
        "currency_conversion": conversion,
    }


def duplicate_payments(db: Session, user_id: str) -> dict:
    # Keep the model-assisted matcher isolated to this explicitly requested
    # tool.  It returns suggestions only; no merge or delete action is exposed.
    from app.gmail.analyzer import find_duplicates

    subs = sorted(_active_subscriptions(db, user_id), key=lambda sub: sub.name.casefold())
    pairs = []
    for keep, merge, reason in find_duplicates(subs):
        pairs.append({
            "keep": {"id": str(subs[keep].id), "name": subs[keep].name},
            "possible_duplicate": {"id": str(subs[merge].id), "name": subs[merge].name},
            "reason": reason,
            "effect": "Both records are currently included in Subtrack totals. This does not prove two bank charges occurred.",
        })
    return {
        "scope": SCOPE_NOTE,
        "suggestions": pairs,
        "suggestion_count": len(pairs),
        "requires_user_confirmation": True,
    }


def review_detections(db: Session, user_id: str, tool_input: dict) -> dict:
    """Return inbox findings that have not silently entered tracked totals."""
    status_value = tool_input.get("status", "pending")
    status = DetectionStatus.dismissed if status_value == "dismissed" else DetectionStatus.pending
    query = db.query(DetectedSubscription).filter(
        DetectedSubscription.user_id == user_id,
        DetectedSubscription.status == status,
    )
    visible_ids = tool_input.get("detection_ids") or []
    if visible_ids:
        valid_ids = []
        for value in visible_ids[:25]:
            try:
                valid_ids.append(UUID(value))
            except (TypeError, ValueError):
                continue
        if not valid_ids:
            return {
                "scope": "Unapproved inbox detections; excluded from recurring totals until approved.",
                "status": status_value,
                "detections": [],
                "matching_count": 0,
            }
        query = query.filter(DetectedSubscription.id.in_(valid_ids))
    rows = query.order_by(
        DetectedSubscription.charge_count.desc(),
        DetectedSubscription.detected_at.desc(),
    ).limit(max(1, min(int(tool_input.get("limit", 25)), 50))).all()
    return {
        "scope": "Unapproved inbox detections; excluded from recurring totals until approved.",
        "status": status_value,
        "detections": [
            {
                "id": str(row.id),
                "merchant": row.merchant,
                "amount": _money(row.amount),
                "currency": row.currency,
                "cycle": _enum_value(row.cycle),
                "category": _enum_value(row.category),
                "confidence": row.confidence,
                "charge_count": row.charge_count,
                "cancelled": row.cancelled,
                "is_price_change": row.existing_subscription_id is not None,
                "matches_existing_payment": row.existing_subscription_id is not None,
                "possible_duplicate_record": row.similar_subscription_id is not None,
                "detected_at": row.detected_at.isoformat() if row.detected_at else None,
            }
            for row in rows
        ],
        "matching_count": len(rows),
        "requires_user_review": True,
    }


def reminders_overview(db: Session, user_id: str, tool_input: dict) -> dict:
    requested_ids = []
    for value in (tool_input.get("reminder_ids") or [])[:25]:
        try:
            requested_ids.append(UUID(value))
        except (TypeError, ValueError):
            continue
    requested_status = tool_input.get("status", "all")
    include_dismissed = requested_status == "dismissed"
    rows = list_user_reminders(
        db,
        user_id,
        reminder_ids=requested_ids or None,
        include_dismissed=include_dismissed,
        horizon_days=max(1, min(int(tool_input.get("horizon_days", 90)), 730)),
    )
    if requested_status != "all":
        rows = [row for row in rows if row["status"] == requested_status]
    return {
        "scope": "In-app reminders attached to the user's tracked recurring payments.",
        "reminders": rows,
        "reminder_count": len(rows),
        "delivery": "Shown inside Subtrack; email and push delivery are not enabled.",
        "read_only": True,
    }


def saving_candidates(db: Session, user_id: str, limit: int = 5) -> dict:
    limit = max(1, min(int(limit), 10))
    currency = CurrencyContext.for_user(db, user_id)
    rows: list[tuple[Subscription, dict, str]] = []
    for sub in _active_subscriptions(db, user_id):
        payload, quality = _payment_payload(sub, currency)
        if payload["monthly_in_base"] is not None:
            rows.append((sub, payload, quality))
    rows.sort(key=lambda item: item[1]["monthly_in_base"], reverse=True)

    recent_cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=90)
    increases = (
        db.query(SubscriptionChange)
        .filter(
            SubscriptionChange.user_id == user_id,
            SubscriptionChange.kind == ChangeKind.price_change,
            SubscriptionChange.changed_at >= recent_cutoff,
        )
        .order_by(SubscriptionChange.changed_at.desc())
        .all()
    )
    increased_ids = {str(change.subscription_id) for change in increases}
    candidates = []
    for sub, payload, _ in rows[:limit]:
        reasons = ["one of your largest tracked monthly commitments"]
        if str(sub.id) in increased_ids:
            reasons.append("its recorded monthly cost increased in the last 90 days")
        candidates.append({
            "id": payload["id"],
            "name": payload["name"],
            "monthly_in_base": payload["monthly_in_base"],
            "base_currency": currency.base,
            "evidence": reasons,
            "necessity_assessment": "unknown — only the user can decide whether it is valuable or necessary",
        })
    return {
        "scope": SCOPE_NOTE,
        "candidates": candidates,
        "note": (
            "This is an evidence-led review shortlist, not a claim that any payment is unnecessary "
            "and not a promise that cancelling is possible or penalty-free."
        ),
        "currency_conversion": currency.metadata(quality for _, _, quality in rows[:limit]),
    }
